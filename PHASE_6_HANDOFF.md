# Handoff — Fase 6 da versão web (primeira entrega)

## Objetivo concluído

Exportação do Markdown aprovado no servidor (`WEB_VERSION_PLAN.md`,
Fase 6, primeira entrega): a escrita no checkout configurado do
`novels-site` já existia; esta fase adiciona download, visualização e
cópia do artefato aprovado, mais a proveniência da exportação. A
integração com GitHub (branch/commit/PR) fica para a entrega posterior.

## Estado da entrega

- PR #36 (`phase-6-export`): 13 arquivos, +632/−46.
- Revisão adversarial (`@reviewer`) antes do done: veredito FAIL com
  1 blocker e 10 achados, todos resolvidos (detalhes abaixo).
- Gates: `ruff check`, `ruff format --check`, `pytest` full,
  `pyright` — verdes; `node --check` no `app.js`.

## Arquitetura adicionada

```text
application/export.py  # _require_approved/_render compartilhados;
                       # PreviewExport (só aprovados, sem escrever),
                       # ListExportHistory; _publish_date_value privado
infrastructure/exports.py  # events_for_run tolerante a payloads pré-fase-6
domain/models.py           # ExportEvent + git_commit/pull_request_url nulos
web/services.py + app.py   # preview_export, list_export_history no Services
routes/actions.py          # GET export/preview (HTML) e export/download
                           # (attachment, filename do registry)
routes/chapter.py          # last_export com degrade + proveniência nos
                           # detalhes técnicos (hash fora do fluxo cotidiano)
routes/support.py          # export_preview_url/export_download_url
templates/chapter.html     # card Export: View/Download, linha amigável
                           # "Last export · <timestamp>", sem script inline
templates/partials/export_preview.html  # render + raw em .source-text
static/app.js              # wireExportToolbar (data-*), copy delegado,
                           # beforeSwap faz swap de corpos 4xx
```

Decisões estruturais:

- Preview/download passam pelo mesmo `_require_approved` do
  `ExportArtifact`: só artefato aprovado sai; 409/400 viram fragmento
  visível via `beforeSwap` (cura também o Diff legado no mesmo caso).
- Reexportação idêntica reescreve os mesmos bytes e acrescenta um
  evento de proveniência por export (ledger append-only); bytes
  estranhos no destino exigem `overwrite` (`CollisionRequired`, 409).
- `PHASE_5_HANDOFF.md` modificado na árvore NÃO foi commitado: é
  documentação de incidente do usuário, fora do escopo.

## Revisão adversarial (o que quebrou e foi corrigido)

- Blocker: `list_export_history` sem guarda zerava a review room
  (409) com uma linha ilegível no `exports.jsonl`; dashboard/novel
  toleravam o mesmo ledger. Fix: `suppress(NovelTranslatorError)` +
  teste de regressão com ledger `{}\n\n`.
- View silencioso no caminho não-aprovado (htmx descarta 4xx);
  `<pre>` sem wrap quebrava mobile; timestamp fora do filtro
  compartilhado; fallback `001.md` ignorava `filename_template`.
- Nits: docstring da idempotência contradizia o assert; imports no
  topo; teste de proveniência asserta o hash exato no painel técnico.

## Itens abertos (não bloqueiam)

- Entrega posterior da Fase 6: criar branch, commit, abrir PR no
  `novels-site` e preencher `git_commit`/`pull_request_url`.
- Pré-existentes notados pelo reviewer, sem contar como defeito: web
  nunca informa `title`, então artefato sem título inferível morre
  em 400 no preview/download/export; select de export pré-seleciona
  revisão não aprovada quando só o draft está aprovado.
- Teste de restore do backup (herdado da Fase 4).
