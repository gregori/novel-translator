# Componentes lógicos de NFR — `novel-translator-cli`

## 1. Organização

`WorkspaceSafetyService` é uma facade da camada de aplicação. Ela não implementa mecanismos diretamente: coordena ports pequenos para lock, publicação atômica, transação de exportação e retenção. Essa fronteira oferece uma entrada coesa aos casos de uso sem concentrar razões de mudança.

Os componentes permanecem organizados em quatro grupos:

- coordenação de segurança do workspace;
- processamento incremental e orçamento de contexto;
- confiabilidade de rede e persistência;
- segurança, observabilidade e recuperação.

## 2. Catálogo de componentes

| Componente | Camada | Responsabilidade |
|---|---|---|
| `WorkspaceSafetyService` | application | Coordenar lock e operações mutáveis; delegar sem conhecer detalhes de filesystem. |
| `WorkspaceLock` | port | Adquirir/liberar lock, expor timeout e verificar candidatura a recuperação. |
| `FileLockAdapter` | adapter | Implementar o port com `filelock` e metadados sanitizados separados. |
| `AtomicFileWriter` | port | Preparar, verificar e promover um artefato individual. |
| `LocalAtomicFileWriter` | adapter | Usar temporário no mesmo filesystem e replace cross-platform. |
| `ExportTransactionCoordinator` | application | Coordenar staging, inventário, promoções, rollback e reconciliação. |
| `ExportInventoryStore` | port | Persistir progresso recuperável da transação de exportação. |
| `RetentionPlanner` | domain/application | Produzir plano puro e excluir runs protegidos da seleção. |
| `RetentionExecutor` | application | Revalidar e executar plano confirmado sob lock. |
| `IncrementalSourcePipeline` | application | Encadear leitura, normalização, hash, segmentação e snapshots incrementais. |
| `IncrementalTextNormalizer` | domain | Normalizar blocos UTF-8 preservando fronteiras e equivalência definida. |
| `StreamingChapterSegmenter` | domain | Formar segmentos por parágrafo/sentença com buffer limitado. |
| `DraftAssembler` | application | Acrescentar traduções ordenadas em temporário e promover draft completo. |
| `TokenEstimator` | port | Estimar custo de contexto para um provider/modelo. |
| `ConservativeCharacterEstimator` | adapter | Fornecer fallback determinístico baseado em caracteres. |
| `ContextBudgetPlanner` | domain | Reservar overhead e calcular orçamento seguro por segmento. |
| `RetryExecutor` | application | Aplicar política de tentativas sem retry oculto. |
| `RetryPolicy` | domain | Classificar falhas, calcular delay e decidir nova tentativa. |
| `SecretRedactor` | port/service | Redigir valores e padrões sensíveis nas bordas. |
| `PathSafetyValidator` | domain/adapter | Validar raiz, ancestrais, reparse points e confinamento. |
| `PermissionHardener` | port | Aplicar permissões restritivas best-effort por plataforma. |
| `ProgressReporter` | port | Emitir eventos sanitizados de progresso. |
| `OutcomePresenter` | adapter | Produzir saída humana ou JSON versionado e sanitizado. |
| `PerformanceProbe` | test support | Medir séries geométricas e avaliar razão de crescimento. |

## 3. Contratos lógicos

```python
class WorkspaceLock(Protocol):
    def acquire(self, timeout_seconds: float) -> LockLease: ...
    def inspect_recovery(self) -> RecoveryAssessment: ...
    def recover(self, authorization: RecoveryAuthorization) -> None: ...

class AtomicFileWriter(Protocol):
    def prepare(self, target: Path, content: ByteStream) -> PreparedFile: ...
    def promote(self, prepared: PreparedFile) -> PublishedFile: ...

class TokenEstimator(Protocol):
    def estimate(self, request: TokenEstimateRequest) -> TokenEstimate: ...

class SecretRedactor(Protocol):
    def redact(self, value: str) -> str: ...

class ExportInventoryStore(Protocol):
    def create(self, inventory: ExportInventory) -> None: ...
    def record_step(self, transaction_id: str, step: ExportStep) -> None: ...
    def load_pending(self) -> tuple[ExportInventory, ...]: ...
```

`ByteStream` representa um iterable/reader de bytes e não exige materialização completa. Contratos internos usam nomes em inglês; a documentação explicativa permanece em português.

## 4. Fluxo de tradução incremental

1. `TranslateChapter` adquire lease pela facade.
2. `IncrementalSourcePipeline` lê e normaliza blocos, atualiza hash e produz snapshots.
3. `StreamingChapterSegmenter` fecha segmentos respeitando orçamento do `ContextBudgetPlanner`.
4. Cada segmento confirmado é persistido pelo `RunRepository` antes da chamada.
5. `RetryExecutor` chama `TranslationGateway` e registra cada tentativa sanitizada.
6. `DraftAssembler` acrescenta respostas confirmadas na ordem contígua.
7. Ao receber todos os segmentos, valida completude e solicita promoção ao `AtomicFileWriter`.
8. `RunRepository` conclui `run.json`; só depois `CurrentDraftStore` publica o ponteiro.
9. A facade libera o lease mesmo em falha ou interrupção.

Invariantes:

- índices confirmados são únicos, contíguos e crescentes;
- concatenação dos slices da fonte equivale à fonte normalizada;
- nenhum segmento é descartado antes de seu snapshot verificável;
- draft parcial nunca recebe `draft_completed`;
- pico de memória depende do maior segmento e de buffers limitados, não do capítulo completo.

## 5. Fluxo de exportação recuperável

1. `ExportDraft` adquire lock e rejeita inventário pendente não reconciliado.
2. O exporter cria `ExportPlan` sem efeitos.
3. `PathSafetyValidator` rejeita links, junctions, traversal e destinos fora da raiz.
4. `ExportTransactionCoordinator` cria staging e inventário persistido.
5. `AtomicFileWriter` prepara e verifica cada arquivo.
6. O coordinator promove arquivos um a um, persistindo o passo após cada promoção.
7. Sucesso integral permite acrescentar `ExportEvent`.
8. Falha aciona rollback best-effort; rollback incompleto mantém inventário bloqueante.

Antes de cada promoção, caminhos e colisões são revalidados. Alteração desde o plano invalida a autorização anterior.

## 6. Fluxo de retenção

1. `RetentionPlanner` recebe índice imutável de runs, projeção atual e eventos editoriais.
2. Produz plano determinístico excluindo current, approved e exported.
3. A CLI exibe dry-run completo.
4. Após confirmação, `RetentionExecutor` adquire lock e recalcula as proteções.
5. Qualquer divergência cancela o plano; não há seleção implícita adicional.
6. Remoções e falhas são registradas sem expor conteúdo.

## 7. Dependências permitidas

| Origem | Pode depender de | Não pode depender de |
|---|---|---|
| Domain | Tipos da biblioteca padrão e outros tipos de domínio | Typer, Pydantic, HTTPX, `filelock`, filesystem concreto |
| Application | Domain e ports | Adapters concretos e presenters Typer |
| Ports | Modelos internos mínimos | Implementações externas |
| Adapters | Ports, modelos de borda e bibliotecas escolhidas | Regras de negócio duplicadas |
| Composition root | Todas as implementações necessárias ao wiring | Lógica de domínio própria |

`WorkspaceSafetyService` depende de abstrações. O composition root injeta `FileLockAdapter`, `LocalAtomicFileWriter`, stores e hardener concretos.

## 8. Falhas e outcomes

| Categoria | Resultado lógico |
|---|---|
| Lock ocupado | `WorkspaceBusy`, sem mutação; informa opção de timeout. |
| Lock possivelmente obsoleto | `RecoveryRequired`, sem remoção automática. |
| Temporário inválido | Falha de persistência antes da publicação. |
| Promoção parcial revertida | Falha registrada; nova tentativa permitida após limpeza verificada. |
| Rollback incompleto | `ReconciliationRequired`; novas exportações bloqueadas. |
| Estimador indisponível | Fallback conservador registrado. |
| Sentença acima do orçamento | Falha permanente de segmentação. |
| Retry esgotado | Run `failed` com todas as tentativas preservadas. |
| Caminho com link/junction | Falha permanente antes de escrita. |
| Redação defensiva acionada | Mensagem sanitizada; valor original não é persistido. |

## 9. Testabilidade

- clock, jitter, filesystem, lock, HTTP, token estimator, redactor e terminal são injetáveis;
- adapters de lock e escrita possuem testes multiprocesso e de falha por plataforma;
- o coordinator usa stores em memória para simular falha em cada passo;
- pipeline incremental usa readers pequenos e limites artificiais de buffer;
- testes PBT exercitam Unicode fragmentado, equivalência de recomposição, caminhos e inventários;
- performance probes usam séries geométricas e não dependem de tempo absoluto portátil;
- canários de segredo percorrem erro de configuração, HTTP, logging e presenters.

## 10. Matriz de NFR por componente

| Grupo de requisito | Componentes primários |
|---|---|
| NFR-CAP | `WorkspaceLock`, `IncrementalSourcePipeline`, `RetentionPlanner` |
| NFR-PERF | `TokenEstimator`, `ContextBudgetPlanner`, `RetryExecutor`, `PerformanceProbe` |
| NFR-REL | `AtomicFileWriter`, `ExportTransactionCoordinator`, `ExportInventoryStore` |
| NFR-SEC | `SecretRedactor`, `PathSafetyValidator`, `PermissionHardener` |
| NFR-PORT | adapters cross-platform, normalizador incremental, APIs Python de path |
| NFR-UX | `ProgressReporter`, `OutcomePresenter`, outcomes estáveis |
| NFR-MNT | ports pequenos, composition root, doubles e separação de camadas |
| PBT parcial | strategies de domínio, pipeline, modelos, paths e eventos |

## 11. Conformidade de extensões

| Extensão | Resultado | Justificativa |
|---|---|---|
| Property-Based Testing parcial | Compliant | O desenho preserva alvos de PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09 para Code Generation. |
| Security Baseline | N/A | Desabilitada em `aidlc-state.md`; requisitos mínimos de produto foram desenhados. |
| Resiliency Baseline | N/A | Desabilitada em `aidlc-state.md`; requisitos aprovados de confiabilidade foram desenhados. |

Não há achado bloqueante.

## 12. Validação de conteúdo

O bloco Python contém assinaturas lógicas válidas. Markdown e tabelas foram revisados. Não há Mermaid, diagrama ASCII, JSON ou YAML embutido.

