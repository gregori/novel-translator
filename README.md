# Novel Translator

CLI local e auditável para traduzir capítulos de web novels do japonês para o inglês. A aplicação mantém runs imutáveis, registra aprovações append-only e exporta Markdown sem publicação automática.

## Instalação

```powershell
uv sync --extra dev
```

## Configuração do provider

O MVP usa o SDK oficial da OpenAI para acessar o endpoint OpenAI-compatible do provider suportado, `opencode-go`. A CLI carrega automaticamente o arquivo `.env` do diretório atual, sem sobrescrever variáveis já exportadas pelo sistema. Copie `.env.example` para `.env` e preencha os valores:

```powershell
Copy-Item .env.example .env
# Edite .env e defina a URL, o modelo e a chave.
```

| Variável | Obrigatória | Finalidade |
|---|---:|---|
| `NOVEL_TRANSLATOR_BASE_URL` | Sim | URL-base do endpoint OpenAI-compatible, incluindo o prefixo necessário, como `/v1`. |
| `NOVEL_TRANSLATOR_MODEL` | Sim | Identificador do modelo enviado ao endpoint. |
| `NOVEL_TRANSLATOR_API_KEY` | Sim | Chave de API enviada como Bearer token; nunca a grave em YAML, commits ou artefatos de run. |

Também é possível informar os mesmos valores diretamente como `--base-url`, `--model` e `--api-key`. `--provider opencode-go` seleciona explicitamente o adapter suportado; outros valores são rejeitados antes da criação do run.

Variáveis já definidas no PowerShell ou no gerenciador de segredos do sistema têm precedência sobre `.env`.

## Uso

```powershell
novel-translator translate --novel minha-novel --chapter 1 --volume 1 --source chapter-ja.txt --bible config/translation-bible.example.yaml --provider opencode-go
novel-translator approve RUN_ID
novel-translator export RUN_ID --destination ../novels-site/src/content/novels/minha-novel/001.md
novel-translator inspect RUN_ID
```

`--volume` é opcional. Quando informado, deve ser inteiro positivo; ele é salvo no `run.json` e incluído como `volume` no front matter do Markdown exportado.

O export usa o título do episódio detectado no draft. Use `--title "Título"` somente para substituí-lo explicitamente. O front matter inclui `publishDate` com a data da exportação; use `--publish-date YYYY-MM-DD` para informar a data original do capítulo. O `draft.md` permanece o texto cru da tradução; o front matter é criado apenas no arquivo exportado.

Durante a tradução, a CLI informa o segmento e a tentativa em andamento. Por padrão, um capítulo de até 60.000 caracteres é enviado em uma única chamada. Capítulos maiores são divididos por parágrafos; cada segmento posterior recebe os últimos 12.000 caracteres da tradução anterior somente como contexto de continuidade. Ajuste o limite com `--segment-limit CARACTERES`. Cada chamada ao provedor tem um prazo total de 90 segundos por padrão; ajuste-o com `--request-timeout SEGUNDOS`.

## Proveniência dos prompts

Runs novos usam `schema_version: 2`. Runs antigos, sem esse campo, continuam
legíveis e preservam o significado legado de `prompt_hash`.

No schema v2, os hashes SHA-256 usam os bytes UTF-8 exatos:

- `source_hash`: source normalizado completo salvo em `source.txt`;
- `bible_hash`: JSON emitido pelo Pydantic para a translation bible validada;
- `prompt_template_hash`: template estático identificado por `prompt_template_version`;
- `context_hash`: contexto renderizado da translation bible;
- `source_segment_hash`: source exato do segmento;
- `continuity_context_hash`: bloco de continuidade exato, incluindo a instrução;
- `rendered_prompt_hash`: prompt completo enviado ao gateway;
- `prompt_hash`: digest da lista JSON compacta e ordenada de `rendered_prompt_hash`.

`prompt_version` é mantido como alias de compatibilidade de
`prompt_template_version`. No primeiro segmento, o contexto de continuidade é a
string vazia.

`segment_manifest` preserva a ordem e `gateway_calls` registra cada tentativa com
seu `rendered_prompt_hash`. O `run.json` armazena apenas hashes e metadados nesse
manifesto, sem duplicar conteúdo sensível.

## Desenvolvimento

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```
