"""Execute: py fontes.py."""

import io
import os
import json
import re
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

import fitz
from PIL import Image

from flask import Response, jsonify, request
from werkzeug.datastructures import ImmutableMultiDict

import personalizar
import revisar
import servidor

app = personalizar.app
ESTADO_ANTERIOR = app.view_functions["estado_complemento"]

VERSAO = "resposta-estruturada-13"
PASTA_IDIOMAS = Path(__file__).resolve().parent / "tessdata"


@app.post("/api/ler-curriculo")
def ler_curriculo_local():
    arquivo = request.files.get("pdf")

    if not arquivo:
        return jsonify(erro="Anexe o currículo em PDF."), 400

    try:
        dados = arquivo.read()

        if not dados:
            raise ValueError("O PDF está vazio.")

        with fitz.open(stream=dados, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise ValueError(
                    "O currículo está protegido por senha."
                )

            if not 1 <= pdf.page_count <= 30:
                raise ValueError(
                    "Use um currículo com até 30 páginas."
                )

            paginas = pdf.page_count

            texto = "\n\n".join(
                bloco[4].strip()
                for pagina in pdf
                for bloco in pagina.get_text("blocks")
                if bloco[6] == 0
            ).strip()

        if not texto:
            raise ValueError(
                "Este PDF não contém texto selecionável. "
                "Envie uma versão exportada como texto, "
                "ou use OCR antes de anexar."
            )

        if len(texto) > servidor.MAX_TEXTO_CURRICULO:
            raise ValueError(
                "O currículo ultrapassa o limite de texto "
                "desta versão."
            )

        return jsonify(
            texto=texto,
            paginas=paginas,
            leitor="PyMuPDF local",
        )

    except (
        ValueError,
        RuntimeError,
        fitz.FileDataError,
    ) as erro:
        return jsonify(erro=str(erro)), 400


LEITOR_JS = r"""
async function lerTextoPdf(arquivo) {
  const dados = new FormData();
  dados.append('pdf', arquivo);

  const resposta = await requisitarApi(
    '/api/ler-curriculo',
    {method: 'POST', body: dados}
  );

  const resultado = await lerRespostaJson(
    resposta,
    'a leitura local do currículo'
  );

  if (
    typeof resultado.texto !== 'string' ||
    !resultado.texto.trim()
  ) {
    throw new Error(
      'O servidor não retornou texto do currículo.'
    );
  }

  return resultado.texto;
}
"""


def script_projeto_local():
    caminho = Path(__file__).resolve().parent / "script.js"

    if not caminho.is_file():
        return Response(
            "throw new Error("
            "'script.js não encontrado na pasta do projeto.');",
            mimetype="application/javascript",
            status=404,
        )

    codigo = caminho.read_text(encoding="utf-8-sig")

    codigo, leitores = re.subn(
        r'^async function lerTextoPdf\(arquivo\)\s*\{.*?^\}',
        lambda _: LEITOR_JS,
        codigo,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )

    codigo = re.sub(
        r'  if \(typeof pdfjsLib === "undefined"\) '
        r'\{.*?^  \}\s*',
        '',
        codigo,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )

    if leitores != 1:
        return Response(
            "throw new Error("
            "'Versão de script.js incompatível com o leitor local.');",
            mimetype="application/javascript",
            status=500,
        )

    return Response(
        codigo,
        mimetype="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


app.view_functions["arquivo_javascript"] = script_projeto_local


def lista_estruturada(*campos):
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                nome: {"type": "string"}
                for nome in campos
            },
            "required": list(campos),
            "additionalProperties": False,
        },
    }


FORMATO_ANALISE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "transcricao_vaga": {"type": "string"},
        "requisitos_vaga": lista_estruturada(
            "trecho_vaga",
        ),
        "pontos_encontrados": lista_estruturada(
            "trecho_vaga",
            "evidencia_curriculo",
            "explicacao",
        ),
        "alteracoes": lista_estruturada(
            "original",
            "sugerido",
            "trecho_vaga",
            "evidencia_curriculo",
            "motivo",
        ),
    },
    "required": [
        "requisitos_vaga",
        "pontos_encontrados",
        "alteracoes",
    ],
}


def analisar_texto_estruturado():
    curriculo = request.form.get("curriculo", "").strip()
    vaga = request.form.get("vaga", "").strip()

    if not curriculo or not vaga:
        return jsonify(
            erro="Não foi recebido texto do currículo ou da vaga."
        ), 400

    if (
        len(curriculo) > servidor.MAX_TEXTO_CURRICULO
        or len(vaga) > servidor.MAX_TEXTO_VAGA
    ):
        return jsonify(
            erro="O currículo ou a vaga ultrapassa o limite de texto."
        ), 400

    if not revisar.TRAVA_ANALISE.acquire(blocking=False):
        return jsonify(
            erro="Já existe uma análise em andamento. Aguarde."
        ), 409

    try:
        corpo = {
            "model": revisar.MODELO_TEXTO,
            "stream": False,
            "format": FORMATO_ANALISE,
            "options": {
                "temperature": 0,
                "num_ctx": 32768,
                "num_predict": 8192,
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        servidor.INSTRUCOES
                        + "\nRespeite o esquema obrigatório. "
                        "Use [] quando não houver itens. "
                        "Não omita campos. Esquema: "
                        + json.dumps(FORMATO_ANALISE)
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "curriculo": curriculo,
                            "vaga": vaga,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }

        requisicao = urllib.request.Request(
            servidor.ENDERECO_OLLAMA,
            data=json.dumps(corpo).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(
            requisicao,
            timeout=300,
        ) as resposta:
            envelope = json.load(resposta)

        if not isinstance(envelope, dict):
            raise ValueError(
                "O Ollama retornou um envelope inválido."
            )

        if envelope.get("done_reason") == "length":
            raise ValueError(
                "A resposta da IA foi cortada pelo limite de saída. "
                "Teste uma vaga mais curta."
            )

        resultado = json.loads(
            envelope.get("message", {}).get("content", "")
        )

        if not isinstance(resultado, dict):
            raise ValueError(
                "A IA não retornou um objeto JSON."
            )

        for nome in FORMATO_ANALISE["required"]:
            itens = resultado.get(nome)

            if not isinstance(itens, list):
                raise ValueError(
                    f"A IA não retornou o campo obrigatório "
                    f"'{nome}' como lista."
                )

            campos = FORMATO_ANALISE[
                "properties"
            ][nome]["items"]["required"]

            if any(
                not isinstance(item, dict)
                or any(
                    not isinstance(item.get(campo), str)
                    for campo in campos
                )
                for item in itens
            ):
                raise ValueError(
                    f"A IA retornou um item incompleto em '{nome}'."
                )

        # Mantém a validação de evidências e a revisão geral.
        analise = servidor.validar_analise(
            resultado,
            curriculo,
            vaga,
        )

        return jsonify(analise)

    except urllib.error.HTTPError as erro:
        detalhe = erro.read(2000).decode(
            "utf-8",
            errors="replace",
        )

        app.logger.warning(
            "Ollama HTTP %s: %s",
            erro.code,
            detalhe,
        )

        return jsonify(
            erro=(
                f"Ollama HTTP {erro.code}: "
                f"{detalhe or erro.reason}"
            )
        ), 502

    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
    ) as erro:
        app.logger.warning(
            "Falha na análise estruturada: %s",
            erro,
        )

        return jsonify(
            erro=(
                "Não foi possível concluir a análise. "
                + str(erro)
            )
        ), 502

    finally:
        revisar.TRAVA_ANALISE.release()


def localizar_tesseract():
    executavel = shutil.which("tesseract")

    if executavel:
        return executavel

    for pasta in (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ):
        if pasta:
            caminho = (
                Path(pasta)
                / "Tesseract-OCR"
                / "tesseract.exe"
            )

            if caminho.is_file():
                return str(caminho)

    raise ValueError(
        "Tesseract não instalado. "
        "Instale o OCR e reinicie o servidor."
    )


def transcrever_imagem(dados):
    executavel = localizar_tesseract()

    if not all(
        (
            PASTA_IDIOMAS / (idioma + ".traineddata")
        ).is_file()
        for idioma in ("por", "eng")
    ):
        raise ValueError(
            "Faltam por.traineddata e/ou eng.traineddata "
            "na pasta tessdata do projeto."
        )

    with Image.open(io.BytesIO(dados)) as imagem:
        if imagem.width * imagem.height > 20_000_000:
            raise ValueError(
                "Imagem muito grande. Divida em recortes menores."
            )

        rgba = imagem.convert("RGBA")
        fundo = Image.new("RGB", rgba.size, "white")

        fundo.paste(
            rgba,
            mask=rgba.getchannel("A"),
        )

        arquivo_png = io.BytesIO()
        fundo.save(arquivo_png, format="PNG")

    processo = subprocess.run(
        [
            executavel,
            "stdin",
            "stdout",
            "--tessdata-dir",
            str(PASTA_IDIOMAS),
            "-l",
            "por+eng",
            "--oem",
            "1",
            "--psm",
            "6",
        ],
        input=arquivo_png.getvalue(),
        capture_output=True,
        timeout=90,
        creationflags=(
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt"
            else 0
        ),
    )

    if processo.returncode:
        app.logger.warning(
            "Falha no OCR: %s",
            processo.stderr.decode(
                "utf-8",
                errors="replace",
            )[:1500],
        )

        raise ValueError(
            "O OCR não conseguiu ler essa imagem. "
            "Confira a instalação e tente um recorte legível."
        )

    texto = processo.stdout.decode(
        "utf-8",
        errors="replace",
    ).strip()

    if not texto:
        raise ValueError(
            "Nenhum texto encontrado. Envie um print mais nítido."
        )

    return texto


def analisar_fontes():
    imagens = request.files.getlist("imagens")
    texto_vaga = request.form.get("vaga", "").strip()

    observacoes = request.form.get(
        "observacoes_usuario", ""
    ).strip()

    if len(observacoes) > 4000:
        return jsonify(
            erro="Use até 4.000 caracteres nas observações."
        ), 400

    if (
        not imagens
        and len(texto_vaga) > servidor.MAX_TEXTO_VAGA
    ):
        return jsonify(
            erro="A descrição ultrapassa o limite de texto."
        ), 400

    if imagens:
        if len(imagens) > servidor.MAX_IMAGENS:
            return jsonify(
                erro="Envie no máximo 5 prints."
            ), 400

        arquivos = []

        for imagem in imagens:
            if (
                imagem.mimetype
                not in servidor.TIPOS_IMAGEM_PERMITIDOS
            ):
                return jsonify(
                    erro="Use prints PNG, JPEG ou WebP."
                ), 400

            dados = imagem.read()

            if not dados:
                return jsonify(
                    erro="Um dos prints está vazio."
                ), 400

            arquivos.append(dados)

        try:
            textos = []

            for indice, dados_imagem in enumerate(
                arquivos, 1
            ):
                app.logger.warning(
                    "Lendo print %s/%s com Tesseract OCR",
                    indice,
                    len(arquivos),
                )

                textos.append(
                    transcrever_imagem(dados_imagem)
                )

            texto = "\n\n".join(textos)

            if len(texto) > servidor.MAX_TEXTO_VAGA:
                raise ValueError(
                    "Transcrição muito longa. Divida o material."
                )

            texto_vaga = texto

        except (
            OSError,
            ValueError,
            subprocess.TimeoutExpired,
            Image.DecompressionBombError,
        ) as erro:
            app.logger.warning(
                "Falha na transcrição: %s",
                erro,
            )

            return jsonify(
                erro=(
                    "Não foi possível concluir todos os prints. "
                    + str(erro)
                )
            ), 502

    campos = request.form.to_dict(flat=True)
    campos["vaga"] = texto_vaga
    request.form = ImmutableMultiDict(campos)

    app.logger.warning(
        "Iniciando comparação textual com %s",
        revisar.MODELO_TEXTO,
    )

    resposta = app.make_response(
        analisar_texto_estruturado()
    )

    if resposta.status_code == 200 and resposta.is_json:
        dados = resposta.get_json()
        dados["observacao_usuario"] = observacoes

        dados["fonte_vaga"] = (
            "prints lidos por OCR"
            if imagens
            else "descrição oficial em texto"
        )

        dados["texto_vaga_lido"] = texto_vaga

        resposta.set_data(
            app.json.dumps(dados)
        )

    return resposta


app.view_functions["analisar"] = analisar_fontes


def estado():
    dados = ESTADO_ANTERIOR()

    dados.update(
        leitor_curriculo="PyMuPDF local",
        versao=VERSAO,
        observacoes_separadas=True,
        modelo_imagens="Tesseract OCR",
        ocr_instalado=bool(
            shutil.which("tesseract")
            or any(
                (
                    Path(pasta)
                    / "Tesseract-OCR"
                    / "tesseract.exe"
                ).is_file()
                for pasta in (
                    os.environ.get("ProgramFiles"),
                    os.environ.get("ProgramFiles(x86)"),
                )
                if pasta
            )
        ),
        idiomas_ocr_prontos=all(
            (
                PASTA_IDIOMAS / (idioma + ".traineddata")
            ).is_file()
            for idioma in ("por", "eng")
        ),
    )

    return dados


app.view_functions["estado_complemento"] = estado

SCRIPT = r"""
(() => {
  const comentario =
    document.querySelector('#observacoes-usuario');

  const botao =
    document.querySelector('#botao-analisar');

  if (botao) {
    botao.textContent = 'Analisar currículo e vaga';
  }

  const apiAnterior = requisitarApi;

  requisitarApi = async function(caminho, opcoes) {
    if (
      caminho === '/api/analisar' &&
      opcoes.body instanceof FormData
    ) {
      opcoes.body.set(
        'observacoes_usuario',
        comentario ? comentario.value.trim() : ''
      );

      opcoes.body.delete('vaga_imagem_confirmada');

      const mensagem =
        document.querySelector('#mensagem');

      if (mensagem) {
        mensagem.textContent =
          'Lendo a vaga e comparando com o currículo. Aguarde...';
      }
    }

    return apiAnterior(caminho, opcoes);
  };

  const mostrarAnterior = mostrarResultado;

  mostrarResultado = function(resultado, textoOriginal) {
    mostrarAnterior(resultado, textoOriginal);

    document.querySelector('#fontes-utilizadas')?.remove();

    const bloco = document.createElement('div');
    bloco.id = 'fontes-utilizadas';
    bloco.className = 'detalhes';

    const fonte = document.createElement('p');

    fonte.textContent =
      'Fonte dos requisitos: ' + resultado.fonte_vaga;

    bloco.appendChild(fonte);

    if (resultado.observacao_usuario) {
      const nota = document.createElement('p');

      nota.textContent =
        'Sua observação (não usada como requisito): ' +
        resultado.observacao_usuario;

      bloco.appendChild(nota);
    }

    if (resultado.texto_vaga_lido) {
      const detalhes = document.createElement('details');
      const titulo = document.createElement('summary');

      titulo.textContent =
        'Ver o texto da vaga usado na comparação';

      const texto = document.createElement('pre');
      texto.style.whiteSpace = 'pre-wrap';
      texto.textContent = resultado.texto_vaga_lido;

      detalhes.append(titulo, texto);
      bloco.appendChild(detalhes);
    }

    document.querySelector(
      '#tela-resultado'
    ).prepend(bloco);
  };
})();
"""


@app.get("/fontes.js")
def javascript_fontes():
    return Response(
        SCRIPT,
        mimetype="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.after_request
def incluir_fontes(resposta):
    if (
        request.path == "/"
        and resposta.status_code == 200
        and resposta.mimetype == "text/html"
    ):
        resposta.direct_passthrough = False
        html = resposta.get_data(as_text=True)

        html = re.sub(
            r'<script\b[^>]*src=["\'][^"\']*'
            r'pdf(?:\.min)?\.js[^"\']*["\'][^>]*>'
            r'\s*</script>',
            '',
            html,
            flags=re.IGNORECASE,
        )

        html = html.replace(
            'src="script.js"',
            'src="/script.js?v=13"',
        )

        html = html.replace(
            "</head>",
            "<style>"
            "#confirmacao-vaga{display:none!important}"
            "</style></head>",
        )

        html = re.sub(
            r"Prints são\s+transcritos para sua "
            r"confirmação antes da comparação\.",
            "Os prints são lidos por OCR e "
            "comparados automaticamente.",
            html,
        )

        if not re.search(
            r'id=[\"\']observacoes-usuario[\"\']',
            html,
        ):
            campo = """
<section class="detalhes" id="area-observacoes">
  <label for="observacoes-usuario">
    Suas observações ou preferências (opcional)
  </label>

  <textarea
    id="observacoes-usuario"
    name="observacoes_usuario"
    rows="4"
    maxlength="4000"
    placeholder="Ex.: gostaria de destacar meus projetos acadêmicos."
  ></textarea>

  <p>
    Este campo é separado da vaga.
    Suas observações ficam registradas no resultado;
    não são usadas para criar requisitos
    ou comprovar habilidades.
  </p>
</section>
"""

            html, quantidade = re.subn(
                r'(<textarea\b[^>]*\bid=["\']vaga["\']'
                r'[^>]*>.*?</textarea\s*>)',
                lambda achado: achado.group(0) + campo,
                html,
                count=1,
                flags=re.IGNORECASE | re.DOTALL,
            )

            if not quantidade:
                app.logger.warning(
                    "Campo #vaga não encontrado no index.html."
                )

        html = re.sub(
            r'(<label\b[^>]*\bfor=["\']vaga["\']'
            r'[^>]*>).*?(</label\s*>)',
            lambda achado: (
                achado.group(1)
                + "Descrição oficial em texto "
                "(para usar sem prints)"
                + achado.group(2)
            ),
            html,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

        resposta.set_data(
            html.replace(
                "</body>",
                '<script src="/fontes.js"></script>'
                "</body>",
            )
        )

        resposta.headers["Cache-Control"] = "no-store"

    return resposta


if __name__ == "__main__":
    print("Analisador: " + VERSAO)

    app.run(
        host="127.0.0.1",
        port=8000,
        debug=False,
    )