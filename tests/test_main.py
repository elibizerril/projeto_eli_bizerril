"""Testes offline do sistema (nenhuma chamada real às APIs)."""

from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import requests

import main as app


class RespostaFalsa:
    def __init__(
        self,
        dados: Any = None,
        *,
        status: int = 200,
        json_invalido: bool = False,
    ) -> None:
        self._dados = dados
        self.status_code = status
        self._json_invalido = json_invalido

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> Any:
        if self._json_invalido:
            raise ValueError("corpo não é JSON")
        return self._dados


class SessaoFalsa:
    def __init__(self, *respostas: Any) -> None:
        self.respostas = list(respostas)
        self.headers: dict[str, str] = {}
        self.chamadas: list[tuple[str, dict[str, Any] | None, int | None]] = []
        self.fechada = False

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> RespostaFalsa:
        self.chamadas.append((url, params, timeout))
        resposta = self.respostas.pop(0)
        if isinstance(resposta, BaseException):
            raise resposta
        return resposta

    def close(self) -> None:
        self.fechada = True


class ValidacaoTests(unittest.TestCase):
    def test_uf_normaliza(self) -> None:
        self.assertEqual(app.validar_uf(" ce "), "CE")

    def test_uf_vazia(self) -> None:
        with self.assertRaises(app.ConsultaError) as contexto:
            app.validar_uf("")

        self.assertIn("Campo vazio", str(contexto.exception))

    def test_uf_inexistente(self) -> None:
        with self.assertRaises(app.ConsultaError) as contexto:
            app.validar_uf("XX")

        self.assertIn("UF inexistente", str(contexto.exception))

    def test_id_valido(self) -> None:
        self.assertEqual(app.validar_id_deputado("220593"), 220593)

    def test_id_vazio(self) -> None:
        with self.assertRaises(app.ConsultaError) as contexto:
            app.validar_id_deputado("  ")

        self.assertIn("Campo vazio", str(contexto.exception))

    def test_id_nao_numerico(self) -> None:
        with self.assertRaises(app.ConsultaError):
            app.validar_id_deputado("abc")

    def test_id_zero(self) -> None:
        with self.assertRaises(app.ConsultaError):
            app.validar_id_deputado("0")


class ConsultaIBGETests(unittest.TestCase):
    def test_listar_estados(self) -> None:
        dados = [
            {"sigla": "CE", "nome": "Ceará", "regiao": {"nome": "Nordeste"}},
            {"sigla": "RJ", "nome": "Rio de Janeiro", "regiao": {"nome": "Sudeste"}},
        ]
        http = SessaoFalsa(RespostaFalsa(dados))
        consulta = app.ConsultaIBGE(session=http)  # type: ignore[arg-type]

        estados = consulta.consultar("estados")

        self.assertEqual(len(estados), 2)
        self.assertEqual(estados[0], {"sigla": "CE", "nome": "Ceará", "regiao": "Nordeste"})
        self.assertEqual(consulta.requisicoes, 1)
        url, params, timeout = http.chamadas[0]
        self.assertTrue(url.endswith("/localidades/estados"))
        self.assertEqual(params, {"orderBy": "nome"})
        self.assertEqual(timeout, 10)

    def test_listar_municipios(self) -> None:
        dados = [
            {
                "nome": "Fortaleza",
                "microrregiao": {
                    "mesorregiao": {"UF": {"regiao": {"nome": "Nordeste"}}}
                },
            }
        ]
        http = SessaoFalsa(RespostaFalsa(dados))
        consulta = app.ConsultaIBGE(session=http)  # type: ignore[arg-type]

        municipios = consulta.consultar("municipios", uf="ce")

        self.assertEqual(
            municipios,
            [{"nome": "Fortaleza", "uf": "CE", "regiao": "Nordeste"}],
        )
        self.assertTrue(http.chamadas[0][0].endswith("/estados/CE/municipios"))

    def test_municipios_com_regiao_imediata(self) -> None:
        dados = [
            {
                "nome": "Belém",
                "regiao-imediata": {
                    "regiao-intermediaria": {"UF": {"regiao": {"nome": "Norte"}}}
                },
            }
        ]
        consulta = app.ConsultaIBGE(session=SessaoFalsa(RespostaFalsa(dados)))  # type: ignore[arg-type]

        municipios = consulta.listar_municipios("PA")

        self.assertEqual(municipios[0]["regiao"], "Norte")

    def test_municipios_uf_vazia_nao_chama_api(self) -> None:
        http = SessaoFalsa()
        consulta = app.ConsultaIBGE(session=http)  # type: ignore[arg-type]

        with self.assertRaises(app.ConsultaError):
            consulta.consultar("municipios", uf="")

        self.assertEqual(http.chamadas, [])

    def test_estados_formato_inesperado(self) -> None:
        consulta = app.ConsultaIBGE(session=SessaoFalsa(RespostaFalsa({"x": 1})))  # type: ignore[arg-type]

        with self.assertRaises(app.ConsultaError) as contexto:
            consulta.listar_estados()

        self.assertIn("formato inesperado", str(contexto.exception))

    def test_recurso_desconhecido(self) -> None:
        consulta = app.ConsultaIBGE(session=SessaoFalsa())  # type: ignore[arg-type]

        with self.assertRaises(app.ConsultaError):
            consulta.consultar("paises")


class ConsultaCamaraTests(unittest.TestCase):
    def test_listar_deputados(self) -> None:
        dados = {
            "dados": [
                {"id": 1, "nome": "Ana", "siglaPartido": "PT", "siglaUf": "CE"},
                {"id": 2, "nome": "Bruno", "siglaPartido": "PL", "siglaUf": "RJ"},
            ]
        }
        http = SessaoFalsa(RespostaFalsa(dados))
        consulta = app.ConsultaCamara(session=http)  # type: ignore[arg-type]

        deputados = consulta.consultar("deputados", uf="ce", partido="PT")

        self.assertEqual(len(deputados), 2)
        self.assertEqual(deputados[0]["nome"], "Ana")
        params = http.chamadas[0][1] or {}
        self.assertEqual(params["siglaUf"], "CE")
        self.assertEqual(params["siglaPartido"], "PT")

    def test_listar_deputados_sem_filtros(self) -> None:
        dados = {"dados": [{"id": 1, "nome": "Ana", "siglaPartido": "PT", "siglaUf": "CE"}]}
        http = SessaoFalsa(RespostaFalsa(dados))
        consulta = app.ConsultaCamara(session=http)  # type: ignore[arg-type]

        consulta.listar_deputados()

        params = http.chamadas[0][1] or {}
        self.assertNotIn("siglaUf", params)
        self.assertNotIn("siglaPartido", params)

    def test_listar_deputados_vazio(self) -> None:
        consulta = app.ConsultaCamara(session=SessaoFalsa(RespostaFalsa({"dados": []})))  # type: ignore[arg-type]

        with self.assertRaises(app.ConsultaError) as contexto:
            consulta.listar_deputados(uf="AC", partido="XPTO")

        self.assertIn("Nenhum deputado encontrado", str(contexto.exception))

    def test_listar_deputados_uf_inexistente(self) -> None:
        consulta = app.ConsultaCamara(session=SessaoFalsa())  # type: ignore[arg-type]

        with self.assertRaises(app.ConsultaError):
            consulta.listar_deputados(uf="XX")

    def test_buscar_deputado(self) -> None:
        dados = {
            "dados": {
                "id": 220593,
                "nomeCivil": "ABILIO JACQUES BRUNINI MOUMER",
                "ultimoStatus": {
                    "nome": "Abilio Brunini",
                    "siglaPartido": "PL",
                    "siglaUf": "MT",
                    "situacao": "Exercício",
                    "email": "dep.abilio@camara.leg.br",
                    "gabinete": {
                        "nome": "123",
                        "telefone": "3215-5123",
                        "email": "gabinete@camara.leg.br",
                    },
                },
            }
        }
        http = SessaoFalsa(RespostaFalsa(dados))
        consulta = app.ConsultaCamara(session=http)  # type: ignore[arg-type]

        deputado = consulta.consultar("deputado", id_deputado="220593")

        self.assertEqual(deputado["nome_civil"], "ABILIO JACQUES BRUNINI MOUMER")
        self.assertEqual(deputado["nome_parlamentar"], "Abilio Brunini")
        self.assertEqual(deputado["situacao"], "Exercício")
        self.assertEqual(deputado["email"], "dep.abilio@camara.leg.br")
        self.assertEqual(deputado["gabinete"], "123")
        self.assertTrue(http.chamadas[0][0].endswith("/deputados/220593"))

    def test_buscar_deputado_inexistente(self) -> None:
        consulta = app.ConsultaCamara(session=SessaoFalsa(RespostaFalsa(status=404)))  # type: ignore[arg-type]

        with self.assertRaises(app.ConsultaError) as contexto:
            consulta.buscar_deputado("999999")

        self.assertIn("Deputado não encontrado", str(contexto.exception))
        self.assertEqual(contexto.exception.status, 404)

    def test_erro_http_generico(self) -> None:
        consulta = app.ConsultaCamara(  # type: ignore[arg-type]
            session=SessaoFalsa(RespostaFalsa({"message": "falha"}, status=500))
        )

        with self.assertRaises(app.ConsultaError) as contexto:
            consulta.listar_deputados()

        self.assertIn("HTTP 500", str(contexto.exception))

    def test_json_invalido(self) -> None:
        consulta = app.ConsultaIBGE(  # type: ignore[arg-type]
            session=SessaoFalsa(RespostaFalsa(json_invalido=True))
        )

        with self.assertRaises(app.ConsultaError) as contexto:
            consulta.listar_estados()

        self.assertIn("não é um JSON válido", str(contexto.exception))

    def test_falha_de_conexao(self) -> None:
        consulta = app.ConsultaIBGE(  # type: ignore[arg-type]
            session=SessaoFalsa(requests.ConnectionError("offline"))
        )

        with self.assertRaises(app.ConsultaError) as contexto:
            consulta.listar_estados()

        self.assertIn("Falha de conexão", str(contexto.exception))

    def test_timeout(self) -> None:
        consulta = app.ConsultaIBGE(  # type: ignore[arg-type]
            session=SessaoFalsa(requests.Timeout("demorou"))
        )

        with self.assertRaises(app.ConsultaError) as contexto:
            consulta.listar_estados()

        self.assertIn("Tempo esgotado", str(contexto.exception))


class HistoricoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.caminho = Path(self._tmp.name) / "historico_consultas.txt"
        self.historico = app.Historico(str(self.caminho))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_registrar_no_formato_pedido(self) -> None:
        self.assertTrue(self.historico.registrar("Consulta Estados IBGE - 27 registro(s)"))

        linha = self.caminho.read_text(encoding="utf-8")
        self.assertRegex(
            linha,
            r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2} - Consulta Estados IBGE - 27 registro\(s\)\n$",
        )

    def test_acrescenta_sem_apagar(self) -> None:
        self.historico.registrar("Consulta Estados IBGE")
        self.historico.registrar("Consulta Deputados Câmara")

        linhas = self.caminho.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(linhas), 2)
        self.assertIn("Consulta Estados IBGE", linhas[0])
        self.assertIn("Consulta Deputados Câmara", linhas[1])

    def test_erro_de_gravacao(self) -> None:
        pasta = Path(self._tmp.name) / "pasta"
        pasta.mkdir()
        historico = app.Historico(str(pasta))

        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            resultado = historico.registrar("Consulta")

        self.assertFalse(resultado)
        self.assertIn("Não foi possível gravar o histórico", saida.getvalue())
        self.assertEqual(historico.tentativas_gravacao, 1)

    def test_exibir_arquivo_ausente(self) -> None:
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.historico.exibir()

        self.assertIn("Nenhuma consulta registrada ainda", saida.getvalue())

    def test_exibir_conteudo(self) -> None:
        self.historico.registrar("Consulta Estados IBGE")

        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.historico.exibir()

        self.assertIn("HISTÓRICO DE CONSULTAS", saida.getvalue())
        self.assertIn("Consulta Estados IBGE", saida.getvalue())
        self.assertIn("Total: 1 consulta(s)", saida.getvalue())


class FonteFalsa:
    def __init__(self, resultado: Any = None, erro: Exception | None = None) -> None:
        self.resultado = resultado
        self.erro = erro
        self.chamadas: list[dict[str, Any]] = []

    def consultar(self, **parametros: Any) -> Any:
        self.chamadas.append(parametros)
        if self.erro is not None:
            raise self.erro
        return self.resultado

    def fechar(self) -> None:
        pass


class AplicacaoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.historico_path = Path(self._tmp.name) / "historico_consultas.txt"
        self.aplicacao = app.Aplicacao()
        self.aplicacao.fechar()
        self.aplicacao.historico = app.Historico(str(self.historico_path))
        self.aplicacao.executando = True

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sucesso_exibe_tabela_e_registra(self) -> None:
        fonte = FonteFalsa(
            [{"sigla": "CE", "nome": "Ceará", "regiao": "Nordeste"}]
        )

        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.aplicacao._executar_consulta(
                "Consulta Estados IBGE",
                fonte.consultar,
                campos=("sigla", "nome", "regiao"),
                rotulos=("UF", "Nome", "Região"),
            )

        self.assertIn("Ceará", saida.getvalue())
        self.assertIn("[INFO] Consulta finalizada.", saida.getvalue())
        linha = self.historico_path.read_text(encoding="utf-8")
        self.assertIn("Consulta Estados IBGE - 1 registro(s)", linha)

    def test_erro_registra_no_historico(self) -> None:
        fonte = FonteFalsa(erro=app.ConsultaError("Campo vazio: informe a UF (ex.: CE)."))

        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.aplicacao._executar_consulta(
                "Consulta Municípios IBGE (UF: vazia)",
                fonte.consultar,
                uf="",
            )

        self.assertIn("[ERRO] Campo vazio", saida.getvalue())
        linha = self.historico_path.read_text(encoding="utf-8")
        self.assertIn("ERRO: Campo vazio", linha)

    def test_detalhe_de_deputado(self) -> None:
        fonte = FonteFalsa(
            {
                "id": 220593,
                "nome_civil": "ABILIO JACQUES BRUNINI MOUMER",
                "nome_parlamentar": "Abilio Brunini",
                "partido": "PL",
                "uf": "MT",
                "situacao": "Exercício",
                "gabinete": "123",
                "telefone": "3215-5123",
                "email": "dep.abilio@camara.leg.br",
            }
        )

        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.aplicacao._executar_consulta(
                "Consulta Deputado Câmara (ID: 220593)",
                fonte.consultar,
            )

        self.assertIn("Nome parlamentar", saida.getvalue())
        self.assertIn("Abilio Brunini", saida.getvalue())
        self.assertIn("Consulta Deputado Câmara (ID: 220593) - 1 registro(s)", self.historico_path.read_text(encoding="utf-8"))

    def test_menu_principal_vazio_e_sair(self) -> None:
        with mock.patch("builtins.input", side_effect=["", "4"]):
            saida = io.StringIO()
            with contextlib.redirect_stdout(saida):
                self.aplicacao.executar()

        self.assertIn("Campo vazio", saida.getvalue())
        self.assertIn("Até logo!", saida.getvalue())

    def test_main_retorna_zero_ao_sair(self) -> None:
        with mock.patch("builtins.input", side_effect=["4"]):
            saida = io.StringIO()
            with contextlib.redirect_stdout(saida):
                codigo = app.main()

        self.assertEqual(codigo, 0)
        self.assertIn("DADOS PÚBLICOS BRASIL", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
