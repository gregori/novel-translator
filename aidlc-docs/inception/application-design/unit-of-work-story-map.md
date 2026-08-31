# Mapa de stories para a unidade de trabalho

## 1. Regra de atribuição

Todas as stories US-001 a US-019 pertencem à Unit of Work `novel-translator-cli`. Cada story possui exatamente um módulo owner primário, escolhido pelo resultado de negócio predominante. Módulos colaboradores não compartilham ownership e não criam nova unit.

## 2. Mapa completo

| Story | Título | Unit of Work | Owner primário | Colaboradores principais | Incremento |
|---|---|---|---|---|---:|
| US-001 | Carregar configuração sem expor segredos | `novel-translator-cli` | `shared` | `cli`, `adapters` | 1 |
| US-002 | Validar a translation bible e construir contexto | `novel-translator-cli` | `translation` | `shared`, `adapters` | 2 |
| US-003 | Validar os metadados editoriais da novel | `novel-translator-cli` | `editorial` | `shared`, `adapters` | 3 |
| US-004 | Ingerir um capítulo de arquivo local | `novel-translator-cli` | `source` | `workspace`, `adapters`, `cli` | 2 |
| US-005 | Ingerir um capítulo do Kakuyomu | `novel-translator-cli` | `source` | `workspace`, `adapters`, `cli` | 2 |
| US-006 | Preservar identidade e resolver volume | `novel-translator-cli` | `source` | `editorial`, `shared`, `cli` | 2 |
| US-007 | Iniciar uma execução imutável | `novel-translator-cli` | `workspace` | `shared`, `translation`, `adapters` | 1 |
| US-008 | Gerar um draft pelo provider configurado | `novel-translator-cli` | `translation` | `source`, `workspace`, `adapters`, `cli` | 2 |
| US-009 | Traduzir um capítulo maior que o limite seguro | `novel-translator-cli` | `translation` | `workspace`, `shared` | 2 |
| US-010 | Tratar falhas transitórias e interrupções | `novel-translator-cli` | `translation` | `workspace`, `adapters`, `cli` | 2 |
| US-011 | Consultar status, draft atual e auditoria | `novel-translator-cli` | `workspace` | `editorial`, `cli`, `adapters` | 2 |
| US-012 | Aprovar explicitamente um draft | `novel-translator-cli` | `editorial` | `workspace`, `cli`, `adapters` | 3 |
| US-013 | Aprovar com segurança durante a exportação | `novel-translator-cli` | `editorial` | `workspace`, `cli` | 3 |
| US-014 | Invalidar aprovação de um draft alterado | `novel-translator-cli` | `editorial` | `workspace`, `shared` | 3 |
| US-015 | Exportar metadados e capa da novel | `novel-translator-cli` | `editorial` | `adapters`, `shared`, `cli` | 3 |
| US-016 | Exportar o capítulo aprovado em Markdown | `novel-translator-cli` | `editorial` | `workspace`, `adapters`, `shared` | 3 |
| US-017 | Escrever no destino sem sobrescrever nem publicar | `novel-translator-cli` | `editorial` | `adapters`, `workspace`, `cli` | 3 |
| US-018 | Obter comportamento portátil e Unicode correto | `novel-translator-cli` | `shared` | Todos os módulos e adapters | 4 |
| US-019 | Recuperar-se de falhas de persistência sem corromper artefatos | `novel-translator-cli` | `workspace` | `editorial`, `translation`, `adapters`, `shared` | 4 |

## 3. Resumo por owner primário

| Módulo owner | Stories | Quantidade |
|---|---|---:|
| `shared` | US-001, US-018 | 2 |
| `workspace` | US-007, US-011, US-019 | 3 |
| `source` | US-004, US-005, US-006 | 3 |
| `translation` | US-002, US-008, US-009, US-010 | 4 |
| `editorial` | US-003, US-012, US-013, US-014, US-015, US-016, US-017 | 7 |
| `cli` | Nenhuma como owner; adapta todas as operações do usuário | 0 |
| `adapters` | Nenhuma como owner; implementa efeitos requeridos pelas capacidades | 0 |
| **Total** | **US-001 a US-019** | **19** |

`cli` e `adapters` não recebem ownership primário porque seus comportamentos existem para entregar resultados das capacidades. Seus requisitos são implementados e testados como colaboradores das stories correspondentes.

## 4. Mapeamento para componentes de Application Design

| Owner | Componentes e casos de uso predominantes |
|---|---|
| `shared` | `ConfigurationService`, `AppConfig`, erros, `Clock`, IDs e `ContentHasher` |
| `workspace` | `RunRepository`, `CurrentDraftStore`, `ApprovalStore` para consulta, `InspectRun` e modelos de run |
| `source` | `SourceAcquisitionService`, `SourceReader`, `SourceDocument` e identidade/proveniência |
| `translation` | `NovelDefinitionService` para bible, `TranslationContextBuilder`, `ChapterSegmenter`, `PromptBuilder`, `RetryExecutor`, `TranslationGateway` e `TranslateChapter` |
| `editorial` | `NovelDefinitionService` para manifesto, `ApproveDraft`, `ExportDraft`, `DraftIntegrityService`, `VolumeResolver`, `NovelSiteExporter`, `ApprovalStore` e `SafeFileWriter` |

## 5. Sequência das stories

### Incremento 1 - Foundation

US-001 e US-007 estabelecem configuração, tipos, ports e lifecycle básico. As parcelas estruturais de US-018 e US-019 entram desde o início, mas o aceite integral ocorre no hardening.

### Incremento 2 - Source e translation

US-004, US-005 e US-006 entregam aquisição e identidade. US-002 prepara bible/contexto. US-008, US-009 e US-010 produzem o draft e tratam segmentação/falhas. US-011 fecha observabilidade e consulta.

### Incremento 3 - Editorial e export

US-003 valida o manifesto. US-012, US-013 e US-014 governam aprovação. US-015, US-016 e US-017 planejam e escrevem a exportação segura.

### Incremento 4 - Hardening transversal

US-018 e US-019 recebem validação ponta a ponta em Windows/macOS, Unicode e falhas de persistência. Obrigações de contrato e PBT são consolidadas sem alterar o ownership das demais stories.

## 6. Obrigações PBT por módulo

| Regra habilitada | Módulos alvo | Propriedades encaminhadas |
|---|---|---|
| PBT-02 | `workspace`, `translation`, `editorial` | Round-trip de modelos serializáveis, `run.json`, registros auditáveis, parse/format quando reversível e divisão/recomposição |
| PBT-03 | `shared`, `workspace`, `source`, `translation`, `editorial` | Identidade canônica, precedência de volume, estados, imutabilidade, hash aprovado, ordem/cobertura de segmentos, nomes ordenáveis e determinismo |
| PBT-07 | Todos os módulos de domínio | Estratégias centralizadas para bibles, manifestos, capítulos Unicode, metadados, runs, segmentos, estados e caminhos válidos |
| PBT-08 | Unit inteira | Shrinking ativo, exemplo mínimo e seed reproduzível em testes/CI |
| PBT-09 | Unit inteira | Hypothesis integrado ao runner Python e registrado na stack/dependências |

## 7. Verificação de cobertura e unicidade

- Intervalo esperado: US-001 a US-019.
- IDs atribuídos: 19.
- IDs ausentes: nenhum.
- IDs duplicados como owner primário: nenhum.
- Units sem story: nenhuma.
- Stories sem Unit of Work: nenhuma.
- Stories atribuídas a unit diferente: nenhuma.

## 8. Readiness para design por unidade

A Unit of Work está pronta para Construction porque possui fronteiras internas, direção de dependência, sequência e ownership integral. Functional Design deve analisar a unit por módulo/componente e registrar propriedades testáveis; NFR Requirements/NFR Design devem aplicar decisões comuns a todo o package; Code Generation deve manter a atribuição primária desta matriz.

## 9. Extension Compliance

| Extensão | Resultado | Justificativa |
|---|---|---|
| Resiliency Baseline | N/A | Desabilitada. |
| Security Baseline | N/A | Desabilitada. |
| Property-Based Testing parcial | Compliant | Todas as regras habilitadas foram encaminhadas a módulos, propriedades e etapas aplicáveis, sem impor regras desabilitadas. |

Não há achado bloqueante de extensão.

## 10. Validação de conteúdo

- Markdown, tabelas, IDs e contagens foram revisados.
- Os 19 IDs formam um intervalo completo e aparecem uma vez na coluna de ownership primário.
- Não há Mermaid, JSON, YAML ou diagrama ASCII.
