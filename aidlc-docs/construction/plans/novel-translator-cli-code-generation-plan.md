# Plano de geração de código — novel-translator-cli

## 1. Fonte de verdade e contexto da unidade

Este é o plano único e executável para a geração de código da unidade `novel-translator-cli`. O código ficará exclusivamente na raiz do workspace, em `src/`, `tests/`, `config/` e nos arquivos de configuração do projeto; os resumos desta etapa ficarão em `aidlc-docs/construction/novel-translator-cli/code/`.

| Item | Decisão |
|---|---|
| Tipo | Package Python instalável com CLI local |
| Layout | `src/novel_translator/` e `tests/` |
| Dependências de outras units | Nenhuma |
| Integrações | filesystem local, HTTP/Kakuyomu, endpoint OpenAI-compatible do OpenCode Go e checkout local do `novels-site` |
| Banco de dados | Nenhum; artefatos, eventos e projeções em filesystem |
| Fronteira | `CompositionRoot` é o único local que conhece adapters concretos |

As interfaces seguem o fluxo `cli -> application -> domain/ports <- adapters`. YAML, TOML, JSON, HTTP e argumentos da CLI são convertidos nas bordas. Código, nomes e docstrings serão em inglês; esta documentação será em português.

## 2. Cobertura de stories

| Grupo | Stories |
|---|---|
| Fundação e operação da CLI | US-001, US-002, US-003, US-004 |
| Fonte, bible e tradução | US-005, US-006, US-007, US-008, US-009, US-010 |
| Workspace, aprovação e exportação | US-011, US-012, US-013, US-014, US-015, US-016, US-017, US-018 |
| Qualidade transversal | US-019 |

## 3. Sequência executável

- [x] **Step 1 — Criar a fundação do projeto.** Criar `pyproject.toml`, `README.md`, `src/novel_translator/`, `tests/`, `config/` e o entry point Typer. Configurar Python 3.14, Hatchling, dependências de runtime e desenvolvimento, Ruff, Pyright strict e Pytest/Hypothesis. Cobertura: US-001, US-019.
- [x] **Step 2 — Implementar núcleo compartilhado e contratos.** Criar tipos imutáveis, erros, outcomes, configuração tipada, portas para relógio/IDs/hashing/lock/filesystem/HTTP/provider e utilitários de serialização segura. Cobertura: US-001, US-019.
- [x] **Step 3 — Implementar segurança e lifecycle do workspace.** Criar resolução segura de caminhos, rejeição de symlinks/junctions, lock exclusivo fail-fast, escrita atômica, criação imutável de runs, `run.json`, hashes, status e projeção de draft atual. Cobertura: US-002, US-003, US-011, US-019.
- [x] **Step 4 — Testar fundação e workspace.** Criar testes unitários e de propriedade para identidade, hashes, serialização, regras de path, imutabilidade, lock e recuperação de escrita. Cobertura: US-002, US-003, US-011, US-019; PBT-02, PBT-03 e PBT-07.
- [x] **Step 5 — Implementar aquisição de fonte.** Criar modelos de proveniência, reader UTF-8 local, cliente HTTP com timeout/retry e reader Kakuyomu; preservar a identidade canônica e metadados extraídos. Cobertura: US-004, US-005, US-019.
- [x] **Step 6 — Implementar bible e preparação de tradução.** Criar schema Pydantic da translation bible, validação YAML, normalização, contexto determinístico, segmentação por parágrafo/sentença e resumo de continuidade local. Cobertura: US-006, US-007, US-008, US-019.
- [x] **Step 7 — Implementar provider e caso de uso de tradução.** Criar gateway OpenAI-compatible configurável para OpenCode Go, estimador conservador de tokens, prompt versionado, chunking incremental, três tentativas com timeout de 120 segundos, redaction centralizada e persistência do draft/rastreabilidade. Cobertura: US-009, US-010, US-011, US-019.
- [x] **Step 8 — Testar fonte e tradução.** Criar testes unitários, de contrato com transporte HTTP falso e de propriedade para validação, segmentação, reconstrução, contexto, chunking, retry e redaction. Cobertura: US-004 a US-011, US-019; PBT-02, PBT-03, PBT-08 e PBT-09.
- [x] **Step 9 — Implementar domínio editorial.** Criar manifesto editorial YAML, eventos de aprovação append-only, projeção pelo último evento para `run_id + draft_hash`, regras de elegibilidade, precedência de volume e plano de exportação. Cobertura: US-012, US-013, US-014, US-015, US-019.
- [x] **Step 10 — Implementar exportação segura.** Criar renderização Markdown compatível com `gregori/novels-site`, pré-voo de colisões, uma confirmação para o conjunto total, escrita compensável/atômica e ausência de publicação automática. Cobertura: US-016, US-017, US-018, US-019.
- [x] **Step 11 — Testar editorial e exportação.** Criar testes unitários, integração de filesystem isolado e propriedades para histórico, elegibilidade, precedência, renderização, colisões e rollback. Cobertura: US-012 a US-018, US-019; PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09.
- [x] **Step 12 — Implementar a CLI e o composition root.** Conectar adapters e casos de uso no `composition.py`; implementar comandos `translate`, `approve`, `export` e `inspect`, saída humana/JSON, mensagens redigidas e exit codes estáveis. Cobertura: US-001 a US-018.
- [x] **Step 13 — Testar a CLI ponta a ponta.** Criar testes de CLI para argumentos, saída humana/JSON, erros, confirmação de exportação e workflow local com provider falso. Cobertura: US-001 a US-018, US-019.
- [x] **Step 14 — Adicionar exemplos e documentação de uso.** Completar `README.md`, incluir exemplos de configuração e fixtures de bible/capítulo sem segredos, e documentar instalação, comandos, workspace, aprovação e exportação. Cobertura: US-001, US-006, US-011 a US-018.
- [x] **Step 15 — Validar a entrega e registrar o resumo.** Executar lint, análise estática e a suíte de testes; verificar cobertura das 19 stories, Windows/macOS por compatibilidade de implementação e criar resumos Markdown em `aidlc-docs/construction/novel-translator-cli/code/`. Cobertura: US-001 a US-019.
- [x] **Step 16 — Implementar volume por capítulo.** Aceitar `--volume` em `translate`, persistir o valor no metadata do run, renderizá-lo no Markdown exportado, documentar e testar a regra. Cobertura: US-016, US-019.
- [x] **Step 17 — Carregar provider por .env.** Adicionar carregamento seguro de `.env`, exemplo versionável, proteção no `.gitignore`, documentação e teste de precedência de ambiente. Cobertura: US-001, US-019.

## 4. Critérios de conclusão

- Todos os passos acima estarão marcados como concluídos na mesma interação em que forem executados.
- A aplicação terá código e testes no workspace, sem código de aplicação em `aidlc-docs/`.
- As 19 stories e as regras PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09 terão rastreabilidade verificável.
- Segurança e resiliência baselines estão desabilitadas por decisão registrada; as exigências funcionais e NFR aprovadas continuam obrigatórias.
