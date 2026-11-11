"""Complemento do projeto: execute com py iniciar.py na pasta do site."""

import io
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

import fitz
from flask import Response, jsonify, request, send_file

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph

import servidor


app = servidor.app
validar_original = servidor.validar_analise

VERSAO = "revisao-pdf-1"


def linguagens(texto):
    nomes = (
        "Python",
        "C++",
        "C#",
        "C",
        "JavaScript",
        "Java",
        "SQL",
        "TypeScript",
        "Rust",
    )

    return [
        nome
        for nome in nomes
        if re.search(
            r"(?<![\w+#])"
            + re.escape(nome)
            + r"(?![\w+#])",
            texto,
            re.IGNORECASE,
        )
    ]


def validar_com_objetivo(resultado, curriculo, vaga):
    analise = validar_original(resultado, curriculo, vaga)

    if (
        analise.get("aguardando_confirmacao")
        or analise.get("alteracoes")
    ):
        return analise

    comuns = [
        nome
        for nome in linguagens(vaga)
        if nome in linguagens(curriculo)
    ]

    if not comuns:
        return analise

    # Só adapta objetivos de estágio genéricos já existentes.
    objetivo = re.search(
        r"(?im)^\s*(Estágio em (?:Tecnologia da Informação|TI)\.)\s*$",
        curriculo,
    )

    if not objetivo:
        return analise

    linguagens_foco = comuns[:2]

    original = objetivo.group(1)
    sugerido = (
        "Estágio em "
        + " e ".join(linguagens_foco)
        + "."
    )

    evidencias = [
        linha.strip()
        for linha in curriculo.splitlines()
        if any(
            nome in linguagens(linha)
            for nome in linguagens_foco
        )
    ]

    requisitos = [
        linha.strip()
        for linha in vaga.splitlines()
        if any(
            nome in linguagens(linha)
            for nome in linguagens_foco
        )
    ]

    if not evidencias or not requisitos:
        return analise

    analise["alteracoes"] = [
        {
            "original": original,
            "sugerido": sugerido,
            "trecho_vaga": " | ".join(requisitos),
            "evidencia_curriculo": " | ".join(evidencias[:3]),
            "motivo": (
                "Sugestão do aplicativo: destacar no objetivo as "
                "linguagens mencionadas tanto na vaga quanto no "
                "currículo. Não altera seu nível de conhecimento. "
                "Se não representar seu objetivo, não selecione."
            ),
        }
    ]

    analise.setdefault("observacoes", []).append(
        "A sugestão de objetivo foi criada por regras do aplicativo, "
        "não pelo modelo. Confira se o objetivo corresponde à "
        "oportunidade e ao que você deseja."
    )

    return analise


# Mantém a análise existente e acrescenta a sugestão de objetivo.
servidor.validar_analise = validar_com_objetivo


def aplicar_no_texto(texto, alteracoes):
    if not isinstance(alteracoes, list) or len(alteracoes) > 20:
        raise ValueError("Seleção de alterações inválida.")

    substituicoes = []

    for item in alteracoes:
        if not isinstance(item, dict):
            raise ValueError("Alteração inválida.")

        original = item.get("original")
        sugerido = item.get("sugerido")

        if not all(
            isinstance(t, str) and t.strip()
            for t in (original, sugerido)
        ):
            raise ValueError(
                "Uma alteração está vazia ou inválida."
            )

        if len(original) > 2000 or len(sugerido) > 2000:
            raise ValueError(
                "Uma alteração ultrapassa o limite de tamanho."
            )

        padrao = (
            r"(?<![\w+#])"
            + r"\s+".join(
                re.escape(parte)
                for parte in original.strip().split()
            )
            + r"(?![\w+#])"
        )

        ocorrencias = list(re.finditer(padrao, texto))

        if len(ocorrencias) != 1:
            raise ValueError(
                "Um trecho não foi encontrado exatamente uma vez. "
                "Volte e confira a sugestão selecionada."
            )

        inicio, fim = ocorrencias[0].span()

        if any(
            inicio < anterior_fim and fim > anterior_inicio
            for anterior_inicio, anterior_fim, _ in substituicoes
        ):
            raise ValueError(
                "Duas sugestões selecionadas alteram o mesmo trecho. "
                "Escolha uma delas."
            )

        substituicoes.append(
            (inicio, fim, sugerido.strip())
        )

    # Aplica do final para o começo para preservar as posições.
    for inicio, fim, novo in sorted(
        substituicoes,
        reverse=True,
    ):
        texto = texto[:inicio] + novo + texto[fim:]

    return texto


def gerar_pdf_organizado(texto):
    # Este é um modelo novo, com visual diferente do original.
    saida = io.BytesIO()

    documento = SimpleDocTemplate(
        saida,
        pagesize=(595.28, 841.89),
        rightMargin=42,
        leftMargin=42,
        topMargin=38,
        bottomMargin=38,
        title="Currículo",
        author="",
    )

    normal = "Helvetica"
    negrito = "Helvetica-Bold"

    fontes_disponiveis = [
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        ),
        (
            Path(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            ),
            Path(
                "/usr/share/fonts/truetype/dejavu/"
                "DejaVuSans-Bold.ttf"
            ),
        ),
    ]

    for arquivo_normal, arquivo_negrito in fontes_disponiveis:
        if (
            arquivo_normal.is_file()
            and arquivo_negrito.is_file()
        ):
            pdfmetrics.registerFont(
                TTFont("CVNormal", str(arquivo_normal))
            )

            pdfmetrics.registerFont(
                TTFont("CVNegrito", str(arquivo_negrito))
            )

            normal = "CVNormal"
            negrito = "CVNegrito"
            break

    corpo = ParagraphStyle(
        "corpo",
        fontName=normal,
        fontSize=9.5,
        leading=13,
        spaceAfter=3,
        textColor=colors.HexColor("#253047"),
    )

    titulo = ParagraphStyle(
        "nome",
        parent=corpo,
        fontName=negrito,
        fontSize=17,
        leading=22,
        spaceAfter=9,
    )

    secao = ParagraphStyle(
        "secao",
        parent=corpo,
        fontName=negrito,
        fontSize=10,
        leading=14,
        spaceBefore=9,
        spaceAfter=5,
        textColor=colors.HexColor("#183b56"),
        keepWithNext=True,
    )

    paragrafos = []
    secao_atual = ""

    for bloco in re.split(r"\n\s*\n", texto):
        corrente = ""

        for linha in bloco.splitlines():
            linha = linha.strip()

            if not linha:
                continue

            cabecalho = (
                linha.isupper()
                and len(linha) < 65
            )

            independente = (
                cabecalho
                or linha.startswith(("-", "•"))
                or "|" in linha
                or re.match(r"^[^:]{1,40}:", linha)
                or secao_atual in {
                    "CURSOS COMPLEMENTARES",
                    "IDIOMAS",
                    "FORMAÇÃO ACADÊMICA",
                }
            )

            if independente and corrente:
                paragrafos.append(corrente)
                corrente = ""

            if cabecalho:
                paragrafos.append(linha)
                secao_atual = linha

            elif independente:
                corrente = linha

            else:
                corrente = (
                    corrente + " " + linha
                ).strip()

        if corrente:
            paragrafos.append(corrente)

    elementos = []
    primeira = True

    for linha in paragrafos:
        linha = linha.strip()

        if not linha:
            continue

        if primeira:
            estilo = titulo
            primeira = False

        elif linha.isupper() and len(linha) < 65:
            estilo = secao

        else:
            estilo = corpo

        elementos.append(
            Paragraph(escape(linha), estilo)
        )

    if not elementos:
        raise ValueError(
            "O PDF não contém texto para gerar o modelo organizado."
        )

    documento.build(elementos)

    return saida.getvalue()


@app.get("/api/estado")
def estado_complemento():
    return jsonify(
        versao=VERSAO,
        pdf_organizado=True,
    )


@app.post("/api/pdf-organizado")
def pdf_organizado():
    arquivo = request.files.get("pdf")

    if not arquivo:
        return jsonify(
            erro="Anexe o PDF original."
        ), 400

    try:
        alteracoes = json.loads(
            request.form.get("alteracoes", "[]")
        )

        if (
            not isinstance(alteracoes, list)
            or len(alteracoes) > 20
        ):
            raise ValueError(
                "Seleção de alterações inválida."
            )

        dados = arquivo.read()

        if not dados:
            raise ValueError("O arquivo está vazio.")

        # Sem seleção, devolve os bytes do original.
        if not alteracoes:
            return send_file(
                io.BytesIO(dados),
                mimetype="application/pdf",
                download_name="curriculo_original.pdf",
            )

        with fitz.open(
            stream=dados,
            filetype="pdf",
        ) as pdf:
            if pdf.needs_pass or pdf.page_count > 30:
                raise ValueError(
                    "PDF protegido ou com mais de 30 páginas."
                )

            texto = "\n\n".join(
                bloco[4].strip()
                for pagina in pdf
                for bloco in pagina.get_text("blocks")
                if bloco[6] == 0
            )

        if not texto.strip():
            raise ValueError(
                "O PDF não contém texto selecionável."
            )

        novo = aplicar_no_texto(texto, alteracoes)
        pdf_saida = gerar_pdf_organizado(novo)

        return send_file(
            io.BytesIO(pdf_saida),
            mimetype="application/pdf",
            download_name="curriculo_modelo_organizado.pdf",
        )

    except (
        ValueError,
        RuntimeError,
        fitz.FileDataError,
    ) as erro:
        return jsonify(
            erro=str(erro)
        ), 400


# Acrescenta um botão à página sem substituir teu script.js.
SCRIPT = r'''
(() => {
  const original = document.querySelector("#gerar-pdf");

  if (!original) {
    return;
  }

  const aviso = document.createElement("p");

  aviso.textContent =
    "Versão de teste: modelo organizado disponível. " +
    "Ele gera um novo visual; não preserva o layout do PDF enviado.";

  const botao = document.createElement("button");

  botao.type = "button";
  botao.className = "secundario";
  botao.textContent = "Gerar PDF em modelo organizado";

  original.parentElement.insertBefore(aviso, original);

  original.parentElement.insertBefore(
    botao,
    original.nextSibling
  );

  let executando = false;

  botao.addEventListener("click", async () => {
    if (executando) {
      return;
    }

    const arquivo = document.querySelector("#arquivo").files[0];
    const mensagem = document.querySelector("#pdf-mensagem");
    const previa = document.querySelector("#pdf-previa");
    const baixar = document.querySelector("#pdf-download");

    if (!arquivo) {
      mensagem.textContent = "Anexe o PDF original.";
      return;
    }

    const selecionadas = Array.from(
      document.querySelectorAll(".selecionar-alteracao:checked"),
      caixa => sugestoes[Number(caixa.value)]
    );

    const dados = new FormData();

    dados.append("pdf", arquivo);
    dados.append("alteracoes", JSON.stringify(selecionadas));

    executando = true;
    botao.disabled = true;
    original.disabled = true;

    previa.hidden = true;
    baixar.hidden = true;

    mensagem.textContent = "Gerando PDF...";

    try {
      const resposta = await fetch("/api/pdf-organizado", {
        method: "POST",
        body: dados
      });

      if (!resposta.ok) {
        let erro;

        try {
          erro = await resposta.json();
        } catch (_) {
          erro = {};
        }

        throw new Error(
          erro.erro || "Não foi possível gerar o PDF."
        );
      }

      const blob = await resposta.blob();

      if (pdfUrl) {
        URL.revokeObjectURL(pdfUrl);
      }

      pdfUrl = URL.createObjectURL(blob);

      previa.src = pdfUrl;
      baixar.href = pdfUrl;

      baixar.download = selecionadas.length
        ? "curriculo_modelo_organizado.pdf"
        : "curriculo_original.pdf";

      previa.hidden = false;
      baixar.hidden = false;

      mensagem.textContent = selecionadas.length
        ? "Novo modelo gerado com as alterações selecionadas. " +
          "Confira todo o conteúdo e o visual antes de baixar."
        : "Nenhuma alteração selecionada: este é o PDF original.";

    } catch (erro) {
      mensagem.textContent = erro.message;

    } finally {
      executando = false;
      botao.disabled = false;
      original.disabled = false;
    }
  });
})();
'''


@app.get("/complemento-pdf.js")
def complemento_javascript():
    return Response(
        SCRIPT,
        mimetype="application/javascript",
    )


@app.after_request
def acrescentar_complemento(resposta):
    if (
        request.path == "/"
        and resposta.status_code == 200
        and resposta.mimetype == "text/html"
    ):
        resposta.direct_passthrough = False

        html = resposta.get_data(as_text=True)

        html = html.replace(
            "</body>",
            '<script src="/complemento-pdf.js"></script></body>',
        )

        resposta.set_data(html)
        resposta.headers["Cache-Control"] = "no-store"

    return resposta


if __name__ == "__main__":
    print("Adaptador de currículo: " + VERSAO)
    print(
        "Arquivo principal: "
        + str(Path(__file__).resolve())
    )

    app.run(
        host="127.0.0.1",
        port=8000,
        debug=False,
    )