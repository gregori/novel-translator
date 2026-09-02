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

## Desenvolvimento

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```
