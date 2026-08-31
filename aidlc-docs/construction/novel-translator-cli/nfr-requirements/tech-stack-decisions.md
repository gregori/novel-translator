# Decisões de stack técnica — `novel-translator-cli`

## 1. Resumo

| Área | Decisão |
|---|---|
| Runtime | CPython 3.14 ou superior dentro da série compatível declarada. |
| Projeto/dependências | `uv`, `pyproject.toml`, `.python-version` e `uv.lock` versionado. |
| Build | Hatchling como backend leve; package em `src/novel_translator/`. |
| CLI | Typer, com entry point de console. |
| Validação de borda | Pydantic v2; value objects/dataclasses no domínio quando apropriado. |
| Configuração | `tomllib` para TOML; PyYAML safe loader para YAML; pydantic-settings/python-dotenv para ambiente e `.env`. |
| HTTP | HTTPX síncrono com `Client`, timeouts explícitos e transport injetável. |
| Testes | Pytest, Hypothesis, pytest-cov/Coverage.py. |
| Qualidade | Ruff para lint/format; Pyright strict para `src/`. |
| Locks | Port de lock cross-platform; implementação concreta será fechada no NFR Design. |
| CI | Windows/macOS obrigatórios; Linux informativo. |

As versões exatas serão resolvidas e fixadas em `uv.lock` durante Code Generation. O `pyproject.toml` manterá limites de compatibilidade por versão principal, sem duplicar o lockfile.

## 2. Runtime e packaging

### CPython 3.14

Python 3.14 é baseline explícita do produto. A série está estável e possui binários oficiais para Windows e macOS. O projeto declara `requires-python = ">=3.14,<3.15"` para tornar a baseline reproduzível na v1; ampliação futura exige CI e revisão de compatibilidade.

Referências: [documentação Python 3.14](https://docs.python.org/3.14/) e [histórico oficial de versões](https://www.python.org/doc/versions/).

### uv e Hatchling

`uv` gerencia instalação do Python, ambiente, dependências, scripts e lockfile cross-platform. `.python-version` fixa a série local; `uv.lock` é commitado e não editado manualmente. Hatchling realiza apenas o build do wheel/sdist e preserva separação entre gestão de ambiente e backend de build.

Referências: [projetos e versões no uv](https://docs.astral.sh/uv/concepts/python-versions/) e [features do uv](https://docs.astral.sh/uv/getting-started/features/).

## 3. Interface de linha de comando

Typer implementa `translate`, `approve`, `export`, `inspect` e o comando explícito de cleanup. Tipos Typer ficam no adapter; modelos Typer não atravessam a camada de aplicação. A CLI deve controlar stdout/stderr e serializar `--json` por presenter próprio para manter o contrato independente do framework.

Referência: [documentação oficial do Typer](https://typer.tiangolo.com/).

## 4. Modelos, configuração e serialização

Pydantic v2 valida dados nas bordas com `extra="forbid"`, tipos estritos e conversão explícita para modelos internos. Pydantic já classifica Python 3.14 entre as versões suportadas. Entidades do domínio não herdam de modelos externos quando isso acoplar regras à serialização.

- TOML: `tomllib` da biblioteca padrão.
- YAML: PyYAML somente com safe loader; validação semântica posterior pelo Pydantic.
- Ambiente/`.env`: pydantic-settings e suporte dotenv; segredos são wrappers não serializáveis.
- JSON: biblioteca padrão para snapshots canônicos e presenter `--json`, com ordenação/formatação definida pelo contrato.

Referência: [Pydantic](https://docs.pydantic.dev/latest/) e [metadados oficiais do projeto](https://github.com/pydantic/pydantic/blob/main/pyproject.toml).

## 5. HTTP e retries

HTTPX opera de forma síncrona para corresponder aos casos de uso sequenciais. Um `httpx.Client` reutiliza conexões durante o processo; timeouts de conexão, leitura, escrita e pool são explícitos. O transport é injetado nos testes. Retries de negócio permanecem no `RetryExecutor`, evitando sobreposição silenciosa com retries internos do transport.

Defaults:

- timeout total/configuração equivalente: 120 segundos;
- máximo de três tentativas totais;
- backoff exponencial com jitter;
- retry apenas para classificação transitória definida pela aplicação.

Referências: [timeouts do HTTPX](https://www.python-httpx.org/advanced/timeouts/) e [transports do HTTPX](https://www.python-httpx.org/advanced/transports/).

## 6. Testes e cobertura

Pytest é o runner único. Hypothesis executa propriedades e usa strategies compartilhadas em `tests/strategies/`. O banco de exemplos do Hypothesis pode acelerar reprodução local; em CI, a saída deve preservar o exemplo mínimo e blob/seed aplicável, mantendo a mesma versão pelo lockfile.

pytest-cov/Coverage.py aplicam dois gates:

- 90% de branch coverage para packages domain/application;
- 80% de branch coverage para o projeto total.

Testes por exemplos continuam obrigatórios para cenários críticos; PBT não os substitui.

Referências: [Pytest](https://docs.pytest.org/en/stable/), [Hypothesis — reprodução de falhas](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html) e [Hypothesis API](https://hypothesis.readthedocs.io/en/latest/reference/api.html).

## 7. Lint, formato e tipos

Ruff é o formatter e linter único, com target Python 3.14 e regras selecionadas no `pyproject.toml`. Pyright usa `typeCheckingMode = "strict"` sobre `src/`; exclusões ou ignores são locais, mínimos e justificados. Código gerado deve passar ambos antes do teste completo.

Referências: [Ruff](https://docs.astral.sh/ruff/) e [configuração oficial do Pyright](https://github.com/microsoft/pyright/blob/main/docs/configuration.md).

## 8. Lock e filesystem

O domínio depende de um `WorkspaceLock` port. A implementação deve ser cross-platform, possuir timeout, dados sanitizados do owner e recuperação conservadora de lock obsoleto. A biblioteca concreta será comparada no NFR Design e validada em Windows/macOS; nenhuma escolha pode depender de `fcntl` ou shell.

Escritas atômicas usam temporário no mesmo filesystem, flush conforme necessidade e replace oferecido pelas APIs Python. Semânticas diferentes de Windows/macOS devem ser cobertas por testes de integração.

## 9. Retenção

A retenção por idade existe como política configurável, porém desabilitada por padrão. Ela é executada somente por comando explícito, primeiro produz dry-run, depois exige confirmação. A seleção exclui:

- run apontado como draft atual;
- run com aprovação no histórico;
- run com exportação no histórico.

Não existe daemon, cleanup na inicialização nem deleção implícita.

## 10. Compatibilidade e atualização

- Toda dependência deve resolver para Python 3.14 em Windows e macOS.
- Atualizações são feitas por mudança explícita do lockfile e execução de todos os gates.
- Dependência incompatível bloqueia Code Generation; não se reduz a baseline do Python sem nova decisão aprovada.
- Linux permanece best-effort e não pode mascarar falha nos dois sistemas suportados.

## 11. Alternativas rejeitadas

| Alternativa | Motivo |
|---|---|
| pip/venv ou Poetry | Não correspondem à decisão de workflow unificado com uv. |
| Click/argparse | Typer foi escolhido para interface tipada e help, mantendo isolamento no adapter. |
| Requests/urllib | HTTPX oferece timeouts detalhados e transport substituível alinhados aos testes. |
| Validação manual total | Pydantic reduz duplicação nas bordas estritas. |
| mypy ou ausência de checker | Pyright strict foi escolhido como gate. |
| Limpeza automática | Contraria a clarificação de retenção explícita e protegida. |

## 12. Conformidade e validação

- PBT-09: Hypothesis integra o runner Pytest; PBT-07 centraliza strategies; PBT-08 usa shrinking/reprodução com versões travadas.
- Security Baseline e Resiliency Baseline: N/A por configuração.
- Links apontam para documentação oficial ou repositórios primários.
- Markdown e tabelas foram verificados; não há Mermaid, diagrama ASCII, JSON ou YAML embutido.
