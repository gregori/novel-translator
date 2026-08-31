# Entidades de domínio — `novel-translator-cli`

## 1. Princípios

- Modelos do núcleo são tipados, preferencialmente imutáveis e independentes de YAML, JSON, HTTP e CLI.
- Identidade, conteúdo e proveniência são conceitos separados.
- Runs e eventos editoriais formam histórico append-only; somente projeções derivadas são mutáveis.
- Texto é tratado como Unicode e serializado em UTF-8 nas bordas.

## 2. Identidade e definições da novel

| Modelo | Campos essenciais | Invariantes |
|---|---|---|
| `NovelId` | `slug` | Não vazio; identidade estável da configuração local. |
| `ChapterIdentity` | `novel`, `chapter` | A identidade fornecida pela CLI é canônica e nunca é substituída por metadados extraídos. |
| `ChapterMetadata` | `chapter_title`, `explicit_volume` | Título não vazio; volume, quando presente, é inteiro positivo. |
| `TranslationBible` | título, idiomas, versão, personagens, termos, regras de honoríficos, convenções e estilo | Schema estrito; sem campos desconhecidos; referências e aliases coerentes. |
| `CharacterEntry` | `canonical_name`, `aliases`, `notes` | Nome canônico não vazio; aliases não vazios e sem duplicatas dentro da entrada. |
| `TerminologyEntry` | `source_term`, `preferred_translation`, `notes` | Origem e tradução não vazias; uma origem não pode apontar silenciosamente para traduções preferidas conflitantes. |
| `EditorialManifest` | título, autor original, categorias, status, sinopse, capa e créditos | Campos obrigatórios válidos; categorias não vazias; status pertencente ao conjunto aprovado. |

Personagens e terminologia são listas de objetos, conforme decisão funcional Q1. A ordem de entrada não afeta o contexto canônico: o builder usa ordenação determinística por chave normalizada, preservando o conteúdo textual original.

## 3. Fonte e contexto

| Modelo | Campos essenciais | Invariantes |
|---|---|---|
| `SourceDocument` | identidade canônica, conteúdo, tipo, URI, captura, reader, versão, metadados, hash | Conteúdo não vazio; hash corresponde aos bytes UTF-8 normalizados; metadados não alteram a identidade. |
| `SourceMetadata` | título/volume extraídos e dados do reader | Campos opcionais; valor extraído é apenas evidência, não decisão canônica. |
| `TranslationContext` | idiomas, personagens, termos, regras e estilo canônicos | Determinístico para a mesma bible; independente de provider. |
| `ContextBudget` | limite total, reserva de saída e margem de segurança | Valores positivos; orçamento disponível deve permanecer maior que zero. |

## 4. Segmentação e tradução

| Modelo | Campos essenciais | Invariantes |
|---|---|---|
| `SegmentPlan` | estratégia, orçamento, hash da fonte e segmentos | Segmentos cobrem integralmente a fonte, sem lacunas, sobreposição ou duplicação. |
| `Segment` | índice, offsets inicial/final, texto e hash | Índices contíguos; offsets válidos; texto equivale exatamente ao slice da fonte. |
| `ContinuityState` | termos/personagens observados e resumo curto determinístico | Derivado somente de segmentos anteriores; limitado pelo orçamento; não contém traduções anteriores completas. |
| `RenderedPrompt` | versão, segmento, contexto, continuidade, conteúdo e hash | Mesmo conjunto de entradas produz os mesmos bytes e hash. |
| `TranslationRequest` | provider, modelo, endpoint ID, parâmetros, prompt e correlação | Não contém credenciais; todos os campos persistíveis são sanitizados. |
| `TranslationResponse` | texto, métricas, resposta auditável e classificação | Texto traduzido não vazio para sucesso. |
| `AttemptRecord` | segmento, número, timestamps, resultado e falha | Numeração começa em 1 e cresce sem lacunas por segmento. |
| `TranslatedSegment` | índice, texto traduzido, prompt/ref. de resposta | Existe exatamente um resultado bem-sucedido para cada segmento recomposto. |
| `Draft` | run, conteúdo, hash e segmentos de origem | Só existe como concluído após todos os segmentos; ordem igual à do plano. |

O resumo de continuidade é local e determinístico: registra termos e personagens encontrados e uma síntese extrativa limitada dos trechos já traduzidos. Ele não executa nova chamada ao LLM e nunca inclui a tradução completa de um segmento anterior.

## 5. Run e auditoria

| Modelo | Campos essenciais | Invariantes |
|---|---|---|
| `RunRecord` | `run_id`, identidade, metadados, hashes, provider/modelo, status, tempos e referências | `run_id` único; transições monotônicas; referências apontam apenas para artefatos do próprio run. |
| `RunStatus` | `started`, `translating`, `draft_completed`, `failed`, `interrupted` | Estados finais não retornam a estados ativos. |
| `Snapshot` | nome lógico, tipo, hash e conteúdo/referência | Create-only por nome lógico; conteúdo já confirmado não é sobrescrito. |
| `FailureRecord` | etapa, classificação, mensagem sanitizada e causa técnica | Não contém segredos; distingue falha transitória, permanente, persistência e interrupção. |
| `CurrentDraftProjection` | identidade para `run_id` | Aponta somente para run concluído; sua alteração não modifica o run. |

Cada reexecução da mesma identidade cria um novo run. O ponteiro atual só muda após a conclusão integral do novo draft, conforme decisão funcional Q4.

## 6. Aprovação e exportação

| Modelo | Campos essenciais | Invariantes |
|---|---|---|
| `ApprovalEvent` | evento, run, hash do draft, timestamp e aprovador | Append-only; válido somente para o hash atual do draft. |
| `ApprovalProjection` | run, hash e evento mais recente | Derivada do histórico; não remove eventos anteriores. |
| `ExportEvent` | evento, run, hash aprovado, plano, destinos e resultado | Append-only; só é criado após resultado observável da escrita. |
| `VolumeDecision` | valor explícito, extraído, resolvido e diagnóstico | Valor explícito tem precedência; conflito é diagnosticado; valor final é positivo ou ausente. |
| `ExportPlan` | contrato, arquivos planejados e fingerprint | Completo e determinístico antes de qualquer escrita. |
| `PlannedFile` | destino relativo, conteúdo/hash e política | Destino confinado; caminhos únicos no plano. |
| `CollisionReport` | arquivos idênticos, novos e conflitantes | Calculado para o plano completo antes da confirmação. |
| `WriteAuthorization` | fingerprint do plano, permissão e origem da decisão | Uma autorização não vale para plano alterado. |

Todos os eventos são preservados. Consultas e elegibilidade usam a aprovação mais recente para o par `run_id + draft_hash`, conforme a clarificação aprovada.

## 7. Relações

- `ChapterIdentity` possui muitos `RunRecord`; no máximo um deles é apontado pela `CurrentDraftProjection`.
- Um `RunRecord` possui um `SourceDocument`, uma `TranslationBible` snapshotada, um `SegmentPlan`, zero ou mais `AttemptRecord` e no máximo um `Draft` concluído.
- Um `RunRecord` possui zero ou mais eventos editoriais; `ApprovalProjection` é calculada desses eventos.
- `ExportPlan` referencia exatamente um draft aprovado e um `EditorialManifest` validado.

## 8. Propriedades PBT

- PBT-02: serializar e desserializar modelos auditáveis preserva igualdade semântica; concatenar os slices de `SegmentPlan` recupera exatamente a fonte.
- PBT-03: identidade canônica, cobertura dos segmentos, monotonicidade de estados, precedência de volume, validade por hash e confinamento de destinos permanecem invariantes.
- PBT-07: estratégias compartilhadas geram bibles, manifestos, Unicode, capítulos, runs, segmentos, eventos e caminhos válidos.
- PBT-08/PBT-09: propriedades usam Hypothesis, shrinking padrão e reprodução do exemplo mínimo/seed pelo runner definido na etapa técnica.

## 9. Conformidade

- Property-Based Testing parcial: compliant para PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09.
- Security Baseline e Resiliency Baseline: N/A, desabilitadas no estado do projeto.
- Não há Mermaid, JSON, YAML ou diagrama ASCII neste artefato.
