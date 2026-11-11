import io
import json
import unittest
from unittest.mock import patch

import fitz

import servidor


def resposta_ollama(resultado):
    conteudo = json.dumps(resultado, ensure_ascii=False)
    resposta = json.dumps({
        "message": {"content": conteudo}
    }, ensure_ascii=False)
    return io.BytesIO(resposta.encode("utf-8"))


def criar_pdf(linhas):
    documento = fitz.open()
    pagina = documento.new_page()
    for indice, linha in enumerate(linhas):
        pagina.insert_text((72, 72 + indice * 24), linha, fontsize=12)
    dados = documento.tobytes()
    documento.close()
    return dados


def texto_pdf(dados):
    with fitz.open(stream=dados, filetype="pdf") as documento:
        return " ".join(
            pagina.get_text("text") for pagina in documento
        ).strip()


class AnaliseTestes(unittest.TestCase):
    def setUp(self):
        servidor.app.testing = True
        self.cliente = servidor.app.test_client()

    def analisar(self, resultado, curriculo, vaga):
        with patch.object(
            servidor.urllib.request,
            "urlopen",
            return_value=resposta_ollama(resultado),
        ):
            return self.cliente.post(
                "/api/analisar",
                data={"curriculo": curriculo, "vaga": vaga},
            )

    def test_sql_nao_e_requisito_e_sugestao_gramatical_e_descartada(self):
        curriculo = "Tenho experiência com C, Python e SQL."
        vaga = "A vaga exige C e Python."
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "C"},
                {"trecho_vaga": "Python"},
                {"trecho_vaga": "SQL"},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "C",
                    "evidencia_curriculo": "C",
                    "explicacao": "A mesma linguagem aparece nos dois trechos.",
                },
                {
                    "trecho_vaga": "Python",
                    "evidencia_curriculo": "Python",
                    "explicacao": "A mesma linguagem aparece nos dois trechos.",
                },
            ],
            "alteracoes": [
                {
                    "original": "Tenho experiência com C",
                    "sugerido": "Possuo experiência com C",
                    "trecho_vaga": "C",
                    "evidencia_curriculo": "C",
                    "motivo": "Apenas uma troca de estilo.",
                }
            ],
        }, curriculo, vaga)

        self.assertEqual(resposta.status_code, 200)
        resultado = resposta.get_json()
        self.assertEqual(
            [item["trecho_vaga"] for item in resultado["requisitos"]],
            ["C", "Python"],
        )
        self.assertEqual(resultado["alteracoes"], [])

    def test_projetos_de_programacao_nao_comprovam_suporte(self):
        vaga = (
            "Manutenção de computadores, instalação e atualização de "
            "softwares e suporte a usuários."
        )
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "Manutenção de computadores"},
                {"trecho_vaga": "instalação e atualização de softwares"},
                {"trecho_vaga": "suporte a usuários"},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "suporte a usuários",
                    "evidencia_curriculo": "Projetos em C e Python",
                    "explicacao": "A resposta inventada pela IA.",
                }
            ],
            "alteracoes": [],
        }, "Projetos em C e Python.", vaga)

        self.assertEqual(resposta.status_code, 200)
        requisitos = resposta.get_json()["requisitos"]
        self.assertEqual(len(requisitos), 3)
        self.assertTrue(all(
            requisito["status"] == "nao_identificado"
            for requisito in requisitos
        ))

    def test_sugestao_tecnica_com_evidencia_citada_e_preservada(self):
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "Python"},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "Python",
                    "evidencia_curriculo": "Python",
                    "explicacao": "A linguagem citada está nos dois trechos.",
                },
            ],
            "alteracoes": [
                {
                    "original": "Projetos",
                    "sugerido": "Projetos em Python",
                    "trecho_vaga": "Python",
                    "evidencia_curriculo": "Python",
                    "motivo": "Destaca uma linguagem exigida e já citada.",
                },
            ],
        }, "Projetos em C e Python.", "A vaga pede Python.")

        self.assertEqual(resposta.status_code, 200)
        alteracoes = resposta.get_json()["alteracoes"]
        self.assertEqual(len(alteracoes), 1)
        self.assertEqual(alteracoes[0]["sugerido"], "Projetos em Python")

    def test_sugestao_rejeitada_e_informada_sem_aplicar_ao_pdf(self):
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "Python"},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "Python",
                    "evidencia_curriculo": "Projetos em Python.",
                    "explicacao": "Python aparece na descrição do projeto.",
                },
            ],
            "alteracoes": [
                {
                    "original": "Tenho experiência",
                    "sugerido": "Possuo experiência",
                    "trecho_vaga": "Python",
                    "evidencia_curriculo": "Projetos em Python.",
                    "motivo": "Alteração apenas de estilo.",
                },
            ],
        }, "Tenho experiência. Projetos em Python.", "A vaga exige Python.")

        self.assertEqual(resposta.status_code, 200)
        resultado = resposta.get_json()
        self.assertEqual(resultado["alteracoes"], [])
        self.assertTrue(any(
            "nenhuma passou pelas validações" in aviso
            for aviso in resultado["observacoes"]
        ))

    def test_sugestao_sem_mudanca_real_e_descartada(self):
        trecho = "Projetos em Python."
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "Python"},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "Python",
                    "evidencia_curriculo": trecho,
                    "explicacao": "Python aparece no projeto.",
                },
            ],
            "alteracoes": [
                {
                    "original": trecho,
                    "sugerido": trecho,
                    "trecho_vaga": "Python",
                    "evidencia_curriculo": trecho,
                    "motivo": "Reforça a competência.",
                },
            ],
        }, trecho, "A vaga exige Python.")

        self.assertEqual(resposta.status_code, 200)
        resultado = resposta.get_json()
        self.assertEqual(resultado["alteracoes"], [])
        self.assertTrue(any(
            "nenhuma passou pelas validações" in aviso
            for aviso in resultado["observacoes"]
        ))

    def test_vaga_c_evidencia_citam_a_mesma_habilidade_com_trechos_diferentes(self):
        vaga = "Conhecimentos básicos em linguagem C."
        curriculo = (
            "Linguagens: Python, C e SQL (básico); C++ (em aprendizado).\n"
            "IMORTAL 1 - Onboard System | C."
        )
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "Conhecimentos básicos em linguagem C."},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "linguagem C",
                    "evidencia_curriculo": (
                        "Linguagens: Python, C e SQL (básico); "
                        "C++ (em aprendizado)."
                    ),
                    "explicacao": "A linguagem C aparece na lista de linguagens.",
                },
                {
                    "trecho_vaga": "C",
                    "evidencia_curriculo": "IMORTAL 1 - Onboard System | C",
                    "explicacao": "O projeto identifica C como linguagem.",
                },
            ],
            "alteracoes": [],
        }, curriculo, vaga)

        self.assertEqual(resposta.status_code, 200)
        requisito = resposta.get_json()["requisitos"][0]
        self.assertEqual(requisito["status"], "encontrado")
        self.assertEqual(
            requisito["trecho_vaga"],
            "Conhecimentos básicos em linguagem C.",
        )
        self.assertTrue(requisito["evidencia_curriculo"])
        self.assertIn("Confirme seu nível", requisito["explicacao"])

    def test_cplusplus_nao_comprova_c(self):
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "C"},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "C",
                    "evidencia_curriculo": "C++",
                    "explicacao": "A IA confundiu as linguagens.",
                },
            ],
            "alteracoes": [],
        }, "Projeto desenvolvido em C++.", "A vaga exige C.")

        self.assertEqual(resposta.status_code, 200)
        requisito = resposta.get_json()["requisitos"][0]
        self.assertEqual(requisito["status"], "nao_identificado")
        self.assertEqual(requisito["evidencia_curriculo"], "")

    def test_identifica_c_mesmo_quando_ia_nao_relata_correspondencia(self):
        curriculo = (
            "Linguagens: Python, C e SQL (básico); C++ (em aprendizado).\n"
            "IMORTAL 1 - Onboard System | C."
        )
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "Conhecimentos básicos em linguagem C."},
            ],
            "pontos_encontrados": [],
            "alteracoes": [],
        }, curriculo, "Conhecimentos básicos em linguagem C.")

        self.assertEqual(resposta.status_code, 200)
        requisito = resposta.get_json()["requisitos"][0]
        self.assertEqual(requisito["status"], "encontrado")
        self.assertIn("Linguagens:", requisito["evidencia_curriculo"])
        self.assertIn("Confirme seu nível", requisito["explicacao"])

    def test_mesma_evidencia_comprova_c_e_python_independentemente(self):
        curriculo = "Linguagens: Python, C e SQL (básico); C++ (em aprendizado)."
        vaga = (
            "Conhecimentos básicos em linguagem C. "
            "Conhecimentos básicos em Python."
        )
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "Conhecimentos básicos em linguagem C."},
                {"trecho_vaga": "Conhecimentos básicos em Python."},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "Conhecimentos básicos em linguagem C.",
                    "evidencia_curriculo": curriculo,
                    "explicacao": "A lista contém a linguagem C.",
                },
            ],
            "alteracoes": [],
        }, curriculo, vaga)

        self.assertEqual(resposta.status_code, 200)
        requisitos = resposta.get_json()["requisitos"]
        self.assertEqual(
            [item["status"] for item in requisitos],
            ["encontrado", "encontrado"],
        )
        self.assertEqual(
            requisitos[0]["evidencia_curriculo"],
            requisitos[1]["evidencia_curriculo"],
        )
        self.assertTrue(all(
            "Confirme seu nível" in item["explicacao"]
            for item in requisitos
        ))

    def test_palavras_que_contem_c_nao_comprovam_linguagem_c(self):
        resposta = self.analisar({
            "requisitos_vaga": [{"trecho_vaga": "C"}],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "C",
                    "evidencia_curriculo": "Ciência da Computação e Excel.",
                    "explicacao": "Correspondência incorreta.",
                },
            ],
            "alteracoes": [],
        }, "Ciência da Computação e Excel.", "A vaga exige C.")

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.get_json()["requisitos"][0]["status"],
            "nao_identificado",
        )

    def test_sql_nao_vira_requisito_de_c_e_python(self):
        resposta = self.analisar({
            "requisitos_vaga": [
                {"trecho_vaga": "C"},
                {"trecho_vaga": "Python"},
                {"trecho_vaga": "SQL"},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "C",
                    "evidencia_curriculo": "SQL",
                    "explicacao": "Correspondência incorreta.",
                },
                {
                    "trecho_vaga": "Python",
                    "evidencia_curriculo": "SQL",
                    "explicacao": "Correspondência incorreta.",
                },
            ],
            "alteracoes": [],
        }, "SQL básico.", "A vaga exige C e Python.")

        self.assertEqual(resposta.status_code, 200)
        requisitos = resposta.get_json()["requisitos"]
        self.assertEqual(
            [item["trecho_vaga"] for item in requisitos],
            ["C", "Python"],
        )
        self.assertTrue(all(
            item["status"] == "nao_identificado"
            for item in requisitos
        ))

    def test_rota_envia_textos_recebidos_ao_ollama_sem_exibir_no_terminal(self):
        curriculo = (
            "Linguagens: Python, C e SQL (básico); C++ (em aprendizado)."
        )
        vaga = "Conhecimentos básicos em linguagem C."
        resultado_ollama = {
            "requisitos_vaga": [
                {"trecho_vaga": vaga},
            ],
            "pontos_encontrados": [
                {
                    "trecho_vaga": "linguagem C",
                    "evidencia_curriculo": "C",
                    "explicacao": "A linguagem C aparece no currículo.",
                },
            ],
            "alteracoes": [],
        }
        with patch.object(
            servidor.urllib.request,
            "urlopen",
            return_value=resposta_ollama(resultado_ollama),
        ) as chamada:
            resposta = self.cliente.post(
                "/api/analisar",
                data={"curriculo": curriculo, "vaga": vaga},
            )

        pedido = json.loads(chamada.call_args.args[0].data)
        texto_enviado = pedido["messages"][1]["content"]
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(curriculo, texto_enviado)
        self.assertIn(vaga, texto_enviado)

    def test_printes_sao_transcritos_sem_comparacao_ou_curriculo(self):
        dados_imagem = b"imagem de teste"
        with patch.object(
            servidor.urllib.request,
            "urlopen",
            return_value=resposta_ollama({
                "transcricao_vaga": "A vaga exige Python."
            }),
        ) as chamada:
            resposta = self.cliente.post(
                "/api/analisar",
                data={
                    "curriculo": "Texto confidencial do currículo.",
                    "vaga": "",
                    "imagens": (
                        io.BytesIO(dados_imagem),
                        "print.png",
                        "image/png",
                    ),
                },
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.get_json()["aguardando_confirmacao"])
        pedido = json.loads(chamada.call_args.args[0].data)
        mensagem = pedido["messages"][1]
        self.assertNotIn("Texto confidencial", mensagem["content"])
        self.assertIn("images", mensagem)


class PdfTestes(unittest.TestCase):
    def setUp(self):
        servidor.app.testing = True
        self.cliente = servidor.app.test_client()

    def editar(self, pdf, alteracoes):
        return self.cliente.post(
            "/api/pdf",
            data={
                "pdf": (io.BytesIO(pdf), "curriculo.pdf"),
                "alteracoes": json.dumps(alteracoes),
            },
            content_type="multipart/form-data",
        )

    def test_sem_alteracoes_devolve_bytes_originais(self):
        original = criar_pdf(["Currículo original."])
        resposta = self.editar(original, [])
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data, original)

    def test_substituicao_unica_e_segura_pode_ser_aplicada(self):
        original = criar_pdf(["Python"])
        resposta = self.editar(original, [{
            "original": "Python",
            "sugerido": "C",
        }])

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(texto_pdf(resposta.data), "C")

    def test_recusa_trecho_ausente_repetido_multilinha_ou_sem_espaco(self):
        casos = [
            (criar_pdf(["Texto simples."]), "inexistente", "Python"),
            (criar_pdf(["Python", "Python"]), "Python", "C"),
            (criar_pdf(["Pythonabc"]), "Python", "C"),
            (
                criar_pdf(["Desenvolvi projetos", "em Python"]),
                "Desenvolvi projetos em Python",
                "Construí aplicações avançadas em Python",
            ),
            (criar_pdf(["C"]), "C", "Uma descrição muito extensa"),
        ]

        for pdf, original, sugerido in casos:
            with self.subTest(original=original, sugerido=sugerido):
                texto_original = texto_pdf(pdf)
                resposta = self.editar(pdf, [{
                    "original": original,
                    "sugerido": sugerido,
                }])
                self.assertEqual(resposta.status_code, 400)
                self.assertEqual(texto_pdf(pdf), texto_original)


if __name__ == "__main__":
    unittest.main()
