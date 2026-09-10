# Operação — Novel Translator no k3s da OCI

Este documento descreve como subir, proteger e restaurar a sala de
revisão no mesmo nó k3s que já roda o dojo-full. Segue o padrão do
`dojo-infra`: imagens na OCIR, manifests aplicados por SSH com
`sudo k3s kubectl` e Ingress Traefik com TLS do cert-manager.

## Arquitetura

- 1 `Deployment` com `replicas: 1` e 2 containers no mesmo Pod:
  `web` (FastAPI) e `worker` (`novel-translator-worker`). Réplica única
  é obrigatória: SQLite WAL e filelocks do workspace não suportam
  horizontal; os dois containers dividem o mesmo `/data` e o mesmo
  banco, com sessões curtas e reserva atômica de jobs.
- 1 `PVC` `local-path` de 5Gi montado em `/data` (runs, editorial,
  `working-copies.sqlite`). Configuração (`novels.yaml`, `config/`,
  `novel-sources/`) vai assada na imagem; estado mutável fica no PVC.
- Sem `NOVEL_TRANSLATOR_SITE_ROOT` no cluster: a exportação direta em
  checkout fica desabilitada (o botão retorna 400 orientando).
  A publicação é o card `Publish` da página do capítulo: abre um pull
  request no `novels-site` com o Markdown aprovado (branch
  `novel-translator/<novel>-ch<cap>-<hash>`, nunca push direto).
  Download/View/Copy continuam manuais e sem checkout.
- Traduções partem da página `/translate`: o `web` enfileira um job
  persistente e o `worker` executa o caso de uso `StartTranslation`.
  Fechar o navegador não interrompe; a página do job atualiza por
  polling HTMX. Como o PVC é a cópia autoritativa, semear o PVC
  continua necessário uma vez (ver “Semeando runs” abaixo).

## Proteção de acesso

Sem basicAuth do Traefik: a sala tem login próprio, de senha única,
em página mobile-friendly (`/login`), com sessão em cookie assinado
(HMAC-SHA256, 30 dias, `HttpOnly`, `SameSite=Lax`, `Secure` sob
HTTPS) e botão de saída no topo. Por isso, além do login:

- POST/PUT/PATCH/DELETE com `Origin`/`Referer` de outro host recebem
  403 (o cookie de sessão seria reenviado sozinho pelo navegador num
  ataque CSRF);
- sem docs automáticos (`docs_url` desligado);
- `/healthz` continua público para as probes do Kubernetes;
- após 10 senhas erradas em 5 minutos o IP recebe 429.

Gere o hash da senha e o segredo de sessão e guarde nos secrets
`NOVEL_TRANSLATOR_AUTH_PASSWORD_HASH` e
`NOVEL_TRANSLATOR_SESSION_SECRET`:

```bash
python -c "from getpass import getpass; from novel_translator.web.auth import hash_password; print(hash_password(getpass()))"
python -c "import secrets; print(secrets.token_hex(32))"
```

Sem essas duas variáveis a sala abre sem login (modo dev local).
No cluster elas são obrigatórias. Trocar o `session-secret`
desconecta todos os navegadores.


## Secrets do GitHub (repositório `gregori/novel-translator`)

Reusar os mesmos valores do dojo onde indicado:

| Secret | Origem |
|---|---|
| `K8S_NODE_PUBLIC_IP` | mesmo do dojo |
| `OCI_SSH_PRIVATE_KEY` | mesmo do dojo |
| `OCI_REGISTRY` | mesmo do dojo (`sa-saopaulo-1.ocir.io`) |
| `OCI_REGISTRY_USERNAME` | mesmo do dojo |
| `OCI_REGISTRY_PASSWORD` | mesmo do dojo |
| `OCI_TENANCY_NAMESPACE` | mesmo do dojo |
| `NOVEL_TRANSLATOR_BASE_URL` | endpoint do provider LLM (alcançável de dentro do cluster; `localhost` não serve) |
| `NOVEL_TRANSLATOR_MODEL` | modelo configurado |
| `NOVEL_TRANSLATOR_API_KEY` | chave do provider (só no servidor) |
| `NOVEL_TRANSLATOR_AUTH_PASSWORD_HASH` | hash scrypt da senha (`hash_password`) |
| `NOVEL_TRANSLATOR_SESSION_SECRET` | 32+ chars aleatórios (ex. `secrets.token_hex(32)`) |
| `NOVEL_TRANSLATOR_GITHUB_TOKEN` | token fino no `gregori/novels-site` (Contents:write, Pull requests:write) |
| `INGRESS_HOST` | ex. `novels.gregori.eti.br` (apontar o DNS ao nó) |

## Primeiro deploy

1. Apontar `INGRESS_HOST` no DNS para o IP público do nó.
2. Cadastrar os secrets acima no GitHub.
3. Push na `main` (ou `workflow_dispatch` em `CD - Deploy Web`).
4. Abrir `https://<INGRESS_HOST>/login` — após o login, o dashboard
   mostra a sala; `/healthz` responde `ok` sem login (probes).

## Semeando runs

No primeiro deploy o PVC está vazio: a CLI traduz contra o workspace
local, a sala lê `/data` no cluster. Envie o workspace local uma vez
com o mesmo Pod descartável do backup, em sentido inverso (com o
Deployment em zero réplicas):

```bash
tar czf - -C .novel-translator . | sudo k3s kubectl run seed-copy --rm -i \
  --restart=Never -n novel-translator --image=busybox:1.36 \
  --overrides='{"spec":{"volumes":[{"name":"workspace","persistentVolumeClaim":{"claimName":"novel-translator-data"}}],"containers":[{"name":"seed-copy","image":"busybox:1.36","stdin":true,"command":["tar","xzf","-","-C","/data"],"volumeMounts":[{"name":"workspace","mountPath":"/data"}]}]}}'
```

Volte a 1 réplica e confira o dashboard. Depois disso, prefira traduzir
pela página `/translate` da própria sala — o worker escreve direto no
PVC, sem nova semeadura. A CLI continua servindo para operação local;
nesse caso repita o envio acima (o PVC segue autoritativo).

## Publicação

Aprovar a revisão, abrir o card `Publish` e confirmar: o servidor cria
a branch, escreve o Markdown e abre o PR, mostrando o link na página
(`Last pull request`). Reexportar o mesmo conteúdo reaproveita o PR
aberto; se o arquivo-base já tem os bytes exatos, nada é criado.
Falha no GitHub não revoga a aprovação (502 orientando, tente de novo).
O merge continua manual no `novels-site`.

## Backup e restore

Backup: `deploy/scripts/backup.sh <bucket> <os-namespace>` no nó.
Ele zera as réplicas (SQLite não pode ser copiado sob escrita), copia
`/data` via Pod descartável, sobre o Deployment e envia o tarball ao
Object Storage.

Restore em ambiente limpo:

1. Aplicar os manifests (`deploy/k8s/`) e subir o Deployment uma vez
   para criar o PVC.
2. Zerar as réplicas.
3. Descompactar o tarball no PVC via Pod descartável (caminho inverso
   do script de backup).
4. Voltar a 1 réplica e conferir dashboard, working copies e diff de
   uma revisão aprovada.

Testar o restore de verdade — backup sem restore testado não conta
como critério de aceite da Fase 4.
