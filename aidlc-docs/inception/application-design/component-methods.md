# Métodos e contratos dos componentes

## 1. Convenções

- Assinaturas são contratos Python de alto nível; bibliotecas concretas serão fechadas em NFR Design.
- Commands, queries, modelos e outcomes são tipados e preferencialmente imutáveis.
- Outcomes de negócio esperados são valores explícitos. Falhas técnicas usam exceções tipadas.
- Operações da v1 são síncronas na perspectiva do caso de uso; adapters podem encapsular APIs assíncronas sem vazar esse detalhe.
- Caminhos usam `pathlib.Path`; texto persistido usa UTF-8 explícito.

## 2. Casos de uso

| Componente | Assinatura | Finalidade | Saída |
|---|---|---|---|
| `TranslateChapter` | `execute(command: TranslateCommand) -> TranslationOutcome` | Executar a pipeline completa e preservar o run. | `TranslationCompleted` ou outcome de negócio documentado. |
| `ApproveDraft` | `execute(command: ApproveCommand) -> ApprovalOutcome` | Aprovar o hash atual de um draft elegível. | `ApprovalRecorded` ou rejeição de elegibilidade/integridade. |
| `ExportDraft` | `execute(command: ExportCommand) -> ExportOutcome` | Validar aprovação e preparar/executar exportação segura. | `ExportCompleted`, `ApprovalRequired`, `CollisionDecisionRequired` ou rejeição. |
| `InspectRun` | `execute(query: InspectQuery) -> RunView` | Consultar run explícito ou draft atual sem mutação. | Visão sanitizada do run. |

### Commands e queries

```python
@dataclass(frozen=True)
class TranslateCommand:
    novel: str
    chapter: str
    chapter_title: str
    source: str
    volume: int | None

@dataclass(frozen=True)
class ApproveCommand:
    run_id: str
    approver: str | None

@dataclass(frozen=True)
class ExportCommand:
    run_id: str
    approve_if_needed: bool
    approver: str | None
    interactive: bool
    allow_overwrite: bool

@dataclass(frozen=True)
class InspectQuery:
    run_id: str | None
    novel: str | None
    chapter: str | None
    include_sensitive_content: bool = False
```

As pré-condições que relacionam campos serão validadas no início de cada caso de uso. A CLI somente converte argumentos para esses tipos.

## 3. Configuração e definições da novel

| Componente | Assinatura | Finalidade | Saída |
|---|---|---|---|
| `ConfigurationService` | `load(path: Path) -> AppConfig` | Carregar TOML/YAML e validar configuração não sensível. | Configuração tipada sem valores secretos. |
| `SecretProvider` | `get(name: str) -> SecretValue` | Resolver variável de ambiente requerida. | Wrapper não serializável e com representação redigida. |
| `NovelDefinitionService` | `load_bible(novel: str) -> TranslationBible` | Carregar bible YAML estrita. | Modelo interno validado. |
| `NovelDefinitionService` | `load_manifest(novel: str) -> EditorialManifest` | Carregar manifesto e verificar a capa. | Modelo interno validado. |
| `TranslationContextBuilder` | `build(bible: TranslationBible) -> TranslationContext` | Produzir contexto canônico e determinístico. | Contexto ordenado, versionável e serializável. |

## 4. Aquisição da fonte

```python
class SourceReader(Protocol):
    def supports(self, source: str) -> bool: ...
    def read(self, request: SourceRequest) -> SourceDocument: ...

class SourceReaderRegistry(Protocol):
    def resolve(self, source: str) -> SourceReader: ...
```

| Método | Entrada | Saída e propósito |
|---|---|---|
| `SourceAcquisitionService.acquire(request)` | `SourceRequest` com identidade canônica e URI/caminho | `SourceDocument` com texto normalizado, metadados, captura e identificador do reader. |
| `LocalFileSourceReader.read(request)` | Caminho local validável | Documento UTF-8; arquivo vazio ou inválido causa exceção tipada. |
| `KakuyomuSourceReader.read(request)` | URL suportada | Documento extraído; distingue URL, ausência e estrutura incompatível. |

`SourceDocument` contém `content`, `source_type`, `source_uri`, `captured_at`, `reader_id`, `reader_version`, `metadata` e `content_hash`. Novel e capítulo extraídos nunca substituem `ChapterIdentity`.

## 5. Segmentação, prompt e tradução

| Componente | Assinatura | Finalidade | Saída |
|---|---|---|---|
| `ChapterSegmenter` | `plan(source: SourceDocument, budget: ContextBudget) -> SegmentPlan` | Selecionar estratégia e criar segmentos ordenados. | Plano com limites, hashes e cobertura. |
| `ChapterSegmenter` | `recompose(translations: Sequence[TranslatedSegment]) -> Draft` | Juntar resultados na ordem do plano. | Draft único; rejeita lacuna, duplicata ou ordem inválida. |
| `PromptBuilder` | `render(context: PromptContext, segment: Segment) -> RenderedPrompt` | Renderizar template versionado e continuidade. | Prompt, versão e hash. |
| `TranslationGateway` | `translate(request: TranslationRequest) -> TranslationResponse` | Obter tradução independente de provider concreto. | Texto validado, métricas e resposta auditável sanitizada. |
| `TranslationGatewayRegistry` | `resolve(provider: str) -> TranslationGateway` | Resolver mapping explícito configurado. | Adapter conhecido ou erro de configuração. |
| `RetryExecutor` | `execute(operation: Callable[[], T], policy: RetryPolicy, observer: AttemptObserver) -> T` | Repetir somente falhas transitórias. | Primeiro sucesso ou exceção final com histórico. |

`TranslationRequest` contém provider/model, endpoint ID não sensível, parâmetros permitidos, prompt e identificadores de correlação. Credenciais são fornecidas ao adapter fora desse modelo serializável.

## 6. Workspace e lifecycle do run

```python
class RunRepository(Protocol):
    def create(self, seed: RunSeed) -> RunRecord: ...
    def append_snapshot(self, run_id: str, snapshot: Snapshot) -> ArtifactRef: ...
    def record_attempt(self, run_id: str, attempt: AttemptRecord) -> None: ...
    def transition(self, run_id: str, transition: RunTransition) -> RunRecord: ...
    def complete(self, run_id: str, draft: Draft, summary: RunSummary) -> RunRecord: ...
    def fail(self, run_id: str, failure: FailureRecord) -> RunRecord: ...
    def interrupt(self, run_id: str, reason: str) -> RunRecord: ...
    def get(self, run_id: str) -> RunRecord: ...
    def read_draft(self, run_id: str) -> Draft: ...

class CurrentDraftStore(Protocol):
    def get(self, identity: ChapterIdentity) -> str | None: ...
    def set(self, identity: ChapterIdentity, run_id: str) -> None: ...
```

### Regras contratuais

- `create` reserva um local único antes de qualquer chamada externa.
- `append_snapshot` é create-only para cada nome lógico e verifica hash.
- `transition` aceita somente transições válidas e grava `run.json` atomicamente.
- `complete` publica o draft antes do estado concluído; ponteiro atual é atualizado depois.
- `fail` e `interrupt` preservam snapshots já confirmados.
- `set` troca apenas a projeção mutável e nunca escreve dentro do run.

## 7. Aprovação e eventos editoriais

```python
class ApprovalStore(Protocol):
    def append_approval(self, event: ApprovalEvent) -> None: ...
    def append_export(self, event: ExportEvent) -> None: ...
    def find_valid_approval(self, run_id: str, draft_hash: str) -> ApprovalEvent | None: ...
    def list_events(self, run_id: str) -> Sequence[EditorialEvent]: ...

class DraftIntegrityService:
    def hash(self, draft: Draft) -> str: ...
    def verify(self, draft: Draft, approval: ApprovalEvent) -> IntegrityOutcome: ...
```

Eventos recebem IDs únicos, timestamp injetado e são append-only. `find_valid_approval` não apaga aprovações antigas; apenas exige igualdade entre o hash atual e o aprovado.

## 8. Exportação

| Componente | Assinatura | Finalidade | Saída |
|---|---|---|---|
| `VolumeResolver` | `resolve(explicit: int | None, extracted: int | None) -> VolumeOutcome` | Aplicar precedência e detectar conflito/invalidez. | Volume positivo ou ausência/rejeição. |
| `NovelSiteExporter` | `plan(request: ExportRequest) -> ExportPlan` | Validar contrato, renderizar índice/capa/capítulo e destinos. | Plano completo sem efeitos. |
| `SafeFileWriter` | `inspect(plan: ExportPlan) -> CollisionReport` | Confinar caminhos e detectar colisões antes de escrever. | Relatório determinístico. |
| `SafeFileWriter` | `write(plan: ExportPlan, authorization: WriteAuthorization) -> WrittenArtifacts` | Gravar temporários e promover arquivos autorizados. | Referências e hashes finais. |

O `ExportPlan` contém todos os `PlannedFile` com destino relativo, bytes UTF-8 ou binários, hash e política de colisão. Se qualquer destino for inválido, nenhuma escrita começa.

## 9. Utilitários injetáveis

```python
class Clock(Protocol):
    def now(self) -> datetime: ...

class RunIdGenerator(Protocol):
    def new(self) -> str: ...

class ContentHasher(Protocol):
    def digest(self, content: bytes) -> str: ...

class ProgressReporter(Protocol):
    def report(self, event: ProgressEvent) -> None: ...
```

## 10. Taxonomia de erro

| Categoria | Forma | Exemplos | Tratamento da CLI |
|---|---|---|---|
| Outcome de negócio | valor tipado | aprovação requerida, colisão requer confirmação | Mensagem acionável; pode solicitar decisão. |
| Entrada/configuração | exceção tipada | bible inválida, provider desconhecido | Mensagem sem stack trace; exit code estável. |
| Integração transitória | exceção tipada com classificação | timeout, rate limit, indisponibilidade | `RetryExecutor`, depois falha explícita. |
| Integração permanente | exceção tipada | URL não suportada, resposta inválida | Sem retry; run falha preservando artefatos. |
| Persistência/integridade | exceção tipada | colisão imutável, escrita atômica falhou | Interrompe publicação de estado e mantém diagnóstico. |
| Defeito inesperado | exceção não prevista | invariante interna quebrada | Exit code interno, correlação e mensagem sanitizada. |

## 11. Extension Compliance

- PBT parcial não impõe implementação nesta etapa. As assinaturas tornam explícitos os pares de round-trip e invariantes a detalhar em Functional Design.
- Security e Resiliency permanecem desabilitadas; segredo fora dos modelos serializáveis atende o requisito NFR-006, não a uma extensão adicional.
