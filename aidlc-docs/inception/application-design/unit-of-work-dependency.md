# Dependências da unidade de trabalho

## 1. Dependências entre unidades

Há somente uma unidade implantável. Portanto, não existem dependências inter-unit, protocolos de rede internos ou ordem de deployment entre serviços.

| Unit of Work | Depende de | Tipo | Estado |
|---|---|---|---|
| `novel-translator-cli` | Nenhuma outra unit | N/A | Autocontida para desenvolvimento e distribuição |

As integrações com Kakuyomu, OpenCode Go, workspace e `novels-site` são dependências externas acessadas por ports; não são Units of Work deste produto.

## 2. Regra de direção interna

A direção permitida é `cli -> application -> domain/ports <- adapters`. O `CompositionRoot` instancia as implementações e injeta dependências; ele não contém regra de negócio.

| Origem | Destino permitido | Finalidade |
|---|---|---|
| `cli` | Commands, queries, outcomes e casos de uso | Adaptar uma invocação para uma operação |
| Application de cada capacidade | Domain, serviços puros e ports | Orquestrar o workflow |
| Domain | `shared` estritamente necessário | Reusar tipos fundamentais sem efeitos externos |
| `adapters` | Ports e tipos internos implementados | Converter e executar efeitos externos |
| `composition.py` | CLI, casos de uso e adapters | Fazer wiring explícito |

Dependências proibidas:

- domain/application para CLI ou adapter concreto;
- chamada direta entre adapters;
- `workspace` para `editorial` ou o inverso como coordenação implícita;
- `source` para gateway de tradução;
- exporter para repositório de runs;
- regra de capacidade dentro de `shared` ou do composition root.

## 3. Matriz de dependências dos módulos

Legenda: `D` dependência de tipos/contratos; `O` orquestra uso; `I` implementa port; `W` wiring; `-` sem dependência direta.

| Origem | `shared` | `workspace` | `source` | `translation` | `editorial` | `cli` | `adapters` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `shared` | - | - | - | - | - | - | - |
| `workspace` | D | - | - | - | - | - | - |
| `source` | D | - | - | - | - | - | - |
| `translation` | D | O | O | - | - | - | - |
| `editorial` | D | O | - | - | - | - | - |
| `cli` | D | - | - | O | O | - | - |
| `adapters` | D | I | I | I | I | - | - |
| `composition.py` | W | W | W | W | W | W | W |

Interpretação importante: `translation` e `editorial` usam contratos de workspace a partir de seus casos de uso; não importam adapters de filesystem. A CLI chama os casos de uso, mas não importa internals de capacidades para executar efeitos diretamente.

## 4. Dependências dos casos de uso

| Caso de uso | Módulo owner | Dependências internas | Ports externos |
|---|---|---|---|
| `TranslateChapter` | `translation` | `shared`, `source`, modelos/serviços de `translation`, contratos de `workspace` | `SourceReader`, `TranslationGateway`, `RunRepository`, `CurrentDraftStore`, `Clock`, `RunIdGenerator`, `ContentHasher`, `ProgressReporter` |
| `ApproveDraft` | `editorial` | `shared`, integridade editorial e contratos de `workspace` | `RunRepository`, `ApprovalStore`, `Clock`, `EventIdGenerator`, `ProgressReporter` |
| `ExportDraft` | `editorial` | `shared`, manifesto, integridade, volume e exporter | `RunRepository`, `ApprovalStore`, `SafeFileWriter`, `Clock`, `ProgressReporter` |
| `InspectRun` | `workspace` | `shared` e projeções sanitizadas | `RunRepository`, `CurrentDraftStore`, `ApprovalStore` |

## 5. Sequência de dependências

| Ordem | Incremento | Pré-requisitos | Resultado desbloqueado |
|---:|---|---|---|
| 1 | Foundation | Nenhum | Tipos, erros, configuração, ports, package e workspace básico |
| 2 | Source e translation | Foundation | Ingestão, contexto, segmentação, provider e draft auditável |
| 3 | Editorial e export | Foundation e contratos de workspace | Aprovação, manifesto, integridade e exportação segura |
| 4 | Hardening transversal | Incrementos 1 a 3 | Portabilidade, Unicode, recuperação, contratos e PBT |

O incremento editorial não precisa esperar a implementação concreta completa da tradução; depende dos contratos e modelos estáveis do workspace. A sequência recomendada minimiza stubs e permite testes com doubles.

## 6. Análise de ciclos

Foi aplicada ordenação por camadas e por contratos:

1. `shared` não depende de capacidade.
2. Domain não depende de application ou adapters.
3. Application depende de domain/ports, nunca de implementações.
4. Adapters dependem dos ports que implementam.
5. `composition.py` é uma raiz de montagem sem consumidores internos.

Com essas regras, todo caminho termina em tipos/ports internos e não retorna à origem. A matriz não contém um par de dependências inversas entre módulos; portanto, não há ciclo planejado.

## 7. Readiness para Construction

- A única unit não possui dependência inter-unit pendente.
- Functional Design pode tratar a unit e detalhar propriedades por módulo/componente.
- NFR Requirements pode selecionar stack e Hypothesis para todo o package.
- NFR Design pode mapear configurações, persistência local, HTTP e políticas transversais.
- Code Generation pode seguir a sequência foundation, translation, editorial e hardening dentro de um único plano.

## 8. Extension Compliance

| Extensão | Resultado | Justificativa |
|---|---|---|
| Resiliency Baseline | N/A | Desabilitada. |
| Security Baseline | N/A | Desabilitada. |
| Property-Based Testing parcial | N/A nesta matriz | PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09 incidem sobre design técnico, geração e testes, não criam dependências entre units. |

Não há achado bloqueante de extensão.

## 9. Validação de conteúdo

- Markdown e tabelas foram revisados.
- A notação compacta de direção possui alternativa explicada em texto e matriz.
- Não há Mermaid, JSON, YAML ou diagrama ASCII.
