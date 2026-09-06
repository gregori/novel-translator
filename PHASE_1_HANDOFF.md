# Handoff — Fase 1 da versão web

## Objetivo concluído

Extração de uma camada de aplicação reutilizável pela CLI e pela futura interface web, conforme `WEB_VERSION_PLAN.md`.

A CLI continua sendo um adaptador de entrada; regras editoriais e orquestração não dependem de Typer, FastAPI ou HTML.

## Estado da entrega

- A implementação foi mergeada em `main` pelo PR
  [#24 — extract cohesive application layers](https://github.com/gregori/novel-translator/pull/24)
  em 6 de setembro de 2026.
- O commit de implementação é `999d89d`
  (`refactor: extract cohesive application layers`).
- A Fase 1 está encerrada; novas alterações devem partir da `main`
  atualizada.

## Arquitetura atual

```text
src/novel_translator/
├── application/
│   ├── approve.py
│   ├── export.py
│   ├── inspect.py
│   ├── review.py
│   └── translate.py
├── domain/
│   ├── errors.py
│   ├── models.py
│   └── translation.py
├── infrastructure/
│   ├── approvals.py
│   ├── export.py
│   ├── filesystem.py
│   ├── providers.py
│   ├── revisions.py
│   ├── run_reader.py
│   ├── runs.py
│   ├── source.py
│   └── workspace.py
├── cli/
│   └── app.py
└── shared/
    └── utils.py
```

Os módulos antigos foram removidos:

- `core.py`
- `editorial.py`
- `providers.py`
- `shared/errors.py`
- `shared/models.py`

## Casos de uso disponíveis

- `ListNovels`
- `ListChapters`
- `GetChapter`
- `StartTranslation`
- `CreateRevision`
- `ListRevisions`
- `GetDiff`
- `ApproveArtifact`
- `RevokeApproval`
- `ExportArtifact`
- `MigrateLegacyDraft`

Todos recebem entradas tipadas e retornam resultados tipados.

## Contratos importantes

### Catálogo

`ListNovels.execute()` retorna `NovelCatalog`.

`ListChapters.execute()` retorna `ChapterCatalog`.

Ambos contêm:

- resultados íntegros;
- `issues` com entradas que não puderam ser indexadas.

Tipos de problema:

```text
foreign
incomplete
corrupt
```

Um run danificado não impede a listagem dos demais.

`ListChaptersInput.novel` é normalizado com `strip()`. Valor vazio lança `ValidationError`.

### Consulta de capítulo

`GetChapterInput` permite selecionar explicitamente:

- run;
- revisão;
- source;
- draft;
- conteúdo da revisão.

Regras:

- source e draft podem ser solicitados junto com uma revisão;
- `include_content=True` exige `revision_id`;
- combinações inválidas lançam `ValidationError`;
- conteúdo permanece opt-in.

### Tradução

`StartTranslation` preserva:

- segmentação;
- retries;
- progresso;
- proveniência dos prompts;
- hashes;
- estados terminais;
- tratamento de interrupções.

O acesso a arquivos, YAML e Kakuyomu está em `infrastructure/source.py`. `domain/translation.py` contém somente modelos e regras puras.

### Workflow editorial

Permanecem inalterados:

- draft original imutável;
- revisões imutáveis;
- parent explícito após a primeira revisão;
- aprovações e revogações append-only;
- aprovação vinculada ao hash exato;
- exportação apenas de artefato aprovado;
- proteção contra colisão de destino;
- migração de drafts legados.

## Configuração de qualidade

`pyproject.toml`:

- Python 3.14;
- Pyright `strict`;
- Ruff com limite efetivo de 79 colunas;
- `E501` habilitado.

## Documentação

- `README.md` descreve a nova arquitetura.
- `REQUIREMENTS.md` preserva a v1 como baseline histórico.
- `WEB_VERSION_PLAN.md` governa a evolução web pós-v1.
- `AGENTS.md` define explicitamente essa precedência.

## Verificação final

```text
pytest:               67 passed
ruff check:           aprovado
ruff format --check:  src e tests formatados
pyright strict:       0 errors, 0 warnings
```

## Próximo passo recomendado

Iniciar a **Fase 2 — catálogo de novels e capítulos**:

1. definir configuração YAML por novel;
2. resolver novel e capítulo sem paths manuais;
3. indexar runs existentes;
4. agregar estado editorial por capítulo;
5. tratar explicitamente múltiplos runs candidatos;
6. ocultar run IDs e hashes do fluxo cotidiano.
