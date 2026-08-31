# Componentes da aplicação

## 1. Visão arquitetural

O `novel-translator` adotará arquitetura hexagonal leve. A CLI é um adapter de entrada; os casos de uso formam a camada de aplicação; modelos, regras e transformações determinísticas ficam no núcleo; filesystem, HTTP, relógio e terminal são acessados por ports implementados por adapters. Dependências apontam das bordas para o núcleo.

O desenho aplica KISS, responsabilidade única e composição sobre herança. Protocols são usados somente nas fronteiras substituíveis exigidas pelos requisitos; não haverá framework de plugins, event bus ou hierarquias de classes na v1.

## 2. Componentes de entrada e composição

### 2.1 `CliAdapter`

**Propósito**: expor `translate`, `approve`, `export` e `inspect`.

**Responsabilidades**:

- interpretar argumentos e distinguir execução interativa de não interativa;
- construir commands/queries tipados;
- chamar exatamente um caso de uso por operação;
- converter outcomes de negócio e exceções tipadas em mensagens e exit codes estáveis;
- solicitar confirmação somente quando o caso de uso retornar uma decisão pendente.

**Não faz**: validação de domínio, acesso direto ao filesystem, HTTP, persistência ou renderização de Markdown.

### 2.2 `CompositionRoot`

**Propósito**: montar a aplicação no início do processo.

**Responsabilidades**:

- carregar configuração e segredos pelas bordas apropriadas;
- instanciar adapters e injetá-los nos casos de uso;
- manter mappings explícitos para providers e source extractors;
- falhar cedo para nomes configurados desconhecidos.

## 3. Casos de uso

### 3.1 `TranslateChapter`

Orquestra validação, ingestão, criação do run, contexto, segmentação sequencial, prompts, chamadas com retry, snapshots, recomposição e conclusão. Controla a ordem do workflow; toda escrita passa por `RunRepository`.

### 3.2 `ApproveDraft`

Verifica a elegibilidade do run e registra um evento append-only contendo `run_id`, hash do draft, timestamp e aprovador opcional.

### 3.3 `ExportDraft`

Verifica integridade da aprovação, resolve eventual decisão de aprovação, valida manifesto e destino, planeja todos os arquivos, detecta colisões e executa escrita segura. Não executa Git, Astro ou deployment.

### 3.4 `InspectRun`

Consulta run por identificador ou resolve o ponteiro de draft atual. Retorna uma visão sanitizada com status, tentativas, falhas e caminhos, sem conteúdo sensível por padrão.

## 4. Componentes do núcleo

### 4.1 `ConfigurationService`

Carrega configuração não sensível de TOML ou YAML, resolve referências a variáveis de ambiente e produz `AppConfig` tipado. O valor de um segredo nunca integra `AppConfig` serializável, logs ou snapshots.

### 4.2 `NovelDefinitionService`

Carrega e valida, separadamente, `TranslationBible` e `EditorialManifest`. Rejeita campos desconhecidos, referências incoerentes, tipos inválidos e capa ausente. Evita compartilhar modelos de serialização externos com o restante do núcleo.

### 4.3 `SourceAcquisitionService`

Seleciona um `SourceReader` por URI, adquire o capítulo e produz `SourceDocument` normalizado com conteúdo, proveniência e metadados. A identidade canônica informada pela CLI nunca é substituída por metadados extraídos.

### 4.4 `TranslationContextBuilder`

Transforma uma bible validada em `TranslationContext` determinístico e independente de provider.

### 4.5 `ChapterSegmenter`

Decide se a fonte cabe no limite seguro, divide sem perda ou duplicação e recompõe resultados na ordem original. Produz `SegmentPlan` explícito com estratégia, limites e hashes.

### 4.6 `PromptBuilder`

Renderiza templates versionados para cada segmento, incorporando contexto e continuidade. Produz `RenderedPrompt` e hash sem conhecer HTTP ou o formato específico do provider.

### 4.7 `TranslationGateway`

Port para o provider de LLM. Recebe `TranslationRequest` independente de SDK e retorna `TranslationResponse` com texto, métricas e representação auditável sanitizada. Falhas técnicas são exceções tipadas classificadas como transitórias ou permanentes.

### 4.8 `RetryExecutor`

Aplica limite e backoff configurados somente a falhas transitórias. Registra cada `AttemptRecord` e nunca repete uma chamada após sucesso confirmado.

### 4.9 `RunRepository`

Port que cria diretórios únicos, grava snapshots imutáveis, atualiza `run.json` de forma atômica e publica o ponteiro mutável do draft atual somente após a conclusão válida. Rejeita sobrescrita de conteúdo imutável.

### 4.10 `ApprovalStore`

Port append-only para `ApprovalEvent` e `ExportEvent`. Localiza a aprovação válida mais recente por `run_id` e hash, preservando eventos anteriores mesmo após alteração do draft.

### 4.11 `CurrentDraftStore`

Port pequeno para leitura e atualização atômica da projeção mutável `novel/chapter -> run_id`. O ponteiro é derivado e não altera o run.

### 4.12 `NovelSiteExporter`

Valida o contrato versionado, resolve volume, slug e nome ordenável, renderiza frontmatter/Markdown e cria um `ExportPlan`. A escrita é delegada a `SafeFileWriter`, que confina caminhos ao checkout, pré-valida colisões e substitui arquivos atomicamente apenas quando autorizado.

## 5. Adapters

| Port | Adapter da v1 | Responsabilidade externa |
|---|---|---|
| `SourceReader` | `LocalFileSourceReader` | Ler UTF-8 e preservar referência local. |
| `SourceReader` | `KakuyomuSourceReader` | Fazer HTTP e extrair página/metadados suportados. |
| `TranslationGateway` | `OpenAICompatibleGateway` | Chamar o endpoint OpenCode Go compatível com OpenAI. |
| `RunRepository` | `FileSystemRunRepository` | Persistir runs e `run.json` no workspace. |
| `ApprovalStore` | `FileApprovalStore` | Acrescentar eventos editoriais locais. |
| `CurrentDraftStore` | `FileCurrentDraftStore` | Manter ponteiro atômico por capítulo. |
| `SafeFileWriter` | `AtomicFileWriter` | Planejar temporários, validar colisões e promover arquivos. |
| `HttpClient` | adapter HTTP a selecionar em NFR Design | Executar requests substituíveis em testes. |
| `Clock` | `SystemClock` | Fornecer instantes injetáveis. |
| `RunIdGenerator` | `UuidRunIdGenerator` | Produzir IDs únicos. |
| `ProgressReporter` | `TerminalProgressReporter` | Exibir progresso sanitizado. |

## 6. Modelos compartilhados do núcleo

Modelos serão tipados e preferencialmente imutáveis: `ChapterIdentity`, `TranslateCommand`, `ApproveCommand`, `ExportCommand`, `InspectQuery`, `AppConfig`, `TranslationBible`, `EditorialManifest`, `SourceDocument`, `TranslationContext`, `Segment`, `SegmentPlan`, `RenderedPrompt`, `TranslationRequest`, `TranslationResponse`, `AttemptRecord`, `RunRecord`, `ApprovalEvent`, `ExportEvent`, `ExportPlan` e outcomes específicos.

Tipos vindos de YAML, TOML, HTTP, CLI ou JSON são convertidos nas bordas. Nenhum modelo de biblioteca externa atravessa um port.

## 7. Regras de dependência

1. CLI depende de commands, queries, outcomes e casos de uso.
2. Casos de uso dependem de modelos, serviços puros e ports.
3. Serviços do núcleo não dependem de CLI, filesystem, HTTP ou provider concreto.
4. Adapters dependem dos ports que implementam e convertem dados externos.
5. Adapters não chamam outros adapters; a coordenação pertence aos casos de uso.
6. Persistência editorial e status técnico permanecem separados.

## 8. Rastreabilidade resumida

| Área | Requisitos e histórias principais |
|---|---|
| CLI e composição | FR-CLI-001 a FR-CLI-004; US-001, US-011 a US-013 |
| Novel definitions | FR-BIB-001 a FR-BIB-004, FR-EDT-001 a FR-EDT-003; US-002, US-003 |
| Source acquisition | FR-ING-001 a FR-ING-004; US-004 a US-006 |
| Translation pipeline | FR-TRN-001 a FR-TRN-006; US-008 a US-010 |
| Workspace | FR-RUN-001 a FR-RUN-005; US-007, US-011, US-019 |
| Approval | FR-APR-001 a FR-APR-003; US-012 a US-014 |
| Export | FR-EXP-001 a FR-EXP-007; US-015 a US-017 |

## 9. Extension Compliance

- Resiliency Baseline: desabilitada; N/A.
- Security Baseline: desabilitada; N/A. NFR-006 continua obrigatório.
- Property-Based Testing parcial: N/A para a identificação de componentes; ports e transformações foram isolados para permitir PBT-02, PBT-03 e PBT-07 posteriormente.
