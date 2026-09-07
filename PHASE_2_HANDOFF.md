# Handoff — Fase 2 da versão web

## Objetivo concluído

Implementação do catálogo de novels e capítulos definido em
`WEB_VERSION_PLAN.md`.

A CLI agora resolve novels, capítulos, sources, runs e destinos de exportação
a partir de configuração versionada, sem exigir paths, hashes ou run IDs no
fluxo editorial cotidiano.

## Estado da entrega

- A implementação foi mergeada em `main` pelo PR
  [#25 — Phase 2: add novel catalog workflow](https://github.com/gregori/novel-translator/pull/25)
  em 6 de setembro de 2026.
- O commit de implementação é `613900d`
  (`feat: add Phase 2 novel catalog workflow`).
- O merge commit é `3f1e9ed9a3d7a9791323f7d9aafb441417711782`.
- A Fase 2 está encerrada; novas alterações devem partir da `main`
  atualizada.

## Arquitetura adicionada

```text
novels.yaml
src/novel_translator/
├── application/
│   ├── catalog.py
│   └── prepare.py
├── domain/
│   └── models.py
├── infrastructure/
│   ├── catalog.py
│   └── exports.py
└── cli/
    └── app.py
```

Responsabilidades:

- `infrastructure/catalog.py`: validação do YAML, resolução de paths,
  descoberta de sources e composição de URLs do Kakuyomu;
- `application/catalog.py`: indexação dos runs, agregação dos capítulos e
  resolução amigável de ambiguidades;
- `application/prepare.py`: aplicação de defaults e overrides antes de criar
  um novo run de tradução;
- `infrastructure/exports.py`: proveniência append-only das exportações;
- `cli/app.py`: comandos de catálogo e adaptação dos comandos editoriais para
  seleção por novel, capítulo e ordinal.

## Configuração por novel

O arquivo `novels.yaml` é a fonte versionada para:

- identificador e título da novel;
- translation bible;
- diretório de sources;
- aliases de identidades históricas dos runs;
- raiz de episódios do Kakuyomu;
- repositório, diretório e template de nome para exportação;
- provider, modelo e volume padrão.

Exemplo do contrato:

```yaml
novels:
  gariben:
    title: The Studious Boy and the Secret Account Girl
    bible: config/gariben.translation-bible.yaml
    source_directory: novel-sources/gariben-kun-to-uraaka-san
    run_aliases:
      - gariben-kun-to-uraaka-san
    kakuyomu_episode_root: https://kakuyomu.jp/works/16816452220316242482/episodes
    export:
      repository: gregori/novels-site
      directory: src/content/novels/gariben
      filename_template: "{chapter:03}.md"
    translation:
      provider: opencode-go
      model: glm-5.3-flash
      default_volume: 3
```

Regras importantes:

- campos desconhecidos são rejeitados;
- identificadores devem ser estáveis, únicos e compatíveis com CLI/URL;
- paths configurados são resolvidos em relação ao catálogo;
- `export.directory` deve ser relativo e não pode conter `..`;
- o checkout de publicação não é armazenado no catálogo;
- `--site-root` ou `NOVEL_TRANSLATOR_SITE_ROOT` deve apontar para um diretório
  existente;
- `kakuyomu_episode_root` aceita somente a raiz canônica de uma obra;
- segredos permanecem fora do YAML, em ambiente ou secret store.

## Casos de uso adicionados

- `ListNovels`
- `ListChapters`
- `ResolveChapter`
- `PrepareTranslation`

Principais tipos de retorno:

- `NovelCatalog` e `NovelSummary`;
- `ChapterCatalog` e `ChapterSummary`;
- `ResolvedChapter`;
- `RunChoice` e `SourceChoice`;
- `PreparedTranslation`.

Todos usam entradas e resultados tipados, sem dependência de Typer.

## Estados agregados por capítulo

```text
no_source
ready
translating
draft_available
in_review
approved
exported
failed
```

O estado representa a situação persistida mais acionável entre source, run e
workflow editorial. `exported` é um fato histórico: revogar uma aprovação
posteriormente não apaga a exportação já registrada.

## Indexação e isolamento de falhas

A listagem preserva entradas saudáveis mesmo quando outras entradas do
workspace estão inválidas. Problemas são retornados como `RunEntryIssue`:

```text
foreign
incomplete
corrupt
orphan
editorial
```

Significados:

- `foreign`: nome da entrada fora do padrão de run;
- `incomplete`: diretório sem `run.json`;
- `corrupt`: metadados do run inválidos;
- `orphan`: run íntegro sem novel ou alias registrado;
- `editorial`: run íntegro cujo ledger editorial não pôde ser projetado.

Danos editoriais não escondem o run nem redefinem seu estado de tradução.
Aprovações, revisões e exportações são projetadas por ledger em uma passagem,
em vez de reler os arquivos para cada run.

## Resolução amigável

Fluxo normal:

```powershell
novel-translator novels
novel-translator chapters gariben
novel-translator inspect --novel gariben --chapter 29
novel-translator approve --novel gariben --chapter 29
novel-translator export --novel gariben --chapter 29 --site-root ../novels-site
```

Contratos:

- run IDs completos permanecem ocultos nas listagens normais;
- um único candidato pode ser resolvido automaticamente;
- múltiplos runs válidos exigem `--run-choice N`;
- o ordinal corresponde exatamente à ordem mostrada por `chapters`;
- nenhuma ambiguidade escolhe um run silenciosamente;
- `RUN_ID` explícito continua disponível para operação técnica.

## Preparação de novas traduções

Criar uma tradução é independente dos runs existentes. Portanto, `translate`
não exige `--run-choice` mesmo quando o capítulo já possui múltiplos runs.

Precedência:

1. overrides explícitos da CLI;
2. defaults registrados em `novels.yaml`.

Source:

- `--source` explícito ignora ambiguidades do diretório configurado;
- sem `--source`, um único `chapter-N.md` ou `chapter-N.txt` é usado;
- múltiplos sources exigem escolha ordinal;
- ausência de source exige entrada explícita;
- `--episode ID` compõe a URL usando `kakuyomu_episode_root`;
- `--episode` aceita somente ID numérico e é incompatível com `--source`.

O provider é validado antes da criação do workspace ou do run.

## Proveniência de exportação

Exportações concluídas são registradas em:

```text
workspace/editorial/exports.jsonl
```

Cada evento contém:

- run;
- tipo e identificador do artefato;
- hash exato do conteúdo;
- destino;
- instante da exportação.

O registro ocorre somente após a escrita bem-sucedida do destino. O ledger é
append-only e permite reconstruir o estado `exported` sem depender da aprovação
corrente.

## Compatibilidade e cutover

- Commands editoriais aceitam novel e capítulo como caminho principal.
- Seleção técnica por run ID continua suportada explicitamente.
- `run_aliases` associa runs históricos à chave atual da novel sem alterar
  seus metadados imutáveis.
- Exportação configurada exige checkout externo explícito; nenhuma árvore de
  publicação é criada silenciosamente.
- A separação entre tradução e publicação definida em `REQUIREMENTS.md`
  permanece preservada.

## Verificação final

```text
pytest:               81 passed
ruff check:           aprovado
ruff format --check:  40 arquivos formatados
pyright strict:       0 errors, 0 warnings
```

Cobertura relevante inclui:

- catálogo sem runs prévios;
- escolha obrigatória entre múltiplos runs;
- estabilidade dos ordinais apresentados;
- todos os estados do workflow editorial;
- exportação histórica após revogação;
- isolamento de runs e ledgers inválidos;
- preparação de tradução sem escolher run existente;
- precedência de overrides;
- composição e validação de episódios do Kakuyomu;
- destino de exportação dentro de checkout explícito;
- workflow CLI completo de tradução, aprovação, exportação e inspeção.

## Próximo passo recomendado

Iniciar a **Fase 3 — Web MVP de leitura e revisão**:

1. criar o dashboard com novels, capítulos recentes e estados agregados;
2. criar a página da novel com busca e filtros;
3. criar a página do capítulo com source, draft, preview e histórico;
4. introduzir working copy mutável sem alterar revisões imutáveis;
5. manter detalhes técnicos recolhidos por padrão;
6. reutilizar os casos de uso da camada de aplicação, sem mover regras para o
   adaptador web.
