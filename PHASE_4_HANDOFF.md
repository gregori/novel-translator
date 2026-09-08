# Handoff — Fase 4 da versão web

## Objetivo concluído

Operação remota e segura da sala de revisão no k3s Always Free da OCI
(o mesmo nó do dojo-full), seguindo `WEB_VERSION_PLAN.md`, mais a
revisão lado a lado pedida antes do aceite.

## Estado da entrega

- PR [#28](https://github.com/gregori/novel-translator/pull/28) (mergeado):
  Fase 4 inicial + split da interface.
- PR [#29](https://github.com/gregori/novel-translator/pull/29) (mergeado,
  correção direta no `main`): chave `script:` faltando no step de apply.
- PR [#30](https://github.com/gregori/novel-translator/pull/30) (mergeado):
  delta pós-review — sync via scp, guards, nome do secret, tags,
  rollout único, redirect http→https.
- Revisão adversarial (`@reviewer`) executada antes do commit: 4 blockers
  corrigidos, 13 sugestões acatadas, 1 divergência deliberada (abaixo).

## Arquitetura adicionada

```text
Dockerfile                    # python:3.14-slim, non-root 10001, deps do uv.lock
deploy/k8s/                   # namespace, pvc local-path 5Gi, deployment,
                              # service, middleware basicAuth+redirect,
                              # ingress Traefik TLS, kustomization
.github/workflows/cd-web.yml # build amd64+arm64 → OCIR, deploy via SSH+SCP
deploy/scripts/backup.sh      # quiesce + tar do PVC + oci os put
deploy/README.md              # runbook: secrets, seed, backup/restore
src/novel_translator/web/app.py  # GET /healthz + middleware de Origin
```

Decisões estruturais:

- Réplica 1 + `strategy: Recreate`: SQLite WAL e filelocks não admitem
  dois escritores nem por segundos (o RollingUpdate padrão sobrepunha).
- Sem `NOVEL_TRANSLATOR_SITE_ROOT` no cluster: exportação desabilitada
  (400 orientando). Publicação no `novels-site` continua manual até a
  Fase 6. Separação tradução/publicação preservada.
- Tradução continua pela CLI; worker persistente chega na Fase 5.
- Ingress com basicAuth do Traefik (o dojo é público sem auth; aqui
  qualquer visitante poderia aprovar/exportar) + redirect http→https.
- Divergência deliberada do review: mantido o `display:block` do painel
  de source no CSS como guarda contra `app.js` em cache (incidente real
  na sessão), com comentário ancorando o motivo.

## Interface: revisão lado a lado

- Em telas ≥50rem, Edit/Preview exibem o source japonês ao lado em grade
  2 colunas, rolagem única da página; `.shell` alarga só no split
  (72rem/110rem via `:has`), demais páginas mantêm a medida editorial.
- Estreito inalterado (abas exclusivas). `aria-selected` acompanha os
  painéis visíveis; mudança de viewport re-sincroniza sem rolar a página.
- Verificado em navegador real (390/1050/1440/1920px).

## Operação (estado real do cluster)

- Host: `novels.gregori.eti.br` (A → 64.181.185.18), TLS letsencrypt-prod
  emitido após fix de hairpin (abaixo). Secrets no repo (nomes exatos):
  `K8S_NODE_PUBLIC_IP`, `OCI_SSH_PRIVATE_KEY`, `OCI_REGISTRY`,
  `OCI_REGISTRY_USERNAME`, `OCI_REGISTRY_PASSWORD`,
  `OCI_TENANCY_NAMESPACE`, `NOVEL_TRANSLATOR_BASE_URL/MODEL/API_KEY`,
  `BASIC_AUTH_PASSWD` (linha `usuario:hash`, não só o hash),
  `INGRESS_HOST`.
- PVC semeado a partir do workspace local (sleeper + `cp` + `exec`;
  o PVC é a cópia autoritativa a partir daí).
- Pendente do aceite: **teste de restore** do backup em ambiente limpo.

## Aprendizados da sessão (operacionais)

1. `appleboy/ssh-action` sem `set -e`/`pipefail` reporta sucesso com
   comandos falhados no meio do script (caso real: clone falhou, apply
   vazio, step verde). Sempre `set -o pipefail`.
2. `--from-literal="...${{ secrets.X }}"` com aspas duplas destrói
   valores com `$` (hash bcrypt, tokens) por expansão do bash remoto.
   Aspas simples em todos.
3. `kubectl run --overrides` usa merge patch: o array `containers` do
   override substitui o gerado — o nome do container, `stdin` e
   `command` precisam estar no override, senão o busybox sai 0 sem
   fazer nada (tarball vazio enviado como sucesso).
4. Script com `scale --replicas=0` exige `trap EXIT` restaurando
   réplicas + `test -s` no artefato antes do upload.
5. Rollout único e declarativo: renderizar a tag do SHA no `sed`,
   nunca `apply :latest` + `set image` (dois rollouts, dois pods
   escritores, estado declarado divergente).
6. Nó sem `git`: checkout no runner + `scp-action` (padrão original
   do dojo), nunca clone no nó. Retry reexecuta código antigo;
   testar fix exige novo dispatch na branch.
7. Erro `tag is needed`: conferir o bloco `tags:` no YAML (edição o
   removeu silenciosamente) antes de culpar os secrets; guarda
   fail-fast para secrets vazios incluída no workflow.
8. `iptables` no nó é cego para regras nftables nativas (`nft list
   ruleset` é a fonte verdadeira; CNI-HOSTPORT-DNAT, redirects).
9. Self-check HTTP-01 do cert-manager falha por hairpin NAT neste nó
   (`dial ...:80: connection refused` só de dentro dos pods). Fix
   herdado do dojo: entrada NodeHosts no ConfigMap do CoreDNS
   apontando o domínio ao ClusterIP do Traefik (só intra-cluster),
   restart do coredns, deletar o challenge. Sem isso, sem certificado.
10. Valor do basic-auth tem que ser a linha `usuario:hash`; sem o
    prefixo o Traefik derruba o router inteiro (404 em tudo, 401
    invisível no log mascarado). Traefik sem middleware válido =
    404, não 500 — debugar pelo log do Traefik, não pelo app.
11. Seed/restore via `kubectl run -i` com stdin sofre timeout de attach
    (pod fica `Running` com `tar` bloqueado). Padrão robusto: pod
    sleeper + `kubectl cp` + `kubectl exec`, com comandos separados
    por poda descartável.
12. Runbook precisa dizer **onde** cada comando roda (nó vs máquina
    local) — `k3s`/`oci` só existem no nó; `scp` parte do local.
13. Cache de `app.js`/`app.css` no navegador quebra deploys de UI:
    orientar Ctrl+F5; manter guarda dupla JS+CSS em transições.
14. Testes de template: parsing de atributos, nunca substring
    (`hidden` anterior ao alvo quebra a asserção por motivo alheio).

## Itens abertos (não bloqueiam o merge)

- Teste de restore do backup (último item do aceite da Fase 4).
- Instalar/configurar a OCI CLI no nó (`backup.sh` a pressupõe;
  hoje ela não existe lá).
- Reteste do aviso "não seguro" no Mac após reboot.
- Ergonomia do basicAuth (sessão/Cloudflare Access) se incomodar.
- Próximo passo recomendado: Fase 5 (jobs persistentes, tradução pela
  web) — exige endpoint de LLM alcançável do cluster (o `localhost`
  do `.env` local não serve).
