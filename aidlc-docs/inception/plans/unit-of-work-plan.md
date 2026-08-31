# Plano de Units Generation

## Objetivo

Decompor o design aprovado em unidades de trabalho e módulos implementáveis, com dependências, sequência, organização de código e atribuição integral das 19 histórias. Como a v1 é uma CLI local, a decisão sobre uma única unidade implantável ou múltiplas unidades lógicas precisa ser explícita antes da geração.

## Avaliação das categorias obrigatórias

| Categoria                | Evidência e necessidade de decisão                                                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Story Grouping           | Seis épicos atravessam fundamentos, tradução e editorial; é necessário escolher a estratégia de agrupamento. |
| Dependencies             | Workspace, configuração e modelos são compartilhados; é necessário definir ownership e ordem.                |
| Team Alignment           | A composição pode refletir ownership coletivo ou especializado.                                              |
| Technical Considerations | A v1 é um processo local sem deploy independente, mas os ports permitem evolução.                            |
| Business Domain          | Tradução, governança editorial e exportação têm coesão própria, com identidade e workspace comuns.           |
| Code Organization        | Projeto Python greenfield; é necessário escolher o layout do package e dos testes.                           |

## Plano de execução

### Part 1 - Planning

- [x] Ler requisitos, histórias, Application Design e regras de estrutura greenfield.
- [x] Avaliar todas as categorias obrigatórias de decomposição.
- [x] Coletar respostas para todas as decisões abaixo.
- [x] Validar respostas quanto a completude, ambiguidade e contradição.
- [x] Avaliar perguntas de acompanhamento; não foram necessárias.
- [x] Consolidar a decomposição proposta, sequência e critérios de fronteira.
- [x] Solicitar aprovação explícita deste plano antes da geração.
- [x] Registrar a aprovação e atualizar `aidlc-state.md`.

### Part 2 - Generation

- [x] Ler o plano aprovado e identificar o primeiro passo pendente de geração.
- [x] Gerar `aidlc-docs/inception/application-design/unit-of-work.md` com unidades, módulos, responsabilidades e estratégia de organização do código.
- [x] Gerar `aidlc-docs/inception/application-design/unit-of-work-dependency.md` com matriz e sequência de dependências.
- [x] Gerar `aidlc-docs/inception/application-design/unit-of-work-story-map.md` atribuindo todas as histórias a unidades/módulos.
- [x] Validar limites, ausência de dependências cíclicas e readiness para design por unidade.
- [x] Confirmar que US-001 a US-019 estão atribuídas exatamente uma vez como ownership primário.
- [x] Validar conteúdo e conformidade das extensões habilitadas.
- [x] Atualizar plano, estado e audit log; apresentar artefatos para aprovação explícita.

## Decisões de decomposição

Preencha uma opção em cada `[Answer]:`. Ao escolher “Other”, descreva a decisão.

### Question 1 - Modelo de unidade e implantação

Qual modelo deve representar a CLI na decomposição?

A) Uma única Unit of Work implantável (`novel-translator-cli`) com módulos internos explícitos

B) Múltiplas units/packages Python instaladas juntas e compostas pela mesma CLI

C) Múltiplos processos ou serviços independentes desde a v1

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 2 - Organização dos módulos internos

Como as responsabilidades devem ser agrupadas dentro da unidade ou packages?

A) Híbrida: módulos por capacidade (`translation`, `workspace`, `editorial`) apoiados por `domain`, `ports` e `adapters` mínimos

B) Por camadas técnicas puras (`cli`, `application`, `domain`, `infrastructure`) sem agrupamento por capacidade

C) Somente por épico/jornada, duplicando infraestrutura quando necessário para independência

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 3 - Sequência de implementação das histórias

Qual estratégia deve orientar a ordem entre módulos?

A) Fundamentos primeiro e depois fatias verticais: configuração/modelos/workspace, ingestão/tradução, aprovação/exportação e endurecimento transversal

B) Implementar cada épico completo na ordem EP-01 a EP-06, mesmo quando exigir stubs temporários

C) Priorizar primeiro um fluxo ponta a ponta mínimo e depois preencher persistência, erros e casos de borda

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 4 - Ownership de recursos compartilhados

Quem deve possuir configuração, modelos comuns, hashing, relógio e workspace?

A) Um núcleo compartilhado mínimo e estável; módulos de capacidade dependem de seus tipos/ports

B) O módulo de tradução possui os recursos e os módulos editoriais dependem dele

C) Cada módulo possui cópias/adapters próprios para reduzir dependências internas

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 5 - Alinhamento de equipe e ownership

Qual modelo de ownership deve ser refletido nos artefatos?

A) Uma equipe com ownership coletivo; fronteiras servem à coesão e testabilidade

B) Owners separados para foundation, translation e editorial/export

C) Ownership por camada técnica, como domain, application e adapters

D) Other (please describe after [Answer]: tag below)

[Answer]: C

### Question 6 - Evolução e escalabilidade de fronteiras

Quanto o design de unidades deve preparar extrações futuras?

A) Manter ports apenas nas fronteiras externas e persistentes já exigidas; extrair novas abstrações quando houver necessidade concreta

B) Criar ports entre todos os módulos para permitir futura separação em serviços

C) Otimizar somente para a v1, permitindo dependências diretas inclusive sobre adapters concretos

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 7 - Layout greenfield do código

Qual estrutura Python deve orientar Code Generation?

A) `src/novel_translator/` com módulos por capacidade e `tests/` espelhando o package

B) `src/` com diretórios somente por camada técnica e `tests/` agrupado por tipo de teste

C) Package diretamente na raiz, sem layout `src/`

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Decomposição consolidada para aprovação

### Unit of Work

Será gerada uma única unidade implantável: `novel-translator-cli`. Ela corresponde ao único processo e package distribuível da v1. Os limites internos serão módulos, não serviços ou packages independentes.

### Módulos internos propostos

| Módulo | Responsabilidade principal |
|---|---|
| `shared` | Tipos fundamentais, erros, hashing, relógio/IDs como ports e configuração tipada. |
| `workspace` | Run lifecycle, snapshots, `run.json`, eventos editoriais e ponteiro atual. |
| `source` | Entrada local, registry de readers e extração Kakuyomu. |
| `translation` | Bible, contexto, chunking, prompt, gateway, retry e caso de uso de tradução. |
| `editorial` | Manifesto, aprovação, integridade, export plan e contrato `novels-site`. |
| `cli` | Commands, apresentação, interatividade e exit codes. |
| `adapters` | Implementações concretas de filesystem, HTTP, provider, relógio e terminal, organizadas por port. |

`shared` será mínimo. Módulos de capacidade não importarão adapters concretos; o composition root fará o wiring.

### Sequência de desenvolvimento

1. Foundation: package, tipos, configuração, erros, ports e workspace básico.
2. Source e translation: ingestão, bible/contexto, run, provider, chunking e draft.
3. Editorial e export: aprovação, manifesto, integridade, rendering e escrita segura.
4. Hardening transversal: portabilidade, Unicode, falhas recuperáveis e obrigações PBT.

### Ownership

O ownership será documentado por camada técnica transversal: `domain`, `application` e `adapters`. Essa escolha orienta revisão e responsabilidade técnica, sem mudar as fronteiras dos módulos por capacidade nem criar Units of Work adicionais.

### Organização greenfield

```text
src/novel_translator/
tests/
config/
```

Dentro do package, módulos de capacidade conterão suas partes de domínio e aplicação; adapters ficarão explícitos nas bordas. `tests/` espelhará o package e separará testes unitários, de integração/contrato e property-based quando aplicável.

### Critérios de fronteira

- Somente integrações externas, persistência e utilitários substituíveis exigidos recebem ports.
- Não haverá comunicação de rede interna, plugin discovery ou abstrações preventivas entre todos os módulos.
- Cada história terá um módulo owner primário, ainda que use colaboradores de outros módulos.
- Dependências seguem `cli -> application -> domain/ports`, com adapters implementando ports via composition root.
- A geração deverá demonstrar ausência de ciclos e cobertura de US-001 a US-019.

## Critérios de conclusão do planejamento

- As sete respostas estão completas, válidas e não contraditórias.
- A quantidade de Units of Work segue o modelo de implantação aprovado.
- Todos os módulos têm responsabilidade e ownership claros.
- A sequência respeita dependências sem ciclos.
- A organização greenfield é compatível com as regras de Code Generation.
- Todas as 19 histórias poderão ser atribuídas exatamente uma vez como ownership primário.

## Extension Compliance

| Extensão                       | Estado nesta etapa  | Tratamento                                                           |
| ------------------------------ | ------------------- | -------------------------------------------------------------------- |
| Resiliency Baseline            | Desabilitada        | Não aplicada.                                                        |
| Security Baseline              | Desabilitada        | Não aplicada.                                                        |
| Property-Based Testing parcial | N/A no planejamento | As obrigações permanecem associadas aos módulos técnicos aplicáveis. |

## Validação de conteúdo

- Markdown, tabela, checkboxes e tags `[Answer]:` verificados.
- Cada pergunta possui opções distinguíveis e “Other” como última opção.
- Não há Mermaid, JSON, YAML ou diagrama ASCII neste plano.
