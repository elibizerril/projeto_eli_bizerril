# Sistema de Consulta a Dados Públicos Brasileiros

**Aluno:** Eli Bizerril
**Projeto:** Projeto_Eli_Bizerril
**Linguagem:** Python 3.10 ou superior
**Dependência externa:** `requests`

## 1. Objetivo

Aplicação em Python que consome duas APIs governamentais abertas, realiza
consultas dinâmicas por meio de um menu interativo, trata exceções, grava um
histórico em arquivo e percorre as listas e dicionários retornados em JSON.

## 2. APIs governamentais utilizadas

| API | Dados consultados | Endpoints |
| --- | --- | --- |
| **IBGE** — Serviço de Dados | Estados e municípios brasileiros | `/api/v1/localidades/estados` e `/api/v1/localidades/estados/{UF}/municipios` |
| **Câmara dos Deputados** — Dados Abertos | Lista de deputados e detalhe de um deputado | `/api/v2/deputados` e `/api/v2/deputados/{id}` |

As duas APIs são oficiais, públicas e **não exigem chave, token ou cadastro**.

## 3. Requisitos atendidos

| Requisito | Como foi atendido |
| --- | --- |
| **Programação Orientada a Objetos** | Classe base `ConsultaPublica` com atributos, construtor `__init__`, métodos e objetos. As classes `ConsultaIBGE`, `ConsultaCamara`, `Historico` e `Aplicacao` herdam ou compõem essa estrutura. |
| **Duas APIs governamentais** | IBGE (estados/municípios) e Câmara dos Deputados (deputados). |
| **Manipulação de arquivos** | Classe `Historico` grava automaticamente em `historico_consultas.txt` e lê o arquivo no menu "Exibir Histórico". |
| **Tratamento de exceções** | Blocos `try/except/else/finally` no acesso HTTP e na execução das consultas. Trata campo vazio, consulta inexistente, erro da API e erro de gravação. |
| **Manipulação de JSON** | Uso de `resposta.json()` e percurso de listas (`dados`, `regiao`) e dicionários (`dados["dados"]`, `ultimoStatus`). |
| **Menu interativo** | Menu principal com 4 opções e submenus para o IBGE e para a Câmara. |

## 4. Estrutura do projeto

```text
Projeto_Eli_Bizerril/
├── main.py                    # sistema completo (classes + menu)
├── historico_consultas.txt    # gerado automaticamente
├── README.md
├── README.pdf
├── requirements.txt
└── tests/
    └── test_main.py           # 33 testes offline
```

## 5. Instalação

```powershell
cd E:\Projeto\Projeto_Eli_Bizerril
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 6. Execução

```powershell
.\.venv\Scripts\python.exe main.py
```

Ao iniciar, o programa mostra o menu principal:

```text
================================
DADOS PÚBLICOS BRASIL
================================
IBGE + Câmara dos Deputados

================================
MENU PRINCIPAL
================================
1 - Consultar IBGE
2 - Consultar Câmara dos Deputados
3 - Exibir Histórico
4 - Sair
Escolha:
```

### Submenu IBGE

```text
================================
IBGE - LOCALIDADES
================================
1 - Listar estados
2 - Listar municípios de uma UF
0 - Voltar
```

Na opção 2, o usuário digita a sigla da UF (por exemplo, `CE`). A consulta é
dinâmica: o programa valida a sigla e monta o endpoint correspondente.

### Submenu Câmara dos Deputados

```text
================================
CÂMARA DOS DEPUTADOS
================================
1 - Listar deputados
2 - Buscar deputado por ID
0 - Voltar
```

Na opção 1, é possível filtrar por UF e por partido. Basta pressionar Enter
para não filtrar. Na opção 2, o usuário informa o ID do deputado (por exemplo,
`220593`).

## 7. Exemplos de saída

Lista de estados (trecho):

```text
UF  Nome                 Região
--  -------------------  ------------
AC  Acre                 Norte
AL  Alagoas              Nordeste
...
Total: 27 registro(s).
```

Municípios de uma UF (trecho):

```text
Município          UF  Região
-----------------  --  --------
Abaiara            CE  Nordeste
Acarape            CE  Nordeste
...
Total: 184 registro(s).
```

Lista de deputados com filtro (trecho):

```text
ID      Nome                      Partido  UF
------  ------------------------  -------  --
141464  José Airton Félix Cirilo  PT       CE
Total: 1 registro(s).
```

Detalhe de um deputado:

```text
ID                : 220593
Nome civil        : ABILIO JACQUES BRUNINI MOUMER
Nome parlamentar  : Abilio Brunini
Partido           : PL
UF                : MT
Situação          : Vacância
```

## 8. Histórico de consultas

Toda consulta é gravada automaticamente em `historico_consultas.txt`, no
formato pedido:

```text
11/11/2026 20:03 - Consulta Estados IBGE - 27 registro(s)
11/11/2026 20:03 - Consulta Municípios IBGE (UF: CE) - 184 registro(s)
11/11/2026 20:03 - Consulta Deputados Câmara (UF: CE, Partido: PT) - 1 registro(s)
11/11/2026 20:03 - Consulta Deputado Câmara (ID: 220593) - 1 registro(s)
```

Consultas com erro também são registradas, o que ajuda a diagnosticar
problemas:

```text
11/11/2026 20:03 - Consulta Municípios IBGE (UF: vazia) - ERRO: Campo vazio: informe a UF (ex.: CE).
```

O menu 3 lê o arquivo e mostra o histórico completo. Se o arquivo ainda não
existir, o programa informa que nenhuma consulta foi registrada.

## 9. Tratamento de exceções

O programa usa `try/except/else/finally` em dois pontos principais:

1. **`ConsultaPublica._requisitar`** — acesso HTTP comum às duas APIs;
2. **`Aplicacao._executar_consulta`** — execução da consulta e gravação do
   histórico.

Cenários tratados:

| Situação | Comportamento |
| --- | --- |
| Campo vazio | Mensagem "Campo vazio" e consulta não é enviada à API. |
| UF inexistente | Mensagem "UF inexistente" com exemplo de sigla válida. |
| ID inválido | Exige apenas números e valor maior que zero. |
| Consulta inexistente | HTTP 404 vira "Consulta inexistente" ou "Deputado não encontrado". |
| Erro na API | HTTP 500, 502 etc. mostram o código e orientam tentar novamente. |
| Falha de conexão | Mensagem amigável, sem encerrar o programa. |
| Timeout | Mensagem "Tempo esgotado". |
| JSON inválido | Mensagem "não é um JSON válido". |
| Erro de gravação | Mostra o erro do sistema operacional e continua em execução. |

## 10. Programação Orientada a Objetos

A classe base está em `main.py`:

```python
class ConsultaPublica:
    def __init__(self, nome, base_url, timeout=10, session=None):
        self.nome = nome
        self.base_url = base_url
        self.timeout = timeout
        self.session = session or requests.Session()
        self.requisicoes = 0

    def _requisitar(self, caminho, params=None):
        ...

    def consultar(self, **parametros):
        raise NotImplementedError(...)

    def fechar(self):
        self.session.close()
```

As classes `ConsultaIBGE` e `ConsultaCamara` herdam de `ConsultaPublica` e
implementam o método `consultar`. A classe `Aplicacao` cria os objetos e
controla o menu:

```python
class Aplicacao:
    def __init__(self):
        self.ibge = ConsultaIBGE()
        self.camara = ConsultaCamara()
        self.historico = Historico()
        self.executando = True
```

## 11. Testes

Os testes são offline: usam uma sessão HTTP falsa e não consultam as APIs
reais.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Resultado esperado:

```text
Ran 33 tests in 0.159s
OK
```

Os testes cobrem validação, sucesso e erro das duas APIs, formato do histórico,
erro de gravação, exibição do histórico e o fluxo do menu.

## 12. Limitações

- A lista de deputados retorna no máximo 100 registros por consulta.
- Os dados refletem o momento da consulta; não há cache local.
- A disponibilidade depende dos servidores do IBGE e da Câmara dos Deputados.
- O histórico é um arquivo de texto simples, sem controle de usuários.
