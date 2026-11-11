"""Execute: py personalizar.py. Requer revisar.py, iniciar.py e servidor.py."""

import io
import json

import fitz
from flask import Response, jsonify, request, send_file

import revisar
import iniciar

app = revisar.app
VERSAO = "personalizacao-5"


@app.post("/api/pdf-personalizado")
def pdf_personalizado():
    arquivo = request.files.get("pdf")

    if not arquivo:
        return jsonify(
            erro="Anexe o currículo original em PDF."
        ), 400

    try:
        alteracoes = json.loads(
            request.form.get("alteracoes", "[]")
        )

        inclusoes = json.loads(
            request.form.get("inclusoes", "[]")
        )

        if (
            not isinstance(alteracoes, list)
            or len(alteracoes) > 20
        ):
            raise ValueError(
                "Seleção de alterações inválida."
            )

        if (
            not isinstance(inclusoes, list)
            or len(inclusoes) > 20
        ):
            raise ValueError(
                "Selecione no máximo 20 inclusões."
            )

        textos = []

        for item in inclusoes:
            if (
                not isinstance(item, dict)
                or item.get("confirmado") is not True
            ):
                raise ValueError(
                    "Confirme as informações selecionadas."
                )

            texto = item.get("texto")

            if (
                not isinstance(texto, str)
                or not texto.strip()
                or len(texto) > 600
            ):
                raise ValueError(
                    "Cada inclusão deve conter "
                    "de 1 a 600 caracteres."
                )

            # Usa exatamente a informação escrita pelo candidato.
            textos.append(texto.strip())

        dados = arquivo.read()

        if not dados:
            raise ValueError("O PDF está vazio.")

        if not alteracoes and not textos:
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
                    "Use um PDF sem senha "
                    "e com até 30 páginas."
                )

            texto = "\n\n".join(
                bloco[4].strip()
                for pagina in pdf
                for bloco in pagina.get_text("blocks")
                if bloco[6] == 0
            )

        if not texto.strip():
            raise ValueError(
                "O PDF não contém texto selecionável. "
                "É necessário OCR."
            )

        novo = iniciar.aplicar_no_texto(
            texto,
            alteracoes,
        )

        if textos:
            novo += (
                "\n\nINFORMAÇÕES COMPLEMENTARES\n\n"
                + "\n\n".join(textos)
            )

        saida = iniciar.gerar_pdf_organizado(novo)

        return send_file(
            io.BytesIO(saida),
            mimetype="application/pdf",
            download_name="curriculo_personalizado.pdf",
        )

    except (
        ValueError,
        TypeError,
        RuntimeError,
        fitz.FileDataError,
    ) as erro:
        return jsonify(erro=str(erro)), 400


ESTADO_ANTERIOR = app.view_functions["estado_complemento"]


def estado():
    dados = ESTADO_ANTERIOR()

    dados.update(
        versao=VERSAO,
        inclusoes_candidato=True,
    )

    return dados


app.view_functions["estado_complemento"] = estado

SCRIPT = r"""
(() => {
  const anterior = mostrarResultado;

  mostrarResultado = function(resultado, textoOriginal) {
    anterior(resultado, textoOriginal);

    document.querySelector('#personalizacao-candidato')?.remove();

    const area = document.querySelector('#tela-resultado');

    if (!area) return;

    const arquivoAnalisado =
      document.querySelector('#arquivo').files[0];

    const secao = document.createElement('section');
    secao.id = 'personalizacao-candidato';

    const titulo = document.createElement('h3');
    titulo.textContent = 'Complementar meu currículo';

    const aviso = document.createElement('p');

    aviso.textContent =
      'Você pode incluir conhecimentos que possui e não aparecem ' +
      'no arquivo. Essas informações são declaradas por você, ' +
      'não verificadas pela IA. O PDF será gerado em um novo ' +
      'layout organizado.';

    secao.append(titulo, aviso);

    const registros = [];
    const mensagem = document.createElement('p');

    mensagem.setAttribute('role', 'status');

    const invalidar = () => {
      document.querySelector('#pdf-previa').hidden = true;
      document.querySelector('#pdf-download').hidden = true;

      mensagem.textContent =
        'Seleção modificada. Gere o PDF novamente.';
    };

    const requisitos = Array.isArray(resultado.requisitos)
      ? resultado.requisitos
      : [];

    requisitos.forEach(item => {
      const bloco = document.createElement('div');
      bloco.className = 'detalhes';

      const requisito = document.createElement('p');
      requisito.textContent = 'Requisito: ' + item.trecho_vaga;

      const origem = document.createElement('p');

      origem.textContent = item.status === 'encontrado'
        ? 'A análise localizou evidência no currículo. ' +
          'Você pode complementar os detalhes.'
        : 'A análise não confirmou integralmente este requisito. ' +
          'Você pode informar o que realmente possui.';

      const rotulo = document.createElement('label');

      const caixa = document.createElement('input');
      caixa.type = 'checkbox';

      rotulo.append(
        caixa,
        document.createTextNode(
          ' Possuo essa habilidade ou experiência e quero ' +
          'incluir a descrição abaixo.'
        )
      );

      const campo = document.createElement('textarea');

      campo.rows = 3;
      campo.maxLength = 600;
      campo.disabled = true;

      campo.placeholder =
        'Escreva o texto que entrará no currículo, ' +
        'com seu nível e/ou experiência real.';

      campo.setAttribute(
        'aria-label',
        'Informação complementar: ' + item.trecho_vaga
      );

      campo.style.width = '100%';

      const previa = document.createElement('p');

      const atualizar = () => {
        campo.disabled = !caixa.checked;

        previa.textContent =
          caixa.checked && campo.value.trim()
            ? 'Adicionar ao PDF: ' + campo.value.trim()
            : '';

        invalidar();
      };

      caixa.addEventListener('change', atualizar);
      campo.addEventListener('input', atualizar);

      bloco.append(
        requisito,
        origem,
        rotulo,
        campo,
        previa
      );

      secao.appendChild(bloco);
      registros.push({caixa, campo});
    });

    const botao = document.createElement('button');
    botao.type = 'button';

    botao.textContent =
      'Gerar PDF com minhas seleções e informações';

    secao.append(botao, mensagem);
    area.appendChild(secao);

    secao.addEventListener('input', invalidar);

    document.querySelectorAll('.selecionar-alteracao').forEach(
      caixa => caixa.addEventListener('change', invalidar)
    );

    botao.addEventListener('click', async () => {
      const arquivo =
        document.querySelector('#arquivo').files[0];

      if (!arquivo || arquivo !== arquivoAnalisado) {
        mensagem.textContent =
          'O arquivo mudou. Analise o currículo novamente.';
        return;
      }

      const marcados = registros.filter(
        r => r.caixa.checked
      );

      if (marcados.length > 20) {
        mensagem.textContent =
          'Selecione no máximo 20 inclusões.';
        return;
      }

      const vazio = marcados.find(
        r => !r.campo.value.trim()
      );

      if (vazio) {
        mensagem.textContent =
          'Descreva cada informação selecionada ' +
          'antes de gerar o PDF.';

        vazio.campo.focus();
        return;
      }

      const inclusoes = marcados.map(r => ({
        texto: r.campo.value.trim(),
        confirmado: true
      }));

      const alteracoes = Array.from(
        document.querySelectorAll(
          '.selecionar-alteracao:checked'
        )
      ).map(
        caixa => sugestoes[Number(caixa.value)]
      );

      const dados = new FormData();

      dados.append('pdf', arquivo);

      dados.append(
        'alteracoes',
        JSON.stringify(alteracoes)
      );

      dados.append(
        'inclusoes',
        JSON.stringify(inclusoes)
      );

      const controles = Array.from(
        area.querySelectorAll('button, input, textarea')
      );

      const estados = controles.map(c => c.disabled);

      controles.forEach(c => c.disabled = true);

      invalidar();

      mensagem.textContent =
        'Gerando PDF com as seleções atuais...';

      try {
        const resposta = await fetch(
          '/api/pdf-personalizado',
          {
            method: 'POST',
            body: dados
          }
        );

        if (!resposta.ok) {
          const erro = await resposta.json();

          throw new Error(
            erro.erro || 'Não foi possível gerar o PDF.'
          );
        }

        const blob = await resposta.blob();

        if (
          !secao.isConnected ||
          document.querySelector('#arquivo').files[0]
            !== arquivoAnalisado
        ) {
          throw new Error(
            'A análise ou o arquivo mudou. ' +
            'Gere o PDF a partir do resultado atual.'
          );
        }

        if (pdfUrl) {
          URL.revokeObjectURL(pdfUrl);
        }

        pdfUrl = URL.createObjectURL(blob);

        const previa =
          document.querySelector('#pdf-previa');

        const download =
          document.querySelector('#pdf-download');

        previa.src = pdfUrl;
        previa.hidden = false;

        download.href = pdfUrl;

        download.download =
          inclusoes.length || alteracoes.length
            ? 'curriculo_personalizado.pdf'
            : 'curriculo_original.pdf';

        download.hidden = false;

        mensagem.textContent =
          inclusoes.length || alteracoes.length
            ? 'PDF pronto em novo layout. Inclui somente as ' +
              'alterações e informações selecionadas. ' +
              'Confira a prévia antes de baixar.'
            : 'Nenhuma mudança selecionada: ' +
              'PDF original disponível.';

        previa.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });

      } catch (erro) {
        mensagem.textContent = erro.message;

      } finally {
        controles.forEach(
          (c, i) => c.disabled = estados[i]
        );
      }
    });
  };
})();
"""


@app.get("/personalizacao.js")
def javascript_personalizacao():
    return Response(
        SCRIPT,
        mimetype="application/javascript",
    )


@app.after_request
def incluir_personalizacao(resposta):
    if (
        request.path == "/"
        and resposta.status_code == 200
        and resposta.mimetype == "text/html"
    ):
        resposta.direct_passthrough = False

        html = resposta.get_data(as_text=True)

        resposta.set_data(
            html.replace(
                "</body>",
                '<script src="/personalizacao.js"></script>'
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