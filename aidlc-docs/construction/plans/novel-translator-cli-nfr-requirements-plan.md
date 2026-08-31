# Plano de NFR Requirements — `novel-translator-cli`

## Objetivo

Transformar os NFRs aprovados em metas verificáveis e decidir a stack técnica da CLI, cobrindo desempenho, capacidade, confiabilidade, segurança mínima, manutenção, testes, portabilidade e usabilidade.

## Plano de execução

- [x] Ler o Functional Design aprovado e os NFRs existentes.
- [x] Avaliar todas as categorias obrigatórias de NFR.
- [x] Registrar as decisões técnicas e metas pendentes abaixo.
- [x] Validar respostas quanto a completude, ambiguidade e contradição.
- [x] Criar pergunta de esclarecimento para a política de retenção por idade.
- [x] Consolidar requisitos mensuráveis e critérios de verificação.
- [x] Consolidar stack, ferramentas e justificativas.
- [x] Validar conformidade PBT e conteúdo dos artefatos.
- [x] Atualizar plano, estado e auditoria; solicitar aprovação de NFR Requirements.

## Decisões

## Question 1 — Versão mínima do Python

Qual baseline deve ser suportada pela v1?

A) Python 3.12 ou superior, priorizando compatibilidade ampla.

B) Python 3.13 ou superior, priorizando recursos mais recentes.

C) Python 3.14 ou superior, aceitando ecossistema e adoção mais novos.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: C

## Question 2 — Gerenciamento e build

Qual fluxo deve gerenciar ambiente, lockfile, scripts e build?

A) `uv` com `pyproject.toml`, lockfile versionado e backend de build leve.

B) `pip`/`venv` com `pyproject.toml` e arquivos de requisitos separados.

C) Poetry para dependências, lockfile, ambiente e build.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 3 — Framework da CLI

Qual abordagem deve implementar comandos, opções e ajuda?

A) Typer, com comandos tipados e help gerado.

B) Click, com controle explícito sobre comandos e parâmetros.

C) `argparse` da biblioteca padrão, sem dependência de framework de CLI.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 4 — Modelos e validação

Qual stack deve validar configuração, bible, manifesto e dados externos?

A) Pydantic v2 para modelos de borda estritos; dataclasses/value objects no domínio quando adequado.

B) Dataclasses e validação manual em toda a aplicação.

C) TypedDict/dataclasses com biblioteca de schema diferente de Pydantic.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 5 — Cliente HTTP

Qual cliente deve atender Kakuyomu e o endpoint OpenAI-compatible?

A) HTTPX em modo síncrono, com timeouts explícitos e transporte substituível em testes.

B) Requests, com Session e adapters de teste.

C) `urllib` da biblioteca padrão.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 6 — Qualidade e testes

Qual política mínima deve bloquear regressões?

A) Pytest + Hypothesis; 90% de cobertura de branches no domínio/application e 80% no total.

B) Pytest + Hypothesis; 80% de cobertura total sem meta por camada.

C) Pytest + Hypothesis sem limiar numérico obrigatório na v1.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 7 — Análise estática e estilo

Qual gate deve ser aplicado ao código em inglês?

A) Ruff para lint/format e mypy em modo strict para `src/`.

B) Ruff para lint/format e Pyright em modo strict para `src/`.

C) Ruff para lint/format, sem type checker bloqueante.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Question 8 — Meta de desempenho local

Excluindo rede e tempo do LLM, qual meta deve valer para validação, segmentação e persistência de um capítulo?

A) Até 2 segundos para fontes de até 1 MiB em máquina de desenvolvimento comum.

B) Até 5 segundos para fontes de até 10 MiB em máquina de desenvolvimento comum.

C) Somente ausência de degradação quadrática observável; sem SLA numérico na v1.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: C

## Question 9 — Timeout e retry padrão

Quais defaults devem ser adotados, mantendo tudo configurável?

A) Timeout total de 120 segundos por chamada; até 3 tentativas com backoff exponencial e jitter.

B) Timeout total de 300 segundos por chamada; até 3 tentativas com backoff exponencial e jitter.

C) Timeout total de 120 segundos; sem retry por padrão.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 10 — Concorrência no workspace

Como evitar corrupção quando dois processos operarem sobre o mesmo workspace?

A) Permitir runs paralelos distintos, usando locks apenas para projeções e logs/eventos compartilhados.

B) Aplicar lock exclusivo ao workspace inteiro e permitir somente um processo mutável por vez.

C) Não implementar locking; documentar que concorrência não é suportada.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Question 11 — Retenção e crescimento

Como controlar o crescimento do histórico imutável?

A) Nunca remover automaticamente; limpeza/arquivamento fica fora da v1 e é sempre explícita.

B) Oferecer retenção configurável por idade já na v1.

C) Manter somente os últimos N runs por capítulo.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Question 12 — Observabilidade e automação

Qual saída operacional a CLI deve oferecer?

A) Saída humana por padrão e `--json` estável para outcomes; progresso estruturado vai para stderr e nunca contém segredos.

B) Somente saída humana; automação usa exit codes e arquivos do workspace.

C) JSON por padrão, com opção para saída humana.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 13 — Proteção local dos dados

Qual baseline deve valer além da redação de segredos?

A) Sem autenticação ou criptografia interna; permissões restritivas best-effort, `.env` ignorado e conteúdo sensível omitido por padrão.

B) Criptografar todos os artefatos do workspace na v1.

C) Depender somente das permissões padrão do sistema operacional, sem ajustes best-effort.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 14 — Matriz de plataformas

Como verificar portabilidade?

A) Windows e macOS como gates obrigatórios; Linux best-effort sem suporte oficial.

B) Windows, macOS e Linux como gates obrigatórios.

C) Windows e macOS apenas; Linux explicitamente não suportado.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Cobertura preliminar

- Escalabilidade: tamanho de entrada, crescimento do workspace e concorrência local.
- Desempenho: processamento local, timeout e retry.
- Disponibilidade/confiabilidade: atomicidade, recuperação, locks e ausência de uptime de serviço.
- Segurança: segredo, conteúdo sensível e permissões locais.
- Manutenibilidade: versões, packaging, tipos, lint, testes e documentação.
- Usabilidade: help, mensagens, saída humana/JSON e exit codes.

## Extensões e validação

- Property-Based Testing parcial permanece obrigatório: PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09.
- Security Baseline e Resiliency Baseline permanecem desabilitadas; os NFRs aprovados ainda se aplicam.
- Markdown, 14 perguntas e 14 tags `[Answer]:` foram verificados.
- Não há Mermaid, diagrama ASCII, JSON ou YAML embutido.
