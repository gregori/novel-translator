# Handoff — Fase 5 da versão web

## Objetivo concluído

Tradução iniciada e acompanhada pela web (`WEB_VERSION_PLAN.md`, Fase 5),
mais a troca pedida do basic-auth por um login próprio simples: senha
única em página mobile-friendly, sessão em cookie assinado, saída real.

## Estado da entrega

- Slices paralelos (`AuthSlice`, `JobsSlice`) + wiring do integrador.
- Revisão adversarial (`@reviewer`) antes do done: 4 blockers corrigidos
  (gate fail-open, transições sem guarda, cookie sem `Secure` atrás do
  Traefik, throttle na IP do proxy), 11 sugestões acatadas.
- Gates: `ruff check`, `ruff format --check`, `pytest` (176), `pyright`
  verdes; verificado em navegador real a 390px (form, navegação, logout).

## Arquitetura adicionada

```text
web/auth.py + routes/auth.py + login.html  # senha única (scrypt stdlib),
                                           # cookie HMAC 30d, throttle 10/5min
application/jobs.py (porta)                # Enqueue/Get/List/Cancel/Retry
infrastructure/jobs.py + migração 0002     # transições vigiadas por status,
                                           # source_text deferred em listagens
worker.py (novel-translator-worker)        # claim atômico, heartbeat, cancel
                                           # cooperativo, recover de stale
routes/translate.py + templates            # form, jobs, job (poll HTMX 2s),
                                           # detalhe técnico recolhido
deploy/k8s/deployment.yaml                 # 2 containers no mesmo Pod (web+worker)
deploy: ingress sem basicAuth, CD verifica secrets de auth
```

Decisões estruturais:

- Sem dependências novas: scrypt/HMAC via stdlib, sem itsdangerous.
- Sem login configurado a sala abre direto (dev local); meio
  configurado recusa subir (`ValueError`); CD falha sem os secrets.
- `uvicorn` com `forwarded_allow_ips="*"` (só alcançável via ingress):
  sem isso o cookie perdia `Secure` e o throttle enxergava um IP só.
- Migração sob filelock cross-process: web e worker sobem juntos.
- Enqueue rejeita capítulo com job ativo (duplo tap no celular).
- Retry cria job filho com `parent_job_id` e `attempt + 1`.
- Polling HTMX troca status + ações juntos; sem trigger no terminal.
- `Services` expõe só casos de uso, nunca o repositório.

## Pós-deploy (incidente do capítulo 35)

- Job falhou 3x em `TransientProviderError` com causa invisível.
- Diagnóstico: egresso ok, chave/modelo ok (chamada curta no pod
  respondeu `ok`); capítulo longo estourava o budget por tentativa.
- Fix #34: `NOVEL_TRANSLATOR_REQUEST_TIMEOUT` configurável + log de
  cada retry no `kubectl logs -c worker`.
- Fix #35: default 300s → 1200s (valor local comprovado).
- `NOVEL_TRANSLATOR_BASE_URL` precisa ser alcançável de dentro do
  cluster (`localhost` não serve) — o worker traduz lá dentro.
- Rollout mantém `strategy: Recreate`; `/healthz` segue público.

## Itens abertos (não bloqueiam)

- Teste de restore do backup (herdado da Fase 4).
- OCI CLI no nó para `backup.sh`.
- Próximo: Fase 6 (exportação/publicação via GitHub).
