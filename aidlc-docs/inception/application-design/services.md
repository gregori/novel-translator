# Serviços e orquestração

## 1. Princípios da camada de aplicação

- Cada comando da CLI chama um único caso de uso.
- Casos de uso coordenam componentes; não implementam parsing, HTTP, serialização ou regras de transformação detalhadas.
- Dependências entram por composição explícita no `CompositionRoot`.
- Operações retornam outcomes de negócio; falhas técnicas atravessam a camada como exceções tipadas.
- Nenhum serviço mantém estado em memória entre invocações da CLI.

## 2. `TranslateChapter`

### Responsabilidade

Produzir um draft auditável a partir de uma identidade canônica e uma fonte, mantendo um run válido mesmo em falha ou interrupção.

### Dependências

`ConfigurationService`, `NovelDefinitionService`, `SourceAcquisitionService`, `TranslationContextBuilder`, `ChapterSegmenter`, `PromptBuilder`, `TranslationGatewayRegistry`, `RetryExecutor`, `RunRepository`, `CurrentDraftStore`, `Clock`, `RunIdGenerator`, `ContentHasher` e `ProgressReporter`.

### Orquestração

1. Validar `TranslateCommand`, configuração e identidade canônica.
2. Carregar a bible antes de consumir rede do provider.
3. Criar um run único com estado `started`.
4. Adquirir a fonte e persistir conteúdo/proveniência como snapshot imutável.
5. Construir e persistir contexto da bible com versão e hash.
6. Criar `SegmentPlan` e persistir estratégia e segmentos.
7. Transicionar o run para `translating`.
8. Para cada segmento, em ordem:
   - renderizar e persistir o prompt;
   - construir requisição auditável sem segredo;
   - executar o gateway pela política de retry;
   - persistir cada tentativa, resposta e resultado do segmento;
   - disponibilizar a continuidade necessária ao segmento seguinte.
9. Recompor e validar o draft completo.
10. Persistir draft, hashes, métricas e `run.json`; transicionar para `draft_completed`.
11. Atualizar atomicamente o ponteiro de draft atual.
12. Retornar `TranslationCompleted` com `run_id` e caminhos relevantes.

### Falhas

- Antes da criação do run: erro de entrada/configuração, sem artefato de execução.
- Depois da criação: registrar falha ou interrupção e preservar tudo que já foi confirmado.
- Um segmento sem resposta válida impede recomposição e conclusão.
- A atualização do ponteiro não altera o run; falha nessa projeção é diagnosticada e recuperável.

## 3. `ApproveDraft`

### Responsabilidade

Registrar a aprovação explícita do conteúdo exato de um run concluído.

### Dependências

`RunRepository`, `ApprovalStore`, `DraftIntegrityService`, `Clock`, gerador de ID de evento e `ProgressReporter`.

### Orquestração

1. Carregar o run e verificar estado `draft_completed`.
2. Ler os bytes atuais do draft e calcular o hash canônico.
3. Criar `ApprovalEvent` com run, hash, timestamp e aprovador opcional.
4. Acrescentar o evento de maneira atômica e append-only.
5. Retornar `ApprovalRecorded`; repetição para o mesmo hash pode retornar a aprovação existente sem apagar histórico.

### Falhas

- Run inexistente ou inelegível retorna rejeição de negócio.
- Falha de leitura/hash ou escrita é técnica e não produz confirmação falsa.

## 4. `ExportDraft`

### Responsabilidade

Exportar o draft aprovado e íntegro para o contrato versionado do `novels-site`, com todas as decisões sensíveis explícitas.

### Dependências

`RunRepository`, `ApprovalStore`, `DraftIntegrityService`, `NovelDefinitionService`, `VolumeResolver`, `NovelSiteExporter`, `SafeFileWriter`, `Clock` e `ProgressReporter`.

### Orquestração

1. Carregar run concluído e draft; recalcular o hash.
2. Buscar aprovação válida para `run_id + draft_hash`.
3. Se ausente:
   - em modo interativo sem autorização, retornar `ApprovalRequired` para a CLI confirmar;
   - em modo não interativo sem flag explícita, rejeitar sem escrita;
   - com autorização explícita, compor `ApproveDraft` antes de continuar.
4. Carregar e validar manifesto e capa.
5. Resolver volume por CLI, metadado confiável e ausência; conflito é outcome de rejeição.
6. Gerar `ExportPlan` completo para índice, capa e capítulo.
7. Inspecionar confinamento de caminhos e todas as colisões antes de escrever.
8. Se houver colisão diferente sem autorização, retornar `CollisionDecisionRequired` ou rejeitar conforme o modo.
9. Escrever o plano com temporários e promoção segura.
10. Verificar hashes finais e acrescentar `ExportEvent`.
11. Retornar `ExportCompleted` com caminhos; nunca executar Git, Astro ou deployment.

### Decisão interativa em duas passagens

A CLI não é injetada no caso de uso. Quando é necessária confirmação, o serviço retorna um outcome descritivo. A CLI coleta consentimento e repete o comando com a flag explícita correspondente. Isso mantém o núcleo testável e impede consentimento implícito.

## 5. `InspectRun`

### Responsabilidade

Fornecer leitura sanitizada e sem mutação do histórico.

### Dependências

`RunRepository`, `CurrentDraftStore` e `ApprovalStore`.

### Orquestração

1. Resolver `run_id` diretamente ou pelo ponteiro `novel/chapter`.
2. Carregar o `RunRecord` e eventos editoriais relacionados.
3. Projetar `RunView` com status, tentativas, falhas, aprovação válida, exportações e caminhos.
4. Omitir prompts, respostas, fonte e draft por padrão; inclusão exige opção explícita.

## 6. Serviços puros auxiliares

| Serviço | Responsabilidade | Efeito externo |
|---|---|---|
| `TranslationContextBuilder` | Canonicalizar a bible em contexto. | Nenhum. |
| `ChapterSegmenter` | Planejar segmentos e recompor traduções. | Nenhum. |
| `PromptBuilder` | Renderizar template versionado. | Nenhum. |
| `VolumeResolver` | Aplicar precedência e detectar conflitos. | Nenhum. |
| `DraftIntegrityService` | Calcular e comparar hashes. | Nenhum. |
| `NovelSiteExporter.plan` | Renderizar um plano de arquivos. | Nenhum. |

Esses componentes são preferidos como funções ou objetos pequenos. Não usam herança e não recebem adapters que não sejam estritamente necessários.

## 7. Registries e composition root

O `CompositionRoot` utiliza mappings explícitos, equivalentes a:

```python
SOURCE_READERS = {
    "file": LocalFileSourceReader,
    "kakuyomu": KakuyomuSourceReader,
}

TRANSLATION_GATEWAYS = {
    "opencode-go": OpenAICompatibleGateway,
}
```

Os registries não fazem descoberta dinâmica, decorators globais ou import magic. Um adapter futuro é adicionado ao mapping e implementa o port existente; casos de uso não mudam.

## 8. Status técnico e estado editorial

### Status técnico do run

`started -> translating -> draft_completed`

De `started` ou `translating`, uma falha leva a `failed` e uma interrupção leva a `interrupted`. Estados finais não retornam a estados ativos.

### Estado editorial

- `ApprovalEvent` e `ExportEvent` são append-only.
- Uma aprovação é válida somente para o hash atual.
- `CurrentDraftStore` é projeção mutável atômica separada.
- Status técnico não recebe estados `approved` ou `exported`.

## 9. Limites transacionais locais

- Cada escrita individual de metadado, evento ou ponteiro usa temporário no mesmo filesystem e promoção atômica.
- Um run é consistente por progressão monotônica; não há transação distribuída entre workspace e checkout externo.
- A exportação pré-valida o conjunto inteiro, grava temporários e somente então promove cada destino.
- Se a promoção parcial não puder ser revertida pela plataforma, o resultado é marcado explicitamente como falha com inventário dos arquivos promovidos; o detalhamento será feito em Functional/NFR Design.

## 10. Observabilidade

Todos os serviços emitem `ProgressEvent` estruturado com tipo, `run_id`, etapa e dados não sensíveis. Adapters escolhem a apresentação. Prompts, respostas, tokens secretos e conteúdo integral não são exibidos por padrão.

## 11. Rastreabilidade

| Serviço | Histórias predominantes |
|---|---|
| `TranslateChapter` | US-001, US-002, US-004 a US-010, US-018, US-019 |
| `ApproveDraft` | US-012, US-014 |
| `ExportDraft` | US-003, US-006, US-013 a US-019 |
| `InspectRun` | US-007, US-011, US-014 |

## 12. Extension Compliance

- PBT parcial: N/A nesta etapa, mas serviços puros isolam round-trips e invariantes para PBT-02/PBT-03; os detalhes ficam para Functional Design.
- Security e Resiliency: desabilitadas. As proteções mínimas já exigidas continuam refletidas nos contratos.
