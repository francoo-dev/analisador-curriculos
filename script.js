// Elementos da tela de envio.
const formulario = document.querySelector("#formulario");
const campoArquivo = document.querySelector("#arquivo");
const campoImagemVaga = document.querySelector("#imagem-vaga");
const campoVaga = document.querySelector("#vaga");
const confirmacaoVaga = document.querySelector("#confirmacao-vaga");
const textoTranscrito = document.querySelector("#texto-transcrito");
const botaoConfirmarVaga = document.querySelector("#confirmar-vaga");
const listaPrints = document.querySelector("#lista-prints");
const mensagem = document.querySelector("#mensagem");
const botaoAnalisar = document.querySelector("#botao-analisar");

// Telas.
const telaEnvio = document.querySelector("#tela-envio");
const telaResultado = document.querySelector("#tela-resultado");

// Elementos da tela de resultados.
const curriculoOriginal = document.querySelector("#curriculo-original");
const curriculoAdaptado = document.querySelector("#curriculo-adaptado");
const areaAlteracoes = document.querySelector("#alteracoes");
const botaoVoltar = document.querySelector("#botao-voltar");

// Elementos da prévia do PDF.
const gerarPdf = document.querySelector("#gerar-pdf");
const pdfMensagem = document.querySelector("#pdf-mensagem");
const pdfPrevia = document.querySelector("#pdf-previa");
const pdfDownload = document.querySelector("#pdf-download");

// Guarda o endereço temporário do PDF gerado.
let pdfUrl = null;

// Guarda as sugestões da IA.
let sugestoes = [];

// Tipos de imagem aceitos.
const tiposImagemPermitidos = [
  "image/png",
  "image/jpeg",
  "image/webp"
];

// Limite de prints por análise.
const limitePrints = 5;

// Guarda os prints enquanto a página estiver aberta.
const imagensVaga = [];

// Guarda os prints selecionados para remoção.
const printsSelecionados = new Set();

function verificarOrigemLocal() {
  const hostLocal = ["localhost", "127.0.0.1"].includes(
    window.location.hostname
  );
  const portaLocal = window.location.port === "8000";

  if (
    window.location.protocol !== "http:"
    || !hostLocal
    || !portaLocal
  ) {
    throw new Error(
      "Esta página não está aberta pelo servidor local. " +
      "No terminal da pasta do projeto, execute `py servidor.py` e " +
      "acesse http://localhost:8000."
    );
  }
}

async function requisitarApi(caminho, opcoes) {
  verificarOrigemLocal();

  try {
    return await fetch(caminho, opcoes);
  } catch (erro) {
    throw new Error(
      "Não foi possível conectar ao servidor Flask em " +
      "http://localhost:8000. No terminal da pasta do projeto, " +
      "execute `py servidor.py` e tente novamente."
    );
  }
}

async function erroRespostaApi(resposta, operacao) {
  const tipoConteudo = resposta.headers.get("content-type") || "";

  if (tipoConteudo.toLowerCase().includes("application/json")) {
    try {
      const resultado = await resposta.json();
      if (resultado && typeof resultado.erro === "string") {
        return resultado.erro;
      }
    } catch (erro) {
      return (
        `O servidor respondeu HTTP ${resposta.status}, mas enviou ` +
        "JSON inválido. Confira o terminal do Flask."
      );
    }
  }

  if (resposta.status === 404) {
    return (
      `O servidor respondeu HTTP 404 durante ${operacao}; a rota não ` +
      "foi encontrada. Confirme se abriu http://localhost:8000 e se " +
      "está executando o servidor.py deste projeto."
    );
  }

  if (resposta.status === 405) {
    return (
      `O servidor respondeu HTTP 405 durante ${operacao}; o método ` +
      "da requisição não é aceito pela rota."
    );
  }

  return (
    `O servidor respondeu HTTP ${resposta.status} durante ${operacao}, ` +
    `com conteúdo ${tipoConteudo || "sem tipo informado"} em vez do JSON esperado. ` +
    "Confira se está usando o servidor.py deste projeto."
  );
}

async function lerRespostaJson(resposta, operacao) {
  const tipoConteudo = resposta.headers.get("content-type") || "";

  if (!tipoConteudo.toLowerCase().includes("application/json")) {
    throw new Error(
      await erroRespostaApi(resposta, operacao)
    );
  }

  let resultado;
  try {
    resultado = await resposta.json();
  } catch (erro) {
    throw new Error(
      `O servidor respondeu HTTP ${resposta.status} com JSON inválido ` +
      `durante ${operacao}. Confira o terminal do Flask.`
    );
  }

  if (!resultado || typeof resultado !== "object" || Array.isArray(resultado)) {
    throw new Error(
      `O servidor respondeu HTTP ${resposta.status} com um formato JSON ` +
      `inesperado durante ${operacao}.`
    );
  }

  if (!resposta.ok) {
    throw new Error(
      typeof resultado.erro === "string"
        ? resultado.erro
        : await erroRespostaApi(resposta, operacao)
    );
  }

  return resultado;
}

// Configura o arquivo auxiliar da biblioteca de PDF.
if (typeof pdfjsLib !== "undefined") {
  pdfjsLib.GlobalWorkerOptions.workerSrc =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
}

// Cria o bloco que contém todos os prints.
const blocoPrints = document.createElement("div");
blocoPrints.className = "detalhes";
blocoPrints.hidden = true;

const tituloPrints = document.createElement("h3");
tituloPrints.textContent = "Prints adicionados";

const instrucaoPrints = document.createElement("p");
instrucaoPrints.className = "legenda";
instrucaoPrints.textContent =
  "Clique nos prints que deseja remover e depois use o botão abaixo.";

const galeriaPrints = document.createElement("div");
galeriaPrints.style.display = "flex";
galeriaPrints.style.flexWrap = "wrap";
galeriaPrints.style.gap = "12px";

const botaoRemoverSelecionados = document.createElement("button");
botaoRemoverSelecionados.type = "button";
botaoRemoverSelecionados.className = "secundario";
botaoRemoverSelecionados.textContent = "Remover prints selecionados";
botaoRemoverSelecionados.disabled = true;

blocoPrints.appendChild(tituloPrints);
blocoPrints.appendChild(instrucaoPrints);
blocoPrints.appendChild(galeriaPrints);
blocoPrints.appendChild(botaoRemoverSelecionados);

listaPrints.appendChild(blocoPrints);

// Atualiza a aparência e a identificação dos prints.
function atualizarGaleria() {
  imagensVaga.forEach(function (registro, indice) {
    const numero = indice + 1;
    const selecionado = printsSelecionados.has(registro);

    registro.imagem.alt = `Print ${numero} da vaga`;

    registro.botao.setAttribute(
      "aria-label",
      `Selecionar print ${numero} para remoção`
    );

    registro.botao.setAttribute(
      "aria-pressed",
      String(selecionado)
    );

    if (selecionado) {
      registro.botao.style.borderColor = "#2563eb";
      registro.botao.style.background = "#dbeafe";
    } else {
      registro.botao.style.borderColor = "#cbd5e1";
      registro.botao.style.background = "#ffffff";
    }
  });

  blocoPrints.hidden = imagensVaga.length === 0;
  botaoRemoverSelecionados.disabled = printsSelecionados.size === 0;
}

// Adiciona um print à galeria.
function adicionarPrint(arquivo) {
  if (!tiposImagemPermitidos.includes(arquivo.type)) {
    return false;
  }

  if (imagensVaga.length >= limitePrints) {
    return false;
  }

  const endereco = URL.createObjectURL(arquivo);

  const botao = document.createElement("button");
  botao.type = "button";

  botao.style.display = "flex";
  botao.style.alignItems = "center";
  botao.style.justifyContent = "center";
  botao.style.width = "180px";
  botao.style.maxWidth = "100%";
  botao.style.margin = "0";
  botao.style.padding = "8px";
  botao.style.border = "2px solid #cbd5e1";
  botao.style.borderRadius = "8px";
  botao.style.cursor = "pointer";

  const imagem = document.createElement("img");
  imagem.src = endereco;
  imagem.style.width = "100%";
  imagem.style.height = "120px";
  imagem.style.objectFit = "contain";

  botao.appendChild(imagem);

  const registro = {
    arquivo: arquivo,
    endereco: endereco,
    botao: botao,
    imagem: imagem
  };

  botao.addEventListener("click", function () {
    if (printsSelecionados.has(registro)) {
      printsSelecionados.delete(registro);
    } else {
      printsSelecionados.add(registro);
    }

    atualizarGaleria();

    const quantidade = printsSelecionados.size;

    if (quantidade === 0) {
      mensagem.textContent = "Nenhum print selecionado.";
    } else {
      mensagem.textContent =
        `${quantidade} print(s) selecionado(s) para remoção.`;
    }
  });

  imagensVaga.push(registro);
  galeriaPrints.appendChild(botao);

  atualizarGaleria();

  return true;
}

// Remove os prints selecionados.
botaoRemoverSelecionados.addEventListener("click", function () {
  const quantidadeRemovida = printsSelecionados.size;

  for (const registro of printsSelecionados) {
    const indice = imagensVaga.indexOf(registro);

    if (indice !== -1) {
      imagensVaga.splice(indice, 1);
    }

    URL.revokeObjectURL(registro.endereco);
    registro.botao.remove();
  }

  printsSelecionados.clear();
  atualizarGaleria();

  mensagem.textContent =
    `${quantidadeRemovida} print(s) removido(s).`;
});

// Recebe imagens coladas com Ctrl + V.
document.addEventListener("paste", function (evento) {
  if (telaEnvio.hidden || !evento.clipboardData) {
    return;
  }

  const itens = evento.clipboardData.items;

  let adicionados = 0;
  let naoAdicionados = 0;

  for (const item of itens) {
    if (!item.type.startsWith("image/")) {
      continue;
    }

    const arquivo = item.getAsFile();

    if (arquivo && adicionarPrint(arquivo)) {
      adicionados++;
    } else {
      naoAdicionados++;
    }
  }

  if (adicionados > 0 || naoAdicionados > 0) {
    evento.preventDefault();

    if (naoAdicionados > 0) {
      mensagem.textContent =
        `${adicionados} print(s) adicionado(s). ` +
        `Use PNG, JPEG ou WebP e adicione no máximo ${limitePrints} prints.`;
    } else {
      mensagem.textContent =
        `${adicionados} print(s) adicionado(s) com sucesso!`;
    }
  }
});

// Adiciona imagens escolhidas no computador.
campoImagemVaga.addEventListener("change", function () {
  const arquivos = Array.from(campoImagemVaga.files);

  let adicionados = 0;
  let naoAdicionados = 0;

  for (const arquivo of arquivos) {
    if (adicionarPrint(arquivo)) {
      adicionados++;
    } else {
      naoAdicionados++;
    }
  }

  // Permite selecionar o mesmo arquivo novamente.
  campoImagemVaga.value = "";

  if (naoAdicionados > 0) {
    mensagem.textContent =
      `${adicionados} print(s) adicionado(s). ` +
      `Use PNG, JPEG ou WebP e adicione no máximo ${limitePrints} prints.`;
  } else if (adicionados > 0) {
    mensagem.textContent =
      `${adicionados} print(s) adicionado(s) com sucesso!`;
  }
});

// Lê o texto de todas as páginas do PDF.
async function lerTextoPdf(arquivo) {
  const dados = await arquivo.arrayBuffer();

  const pdf = await pdfjsLib.getDocument({
    data: dados
  }).promise;

  const paginas = [];

  for (let numero = 1; numero <= pdf.numPages; numero++) {
    const pagina = await pdf.getPage(numero);
    const conteudo = await pagina.getTextContent();

    let textoPagina = "";

    for (const item of conteudo.items) {
      textoPagina += item.str;
      textoPagina += item.hasEOL ? "\n" : " ";
    }

    paginas.push(textoPagina.trim());
  }

  return paginas.join("\n\n").trim();
}

// Adiciona uma lista à tela de resultados.
function adicionarListaResultado(titulo, itens) {
  const subtitulo = document.createElement("h4");
  subtitulo.textContent = titulo;

  areaAlteracoes.appendChild(subtitulo);

  if (!Array.isArray(itens) || itens.length === 0) {
    const paragrafo = document.createElement("p");
    paragrafo.textContent = "Nenhum item informado.";

    areaAlteracoes.appendChild(paragrafo);
    return;
  }

  const lista = document.createElement("ul");

  itens.forEach(function (item) {
    const elemento = document.createElement("li");
    elemento.textContent = String(item);

    lista.appendChild(elemento);
  });

  areaAlteracoes.appendChild(lista);
}

// Mostra os dados devolvidos pela IA.
function mostrarResultado(resultado, textoOriginal) {
  curriculoOriginal.textContent = textoOriginal;

  sugestoes = Array.isArray(resultado.alteracoes)
    ? resultado.alteracoes.filter(function (alteracao) {
        return (
          alteracao &&
          typeof alteracao.original === "string" &&
          typeof alteracao.sugerido === "string" &&
          alteracao.original.trim() &&
          alteracao.sugerido.trim() &&
          alteracao.original !== alteracao.sugerido
        );
      })
    : [];

  if (sugestoes.length > 0) {
    curriculoAdaptado.textContent =
      "Selecione abaixo as sugestões que deseja aplicar. " +
      "O PDF será alterado apenas após gerar a prévia.";
  } else {
    curriculoAdaptado.textContent =
      "Nenhuma sugestão técnica foi validada. " +
      "Você pode visualizar e baixar o PDF original.";
  }

  pdfPrevia.hidden = true;
  pdfDownload.hidden = true;
  pdfMensagem.textContent = "";

  if (pdfUrl) {
    URL.revokeObjectURL(pdfUrl);
    pdfUrl = null;
  }

  areaAlteracoes.replaceChildren();

  const tituloRequisitos = document.createElement("h4");
  tituloRequisitos.textContent = "Requisitos e evidências";
  areaAlteracoes.appendChild(tituloRequisitos);

  const requisitos = Array.isArray(resultado.requisitos)
    ? resultado.requisitos
    : [];

  if (requisitos.length === 0) {
    const paragrafo = document.createElement("p");
    paragrafo.textContent =
      "Nenhum requisito foi validado por citação literal da vaga.";
    areaAlteracoes.appendChild(paragrafo);
  }

  requisitos.forEach(function (requisito) {
    const bloco = document.createElement("div");
    bloco.className = "detalhes";

    const trechoVaga = document.createElement("p");
    trechoVaga.textContent =
      `Trecho exato da vaga: ${requisito.trecho_vaga}`;
    bloco.appendChild(trechoVaga);

    if (requisito.status === "encontrado") {
      const evidencia = document.createElement("p");
      evidencia.textContent =
        `Trecho exato do currículo: ${requisito.evidencia_curriculo}`;

      const explicacao = document.createElement("p");
      explicacao.textContent =
        `Relação: ${requisito.explicacao}`;

      bloco.appendChild(evidencia);
      bloco.appendChild(explicacao);
    } else {
      const naoIdentificado = document.createElement("p");
      naoIdentificado.textContent =
        "não identificado no currículo. Isso não significa que você " +
        "não possua a habilidade; se possuir, confirme e descreva a " +
        "experiência antes de considerar incluí-la.";
      bloco.appendChild(naoIdentificado);
    }

    areaAlteracoes.appendChild(bloco);
  });

  const tituloMudancas = document.createElement("h4");
  tituloMudancas.textContent = "Alterações sugeridas";
  areaAlteracoes.appendChild(tituloMudancas);

  if (sugestoes.length > 0) {
    sugestoes.forEach(function (alteracao, indice) {
      const bloco = document.createElement("div");
      bloco.className = "detalhes";

      const original = document.createElement("p");
      original.textContent =
        `Original: ${alteracao.original || "Não informado."}`;

      const sugerido = document.createElement("p");
      sugerido.textContent =
        `Sugestão: ${alteracao.sugerido || "Não informada."}`;

      const motivo = document.createElement("p");
      motivo.textContent =
        `Motivo: ${alteracao.motivo || "Não informado."}`;

      const requisito = document.createElement("p");
      requisito.textContent =
        `Requisito da vaga: ${alteracao.trecho_vaga}`;

      const evidencia = document.createElement("p");
      evidencia.textContent =
        `Evidência no currículo: ${alteracao.evidencia_curriculo}`;

      const selecionar = document.createElement("input");
      selecionar.type = "checkbox";
      selecionar.value = String(indice);
      selecionar.className = "selecionar-alteracao";

      selecionar.addEventListener("change", function () {
        pdfPrevia.hidden = true;
        pdfDownload.hidden = true;

        pdfMensagem.textContent =
          "Seleção alterada. Gere uma nova prévia.";
      });

      const rotulo = document.createElement("label");

      rotulo.appendChild(selecionar);

      rotulo.appendChild(
        document.createTextNode(" Aplicar esta sugestão")
      );

      bloco.appendChild(rotulo);
      bloco.appendChild(original);
      bloco.appendChild(sugerido);
      bloco.appendChild(motivo);
      bloco.appendChild(requisito);
      bloco.appendChild(evidencia);

      areaAlteracoes.appendChild(bloco);
    });
  } else {
    const paragrafo = document.createElement("p");

    paragrafo.textContent =
      "Nenhuma sugestão técnica foi disponibilizada.";

    areaAlteracoes.appendChild(paragrafo);
  }

  adicionarListaResultado(
    "Avisos para conferir",
    resultado.observacoes
  );
}

botaoConfirmarVaga.addEventListener("click", function () {
  const descricaoConfirmada = textoTranscrito.value.trim();

  if (!descricaoConfirmada) {
    mensagem.textContent =
      "Cole ou corrija a descrição da vaga antes de confirmar.";
    textoTranscrito.focus();
    return;
  }

  campoVaga.value = descricaoConfirmada;
  confirmacaoVaga.hidden = true;
  window.setTimeout(function () {
    formulario.requestSubmit();
  }, 0);
});

// Envia o currículo e a vaga para o servidor.
formulario.addEventListener("submit", async function (evento) {
  evento.preventDefault();

  try {
    verificarOrigemLocal();
  } catch (erro) {
    mensagem.textContent = erro.message;
    return;
  }

  const arquivo = campoArquivo.files[0];
  const descricaoVaga = campoVaga.value.trim();

  if (!arquivo) {
    mensagem.textContent = "Anexe seu currículo em PDF.";
    return;
  }

  if (imagensVaga.length === 0 && !descricaoVaga) {
    mensagem.textContent =
      "Cole ou selecione um print da vaga, ou informe a descrição em texto.";

    return;
  }

  if (
    arquivo.type !== "application/pdf" &&
    !arquivo.name.toLowerCase().endsWith(".pdf")
  ) {
    mensagem.textContent =
      "Escolha um arquivo PDF para o currículo.";

    return;
  }

  if (typeof pdfjsLib === "undefined") {
    mensagem.textContent =
      "Não foi possível carregar o leitor de PDF. Verifique sua conexão.";

    return;
  }

  botaoAnalisar.disabled = true;
  mensagem.textContent = "Lendo o currículo...";

  try {
    const textoCurriculo = await lerTextoPdf(arquivo);

    if (!textoCurriculo) {
      mensagem.textContent =
        "Não encontramos texto no PDF. Ele pode ser uma imagem digitalizada.";

      return;
    }

    const dados = new FormData();

    dados.append("curriculo", textoCurriculo);
    dados.append("vaga", descricaoVaga);

    imagensVaga.forEach(function (registro, indice) {
      const nomeArquivo =
        registro.arquivo.name || `print-${indice + 1}.png`;

      dados.append(
        "imagens",
        registro.arquivo,
        nomeArquivo
      );
    });

    mensagem.textContent =
      "Analisando com a IA local. Isso pode levar alguns minutos...";

    const resposta = await requisitarApi("/api/analisar", {
      method: "POST",
      body: dados
    });

    const resultado = await lerRespostaJson(
      resposta,
      "a análise do currículo"
    );

    if (resultado.aguardando_confirmacao) {
      textoTranscrito.value =
        typeof resultado.transcricao_vaga === "string"
          ? resultado.transcricao_vaga
          : "";
      confirmacaoVaga.hidden = false;
      mensagem.textContent =
        textoTranscrito.value
          ? "Confira e corrija a transcrição. A vaga ainda não foi comparada."
          : "Não foi possível extrair texto. Digite a descrição da vaga para continuar.";
      textoTranscrito.focus();
      return;
    }

    confirmacaoVaga.hidden = true;
    mostrarResultado(resultado, textoCurriculo);

    mensagem.textContent = "";
    telaEnvio.hidden = true;
    telaResultado.hidden = false;

    window.scrollTo(0, 0);
  } catch (erro) {
    console.error("Erro ao preparar a análise:", erro);

    mensagem.textContent =
      erro.message ||
      "Não foi possível fazer a análise. Confira se o servidor está aberto.";
  } finally {
    botaoAnalisar.disabled = false;
  }
});

// Volta para a tela de envio.
botaoVoltar.addEventListener("click", function () {
  telaResultado.hidden = true;
  telaEnvio.hidden = false;

  window.scrollTo(0, 0);
});

// Gera uma cópia do PDF com as sugestões selecionadas.
gerarPdf.addEventListener("click", async function () {
  try {
    verificarOrigemLocal();
  } catch (erro) {
    pdfMensagem.textContent = erro.message;
    return;
  }

  const arquivo = campoArquivo.files[0];

  if (!arquivo) {
    pdfMensagem.textContent =
      "Selecione novamente o PDF original.";

    return;
  }

  const caixasSelecionadas = document.querySelectorAll(
    ".selecionar-alteracao:checked"
  );

  const escolhas = Array.from(
    caixasSelecionadas,
    function (caixa) {
      return sugestoes[Number(caixa.value)];
    }
  );

  const dados = new FormData();

  dados.append("pdf", arquivo);
  dados.append("alteracoes", JSON.stringify(escolhas));

  gerarPdf.disabled = true;
  pdfMensagem.textContent = "Preparando PDF...";
  pdfPrevia.hidden = true;
  pdfDownload.hidden = true;

  try {
    const resposta = await requisitarApi("/api/pdf", {
      method: "POST",
      body: dados
    });

    if (!resposta.ok) {
      throw new Error(await erroRespostaApi(resposta, "a geração do PDF"));
    }

    const blob = await resposta.blob();

    if (pdfUrl) {
      URL.revokeObjectURL(pdfUrl);
    }

    pdfUrl = URL.createObjectURL(blob);

    pdfPrevia.src = pdfUrl;
    pdfDownload.href = pdfUrl;

    pdfPrevia.hidden = false;
    pdfDownload.hidden = false;

    if (escolhas.length > 0) {
      pdfMensagem.textContent =
        "Confira a prévia antes de baixar. " +
        "Se algo estiver incorreto, não use o arquivo.";
    } else {
      pdfMensagem.textContent =
        "Nenhuma alteração selecionada: este é o PDF original.";
    }
  } catch (erro) {
    pdfMensagem.textContent =
      erro.message || "Erro ao gerar o PDF.";
  } finally {
    gerarPdf.disabled = false;
  }
});