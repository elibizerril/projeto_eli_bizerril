"""Sistema de Consulta a Dados Públicos Brasileiros.

Trabalho acadêmico que consome duas APIs governamentais abertas:

* IBGE — estados e municípios;
* Câmara dos Deputados — deputados federais.

O programa oferece um menu interativo, valida os dados digitados, trata
falhas de rede/API/arquivo e grava automaticamente cada consulta em
``historico_consultas.txt``.

Execução:
    python main.py

Autor: Eli Bizerril
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Callable, Sequence

import requests

ARQUIVO_HISTORICO = "historico_consultas.txt"
LIMITE_EXIBICAO = 20
SEPARADOR = "=" * 32

# Siglas oficiais das 27 unidades federativas.
UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

ROTULOS_DEPUTADO = {
    "id": "ID",
    "nome_civil": "Nome civil",
    "nome_parlamentar": "Nome parlamentar",
    "partido": "Partido",
    "uf": "UF",
    "situacao": "Situação",
    "gabinete": "Gabinete",
    "telefone": "Telefone",
    "email": "E-mail",
}


class ConsultaError(Exception):
    """Erro esperado durante uma consulta ou gravação de arquivo."""

    def __init__(self, mensagem: str, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


# ---------------------------------------------------------------------------
# Validações (executadas antes de acessar a rede)
# ---------------------------------------------------------------------------


def validar_uf(uf: str) -> str:
    """Valida e normaliza uma sigla de UF."""
    uf = (uf or "").strip().upper()
    if not uf:
        raise ConsultaError("Campo vazio: informe a UF (ex.: CE).")
    if uf not in UFS:
        raise ConsultaError(f"UF inexistente: {uf}. Use uma sigla válida (ex.: CE).")
    return uf


def validar_id_deputado(valor: str) -> int:
    """Valida o ID numérico de um deputado."""
    texto = (valor or "").strip()
    if not texto:
        raise ConsultaError("Campo vazio: informe o ID do deputado (ex.: 220593).")
    if not texto.isdigit():
        raise ConsultaError("ID inválido: use apenas números (ex.: 220593).")
    numero = int(texto)
    if numero <= 0:
        raise ConsultaError("ID inválido: o número deve ser maior que zero.")
    return numero


# ---------------------------------------------------------------------------
# Programação Orientada a Objetos
# ---------------------------------------------------------------------------


class ConsultaPublica:
    """Classe base para consultas a APIs públicas.

    Atributos:
        nome: nome da fonte exibido ao usuário;
        base_url: endereço base da API;
        timeout: tempo máximo de espera, em segundos;
        session: sessão HTTP reutilizada entre as consultas;
        requisicoes: contador de requisições realizadas.
    """

    def __init__(
        self,
        nome: str,
        base_url: str,
        timeout: int = 10,
        session: requests.Session | None = None,
    ) -> None:
        self.nome = nome
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "Projeto_Eli_Bizerril/1.0",
            }
        )
        self.requisicoes = 0

    def _requisitar(self, caminho: str, params: dict[str, Any] | None = None) -> Any:
        """Faz a requisição e devolve o JSON, tratando as falhas previsíveis.

        O bloco try/except/else/finally é obrigatório no trabalho e está
        concentrado aqui, no acesso HTTP comum às duas APIs.
        """
        url = f"{self.base_url}{caminho}"

        try:
            resposta = self.session.get(url, params=params, timeout=self.timeout)
            resposta.raise_for_status()
        except requests.exceptions.ConnectionError as erro:
            raise ConsultaError(
                "Falha de conexão. Verifique sua internet e tente novamente."
            ) from erro
        except requests.exceptions.Timeout as erro:
            raise ConsultaError(
                "Tempo esgotado: a API demorou demais para responder."
            ) from erro
        except requests.exceptions.HTTPError as erro:
            status = erro.response.status_code if erro.response is not None else None
            if status == 404:
                raise ConsultaError(
                    "Consulta inexistente: o recurso não foi encontrado na API.",
                    status=404,
                ) from erro
            raise ConsultaError(
                f"Erro na API (HTTP {status}). Tente novamente mais tarde.",
                status=status,
            ) from erro
        except requests.exceptions.RequestException as erro:
            raise ConsultaError(f"Erro ao acessar a API: {erro}") from erro
        else:
            try:
                # Manipulação de JSON exigida pelo trabalho: resposta.json()
                return resposta.json()
            except ValueError as erro:
                raise ConsultaError(
                    "A API respondeu, mas o conteúdo não é um JSON válido."
                ) from erro
        finally:
            # Executado com sucesso ou com erro: mantém o contador atualizado.
            self.requisicoes += 1

    def consultar(self, **parametros: Any) -> Any:
        """Método genérico; cada subclasse implementa o seu comportamento."""
        raise NotImplementedError("A subclasse deve implementar o método consultar().")

    def fechar(self) -> None:
        self.session.close()

    def __str__(self) -> str:
        return self.nome


class ConsultaIBGE(ConsultaPublica):
    """Consulta estados e municípios na API oficial do IBGE."""

    def __init__(
        self,
        timeout: int = 10,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(
            "IBGE",
            "https://servicodados.ibge.gov.br/api/v1",
            timeout,
            session,
        )

    def consultar(
        self,
        recurso: str = "estados",
        uf: str = "",
    ) -> list[dict[str, Any]]:
        if recurso == "estados":
            return self.listar_estados()
        if recurso == "municipios":
            return self.listar_municipios(uf)
        raise ConsultaError(f"Recurso desconhecido no IBGE: {recurso!r}.")

    def listar_estados(self) -> list[dict[str, Any]]:
        """GET /localidades/estados."""
        dados = self._requisitar("/localidades/estados", {"orderBy": "nome"})
        if not isinstance(dados, list):
            raise ConsultaError("O IBGE retornou um formato inesperado para estados.")

        estados: list[dict[str, Any]] = []
        for item in dados:
            if not isinstance(item, dict):
                continue
            regiao = item.get("regiao") or {}
            estados.append(
                {
                    "sigla": item.get("sigla") or "",
                    "nome": item.get("nome") or "",
                    "regiao": (regiao.get("nome") or "")
                    if isinstance(regiao, dict)
                    else "",
                }
            )

        if not estados:
            raise ConsultaError("O IBGE não retornou nenhum estado.")
        return estados

    def listar_municipios(self, uf: str) -> list[dict[str, Any]]:
        """GET /localidades/estados/{UF}/municipios."""
        uf = validar_uf(uf)
        dados = self._requisitar(f"/localidades/estados/{uf}/municipios")
        if not isinstance(dados, list):
            raise ConsultaError("O IBGE retornou um formato inesperado para municípios.")

        municipios: list[dict[str, Any]] = []
        for item in dados:
            if not isinstance(item, dict):
                continue
            municipios.append(
                {
                    "nome": item.get("nome") or "",
                    "uf": uf,
                    "regiao": _regiao_do_municipio(item),
                }
            )

        if not municipios:
            raise ConsultaError(f"O IBGE não retornou municípios para a UF {uf}.")
        return municipios


class ConsultaCamara(ConsultaPublica):
    """Consulta deputados na API de Dados Abertos da Câmara dos Deputados."""

    def __init__(
        self,
        timeout: int = 10,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(
            "Câmara dos Deputados",
            "https://dadosabertos.camara.leg.br/api/v2",
            timeout,
            session,
        )

    def consultar(
        self,
        recurso: str = "deputados",
        uf: str = "",
        partido: str = "",
        id_deputado: str = "",
    ) -> Any:
        if recurso == "deputados":
            return self.listar_deputados(uf=uf, partido=partido)
        if recurso == "deputado":
            return self.buscar_deputado(id_deputado)
        raise ConsultaError(f"Recurso desconhecido na Câmara: {recurso!r}.")

    def listar_deputados(
        self,
        uf: str = "",
        partido: str = "",
    ) -> list[dict[str, Any]]:
        """GET /deputados, com filtros opcionais de UF e partido."""
        uf = (uf or "").strip().upper()
        partido = (partido or "").strip()

        if uf and uf not in UFS:
            raise ConsultaError(f"UF inexistente: {uf}. Use uma sigla válida (ex.: CE).")
        if partido and len(partido) > 20:
            raise ConsultaError("Partido inválido: use no máximo 20 caracteres.")

        parametros: dict[str, Any] = {
            "itens": 100,
            "pagina": 1,
            "ordem": "ASC",
            "ordenarPor": "nome",
        }
        if uf:
            parametros["siglaUf"] = uf
        if partido:
            parametros["siglaPartido"] = partido

        dados = self._requisitar("/deputados", parametros)
        if not isinstance(dados, dict):
            raise ConsultaError("A Câmara retornou um formato inesperado para deputados.")

        lista = dados.get("dados")
        if not isinstance(lista, list):
            raise ConsultaError("A Câmara não retornou a lista de deputados.")

        deputados: list[dict[str, Any]] = []
        for item in lista:
            if not isinstance(item, dict):
                continue
            deputados.append(
                {
                    "id": item.get("id") or "",
                    "nome": item.get("nome") or item.get("nomeCivil") or "",
                    "partido": item.get("siglaPartido") or "",
                    "uf": item.get("siglaUf") or "",
                }
            )

        if not deputados:
            raise ConsultaError(
                "Nenhum deputado encontrado com os filtros informados."
            )
        return deputados

    def buscar_deputado(self, id_deputado: str) -> dict[str, Any]:
        """GET /deputados/{id}."""
        numero = validar_id_deputado(id_deputado)

        try:
            dados = self._requisitar(f"/deputados/{numero}")
        except ConsultaError as erro:
            if erro.status == 404:
                raise ConsultaError(
                    f"Deputado não encontrado para o ID {numero}.",
                    status=404,
                ) from erro
            raise

        if not isinstance(dados, dict):
            raise ConsultaError("A Câmara retornou um formato inesperado para o deputado.")

        item = dados.get("dados")
        if not isinstance(item, dict):
            raise ConsultaError("A Câmara não retornou os dados do deputado.")

        status = item.get("ultimoStatus") or {}
        if not isinstance(status, dict):
            status = {}
        gabinete = status.get("gabinete") or {}
        if not isinstance(gabinete, dict):
            gabinete = {}

        return {
            "id": item.get("id") or numero,
            "nome_civil": item.get("nomeCivil") or "",
            "nome_parlamentar": status.get("nome") or "",
            "partido": status.get("siglaPartido") or "",
            "uf": status.get("siglaUf") or "",
            "situacao": status.get("situacao")
            or status.get("descricaoStatus")
            or "",
            "gabinete": gabinete.get("nome") or "",
            "telefone": gabinete.get("telefone") or "",
            "email": status.get("email") or gabinete.get("email") or "",
        }


def _regiao_do_municipio(item: dict[str, Any]) -> str:
    """Extrai a região em qualquer um dos formatos usados pelo IBGE."""
    caminhos = (
        ("microrregiao", "mesorregiao", "UF", "regiao", "nome"),
        ("regiao-imediata", "regiao-intermediaria", "UF", "regiao", "nome"),
    )
    for caminho in caminhos:
        atual: Any = item
        for chave in caminho:
            if not isinstance(atual, dict):
                atual = None
                break
            atual = atual.get(chave)
        if atual:
            return str(atual)
    return ""


# ---------------------------------------------------------------------------
# Manipulação de arquivo: histórico de consultas
# ---------------------------------------------------------------------------


class Historico:
    """Grava e lê o arquivo ``historico_consultas.txt``."""

    def __init__(self, caminho: str = ARQUIVO_HISTORICO) -> None:
        self.caminho = caminho
        self.tentativas_gravacao = 0

    def registrar(self, descricao: str) -> bool:
        """Acrescenta uma linha no formato: 11/11/2026 19:32 - Consulta ..."""
        linha = f"{datetime.now():%d/%m/%Y %H:%M} - {descricao}\n"

        try:
            with open(self.caminho, "a", encoding="utf-8") as arquivo:
                arquivo.write(linha)
        except OSError as erro:
            print(f"\n[ERRO] Não foi possível gravar o histórico: {erro}")
            return False
        else:
            return True
        finally:
            self.tentativas_gravacao += 1

    def exibir(self) -> None:
        """Mostra o conteúdo do histórico, tratando arquivo ausente ou vazio."""
        print(f"\n{SEPARADOR}")
        print("HISTÓRICO DE CONSULTAS")
        print(SEPARADOR)

        try:
            with open(self.caminho, encoding="utf-8") as arquivo:
                linhas = [linha.rstrip() for linha in arquivo if linha.strip()]
        except FileNotFoundError:
            print("Nenhuma consulta registrada ainda.")
            return
        except OSError as erro:
            print(f"[ERRO] Não foi possível ler o histórico: {erro}")
            return
        else:
            if not linhas:
                print("Nenhuma consulta registrada ainda.")
            else:
                for linha in linhas:
                    print(linha)
                    print("-" * len(linha))
                print(f"Total: {len(linhas)} consulta(s).")
        finally:
            print(SEPARADOR)


# ---------------------------------------------------------------------------
# Apresentação no terminal
# ---------------------------------------------------------------------------


def _truncar(texto: str, largura: int) -> str:
    if len(texto) <= largura:
        return texto
    if largura <= 3:
        return texto[:largura]
    return texto[: largura - 3] + "..."


def exibir_tabela(
    linhas: Sequence[dict[str, Any]],
    campos: Sequence[str],
    rotulos: Sequence[str],
) -> None:
    """Imprime uma tabela simples, sem dependências externas."""
    textos = [
        [
            str(linha.get(campo)) if linha.get(campo) not in (None, "") else "-"
            for campo in campos
        ]
        for linha in linhas
    ]
    larguras = []
    for indice, rotulo in enumerate(rotulos):
        largura = max([len(rotulo)] + [len(linha[indice]) for linha in textos])
        larguras.append(min(largura, 40))

    print("  ".join(rotulo.ljust(largura) for rotulo, largura in zip(rotulos, larguras)))
    print("  ".join("-" * largura for largura in larguras))
    for linha in textos:
        print(
            "  ".join(
                _truncar(valor, largura).ljust(largura)
                for valor, largura in zip(linha, larguras)
            ).rstrip()
        )


class Aplicacao:
    """Monta os objetos e controla o menu interativo."""

    def __init__(self) -> None:
        self.ibge = ConsultaIBGE()
        self.camara = ConsultaCamara()
        self.historico = Historico()
        self.executando = True

    # -- menu principal ----------------------------------------------------

    def executar(self) -> None:
        self._cabecalho()
        try:
            while self.executando:
                self._menu_principal()
        finally:
            self.fechar()
            print("\nAté logo!")

    def _cabecalho(self) -> None:
        print(SEPARADOR)
        print("DADOS PÚBLICOS BRASIL")
        print(SEPARADOR)
        print("IBGE + Câmara dos Deputados")

    def _menu_principal(self) -> None:
        print(f"\n{SEPARADOR}")
        print("MENU PRINCIPAL")
        print(SEPARADOR)
        print("1 - Consultar IBGE")
        print("2 - Consultar Câmara dos Deputados")
        print("3 - Exibir Histórico")
        print("4 - Sair")

        opcao = self._ler("Escolha: ")
        if not opcao:
            print("\n[ERRO] Campo vazio. Digite uma opção de 1 a 4.")
        elif opcao == "1":
            self._menu_ibge()
        elif opcao == "2":
            self._menu_camara()
        elif opcao == "3":
            self.historico.exibir()
        elif opcao == "4":
            self.executando = False
        else:
            print("\n[ERRO] Opção inválida. Digite uma opção de 1 a 4.")

    # -- submenu IBGE ------------------------------------------------------

    def _menu_ibge(self) -> None:
        while True:
            print(f"\n{SEPARADOR}")
            print("IBGE - LOCALIDADES")
            print(SEPARADOR)
            print("1 - Listar estados")
            print("2 - Listar municípios de uma UF")
            print("0 - Voltar")

            opcao = self._ler("Escolha: ")
            if opcao == "0":
                return
            if not opcao:
                print("\n[ERRO] Campo vazio. Digite 1, 2 ou 0.")
            elif opcao == "1":
                self._executar_consulta(
                    "Consulta Estados IBGE",
                    self.ibge.consultar,
                    campos=("sigla", "nome", "regiao"),
                    rotulos=("UF", "Nome", "Região"),
                    recurso="estados",
                )
            elif opcao == "2":
                uf = self._ler("UF (ex.: CE): ")
                self._executar_consulta(
                    f"Consulta Municípios IBGE (UF: {uf.upper() or 'vazia'})",
                    self.ibge.consultar,
                    campos=("nome", "uf", "regiao"),
                    rotulos=("Município", "UF", "Região"),
                    recurso="municipios",
                    uf=uf,
                )
            else:
                print("\n[ERRO] Opção inválida. Digite 1, 2 ou 0.")

    # -- submenu Câmara ----------------------------------------------------

    def _menu_camara(self) -> None:
        while True:
            print(f"\n{SEPARADOR}")
            print("CÂMARA DOS DEPUTADOS")
            print(SEPARADOR)
            print("1 - Listar deputados")
            print("2 - Buscar deputado por ID")
            print("0 - Voltar")

            opcao = self._ler("Escolha: ")
            if opcao == "0":
                return
            if not opcao:
                print("\n[ERRO] Campo vazio. Digite 1, 2 ou 0.")
            elif opcao == "1":
                uf = self._ler("UF (Enter para todas): ").upper()
                partido = self._ler("Partido (Enter para todos): ")
                filtros = []
                if uf:
                    filtros.append(f"UF: {uf}")
                if partido:
                    filtros.append(f"Partido: {partido}")
                sufixo = f" ({', '.join(filtros)})" if filtros else " (todos)"
                self._executar_consulta(
                    f"Consulta Deputados Câmara{sufixo}",
                    self.camara.consultar,
                    campos=("id", "nome", "partido", "uf"),
                    rotulos=("ID", "Nome", "Partido", "UF"),
                    recurso="deputados",
                    uf=uf,
                    partido=partido,
                )
            elif opcao == "2":
                id_deputado = self._ler("ID do deputado (ex.: 220593): ")
                self._executar_consulta(
                    f"Consulta Deputado Câmara (ID: {id_deputado or 'vazio'})",
                    self.camara.consultar,
                    recurso="deputado",
                    id_deputado=id_deputado,
                )
            else:
                print("\n[ERRO] Opção inválida. Digite 1, 2 ou 0.")

    # -- execução e exibição ----------------------------------------------

    def _executar_consulta(
        self,
        descricao: str,
        funcao: Callable[..., Any],
        *,
        campos: Sequence[str] = (),
        rotulos: Sequence[str] = (),
        **parametros: Any,
    ) -> None:
        """Executa uma consulta registrando sucesso ou erro no histórico.

        Este é o segundo bloco try/except/else/finally do programa: o
        ``finally`` garante o aviso de encerramento em qualquer cenário.
        """
        try:
            resultado = funcao(**parametros)
        except ConsultaError as erro:
            print(f"\n[ERRO] {erro}")
            self.historico.registrar(f"{descricao} - ERRO: {erro}")
            return
        except Exception as erro:  # rede de segurança para falhas inesperadas
            print(f"\n[ERRO] Falha inesperada: {erro}")
            self.historico.registrar(f"{descricao} - ERRO inesperado: {erro}")
            return
        else:
            self._mostrar_resultado(resultado, campos, rotulos)
            quantidade = 1 if isinstance(resultado, dict) else len(resultado)
            self.historico.registrar(f"{descricao} - {quantidade} registro(s)")
        finally:
            print("[INFO] Consulta finalizada.")

    def _mostrar_resultado(
        self,
        resultado: Any,
        campos: Sequence[str],
        rotulos: Sequence[str],
    ) -> None:
        if isinstance(resultado, dict):
            self._mostrar_detalhe(resultado)
            return

        if not isinstance(resultado, list) or not resultado:
            print("\nNenhum registro encontrado.")
            return

        exibidas = resultado[:LIMITE_EXIBICAO]
        print()
        exibir_tabela(exibidas, campos, rotulos)

        restantes = len(resultado) - len(exibidas)
        if restantes > 0:
            print(f"\n... e mais {restantes} registro(s).")
        print(f"Total: {len(resultado)} registro(s).")

    @staticmethod
    def _mostrar_detalhe(dados: dict[str, Any]) -> None:
        print()
        for chave, valor in dados.items():
            rotulo = ROTULOS_DEPUTADO.get(chave, chave.replace("_", " ").title())
            texto = str(valor) if valor not in (None, "") else "-"
            print(f"{rotulo:<18}: {texto}")

    # -- entrada e encerramento -------------------------------------------

    @staticmethod
    def _ler(mensagem: str) -> str:
        try:
            return input(mensagem).strip()
        except EOFError as erro:
            raise KeyboardInterrupt from erro

    def fechar(self) -> None:
        self.ibge.fechar()
        self.camara.fechar()


def main() -> int:
    aplicacao = Aplicacao()
    try:
        aplicacao.executar()
    except KeyboardInterrupt:
        print("\n\nPrograma interrompido pelo usuário.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
