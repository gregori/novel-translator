# Operação — Novel Translator no k3s da OCI

Este documento descreve como subir, proteger e restaurar a sala de
revisão no mesmo nó k3s que já roda o dojo-full. Segue o padrão do
`dojo-infra`: imagens na OCIR, manifests aplicados por SSH com
`sudo k3s kubectl` e Ingress Traefik com TLS do cert-manager.

## Arquitetura

- 1 `Deployment` com `replicas: 1`. Réplica única é obrigatória:
  SQLite WAL e filelocks do workspace não suportam horizontal.
- 1 `PVC` `local-path` de 5Gi montado em `/data` (runs, editorial,
  `working-copies.sqlite`). Configuração (`novels.yaml`, `config/`,
  `novel-sources/`) vai assada na imagem; estado mutável fica no PVC.
- Sem `NOVEL_TRANSLATOR_SITE_ROOT` no cluster: a exportação fica
  desabilitada (o botão retorna 400 orientando). Publicação no
  `novels-site` continua manual até a Fase 6 (bot com Deploy Key
  abrindo PR, nunca push direto).
- Tradução continua pela CLI nesta fase; o worker persistente chega na
  Fase 5. Como a CLI roda contra o workspace local e a sala lê `/data`
  no PVC, é preciso semear o PVC (ver “Semeando runs” abaixo); a partir
  daí o PVC é a cópia autoritativa.

## Proteção de acesso

Ao contrário do dojo (Ingress público sem auth), esta sala fica atrás de
basicAuth do Traefik (`middleware.yaml`), porque qualquer pessoa com a
URL poderia aprovar e exportar capítulos. Por isso, além do basicAuth:

- POST/PUT/PATCH/DELETE com `Origin`/`Referer` de outro host recebem
  403 (as credenciais de basic-auth seriam reenviadas sozinhas pelo
  navegador num ataque CSRF);
- sem cookies de sessão, sem docs automáticos (`docs_url` desligado).

Gere o htpasswd e guarde no secret `BASIC_AUTH_PASSWD`:

```bash
htpasswd -nbB reviewer 'sua-senha-forte'
```

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
| `NOVEL_TRANSLATOR_BASE_URL` | endpoint do provider LLM |
| `NOVEL_TRANSLATOR_MODEL` | modelo configurado |
| `NOVEL_TRANSLATOR_API_KEY` | chave do provider (só no servidor) |
| `BASIC_AUTH_PASSWD` | linha `reviewer:$apr1$...` do `htpasswd` acima |
| `INGRESS_HOST` | ex. `novels.gregori.eti.br` (apontar o DNS ao nó) |

## Primeiro deploy

1. Apontar `INGRESS_HOST` no DNS para o IP público do nó.
2. Cadastrar os secrets acima no GitHub.
3. Push na `main` (ou `workflow_dispatch` em `CD - Deploy Web`).
4. Abrir `https://<INGRESS_HOST>/healthz` — deve responder `ok` após o
   basicAuth.

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

Volte a 1 réplica e confira o dashboard. Depois disso, traduza pela CLI
e repita o envio, ou rode a CLI com o workspace apontando para uma cópia
sincronizada — o PVC é a cópia autoritativa da sala.

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
