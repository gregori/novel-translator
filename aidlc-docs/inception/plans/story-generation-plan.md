# Story Generation Plan

## Objetivo

Converter os requisitos aprovados da v1 do Novel Translator em personas e histórias de usuário rastreáveis, pequenas e testáveis. As histórias cobrirão jornadas de CLI, cenários alternativos e falhas observáveis sem antecipar arquitetura, cronograma ou divisão em sprints.

## Fontes

- `REQUIREMENTS.md` - fonte autoritativa do escopo do produto.
- `aidlc-docs/inception/requirements/requirements.md` - requisitos analisados e aprovados, incluindo FRs, NFRs, cenários e critérios de aceite.
- `aidlc-docs/inception/plans/user-stories-assessment.md` - justificativa para executar esta etapa.
- Configuração de extensões em `aidlc-docs/aidlc-state.md`.

## Registro da Parte 1 - Planning

- [x] Avaliar e documentar a necessidade de user stories.
- [x] Analisar personas, jornadas, regras de negócio, integrações, NFRs e casos de erro presentes nos requisitos.
- [x] Comparar abordagens de decomposição e registrar uma recomendação.
- [x] Criar perguntas específicas para as decisões que afetam a qualidade das histórias.
- [x] Validar que todos os campos `[Answer]:` foram preenchidos.
- [x] Analisar respostas em busca de ambiguidades, combinações sem regra e contradições.
- [x] Resolver toda ambiguidade em arquivo de esclarecimento, se necessário (N/A: nenhuma ambiguidade ou contradição identificada).
- [x] Obter aprovação explícita deste plano antes da geração.

## Opções de decomposição

### A) Baseada em jornada

Segue tradução, consulta, aprovação e exportação de ponta a ponta. Favorece entendimento do fluxo do operador, mas pode repetir capacidades compartilhadas como configuração, validação e persistência.

### B) Baseada em funcionalidade

Agrupa CLI, ingestão, bible, tradução, workspace, aprovação e exportação. Facilita rastreabilidade funcional, mas pode fragmentar o valor percebido pelo usuário.

### C) Baseada em persona

Agrupa necessidades do operador, aprovador, automação e mantenedor. Evidencia responsabilidades, mas cria sobreposição quando mais de uma persona participa do mesmo fluxo.

### D) Baseada em domínio

Agrupa tradução, governança de execuções e entrega editorial. Mantém coesão das regras de negócio, mas precisa de mapas adicionais para mostrar jornadas completas.

### E) Baseada em épicos

Cria hierarquia de épicos e histórias. Dá boa visão de escopo, mas uma hierarquia excessiva pode esconder dependências e produzir histórias grandes.

### Recomendação inicial

Usar uma abordagem híbrida: épicos por jornada/capacidade de negócio e histórias verticais pequenas dentro de cada épico, com mapeamento explícito de personas e requisitos. Isso mantém a visão do fluxo sem transformar componentes internos em valor fictício para o usuário.

## Perguntas para fechar a metodologia

Preencha cada campo `[Answer]:` com a letra escolhida. Se escolher `X`, descreva a decisão na mesma linha. Todas as respostas precisam estar preenchidas antes da aprovação do plano.

## Question 1

Qual modelo de personas deve orientar as histórias da v1?

A) Uma persona principal, Operador de Tradução, executa tradução, aprovação e exportação; automação e manutenção aparecem apenas como contextos dessa persona

B) Três personas: Operador de Tradução, Responsável Editorial/Aprovador e Mantenedor da Ferramenta

C) Quatro personas: Operador de Tradução, Responsável Editorial/Aprovador, Consumidor de Automação não interativa e Mantenedor da Ferramenta

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2

Qual abordagem de decomposição deve ser usada em `stories.md`?

A) Híbrida recomendada: épicos por jornada/capacidade e histórias verticais pequenas, com referências cruzadas por persona e requisito

B) Jornada: histórias ordenadas estritamente pelos fluxos de tradução, consulta, aprovação e exportação

C) Funcionalidade/domínio: histórias agrupadas por CLI, ingestão, bible, tradução, workspace, aprovação e exportação

D) Persona: histórias agrupadas pelo usuário que recebe o valor

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3

Qual formato deve ser usado para os critérios de aceite de cada história?

A) Cenários Given/When/Then, incluindo fluxo principal e erros relevantes, com referências aos IDs de requisitos

B) Lista objetiva de condições verificáveis, com referências aos IDs de requisitos

C) Formato híbrido: Given/When/Then para comportamento e lista separada para restrições transversais, sempre com referências aos IDs

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 4

Como requisitos técnicos e não funcionais, como portabilidade, testabilidade, UTF-8 e proteção de segredos, devem aparecer nas histórias?

A) Como critérios transversais anexados apenas às histórias diretamente afetadas, mantendo uma matriz final de cobertura dos NFRs

B) Como histórias próprias atribuídas ao Mantenedor, mesmo quando não representam uma jornada de usuário final

C) Em ambos: critérios nas histórias afetadas e histórias habilitadoras separadas somente quando houver resultado observável e independente

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 5

Qual granularidade deve orientar a geração?

A) Histórias pequenas e implementáveis, cada uma com um único resultado observável; cenários alternativos permanecem na mesma história quando não entregam valor isoladamente

B) Histórias maiores por comando da CLI, reunindo todos os fluxos e erros do comando

C) Histórias muito pequenas por cenário de aceite, inclusive separando cada erro em uma história própria

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Decisões validadas

- **Personas**: uma persona principal, Operador de Tradução; automação e manutenção serão contextos operacionais, não personas independentes.
- **Decomposição**: épicos por jornada/capacidade, contendo histórias verticais pequenas e rastreáveis.
- **Critérios de aceite**: cenários Given/When/Then para comportamento e listas separadas para restrições transversais.
- **NFRs**: critérios nas histórias afetadas; histórias habilitadoras apenas quando houver resultado observável e independente.
- **Granularidade**: um resultado observável por história; alternativas sem valor isolado permanecem como cenários da história correspondente.
- **Análise de consistência**: todas as respostas são válidas, mutuamente compatíveis e suficientes para orientar a geração; não há esclarecimentos pendentes.

## Plano de geração - Parte 2

- [x] Ler e validar todas as respostas aprovadas deste plano.
- [x] Definir as personas escolhidas, seus objetivos, responsabilidades, contexto e pontos de dor.
- [x] Gerar `aidlc-docs/inception/user-stories/personas.md` e mapear cada persona às jornadas relevantes.
- [x] Decompor os requisitos em épicos e histórias conforme a abordagem e a granularidade aprovadas.
- [x] Escrever cada história no formato “Como [persona], quero [objetivo], para [valor]”.
- [x] Adicionar critérios de aceite no formato aprovado, cobrindo fluxo principal, alternativas e erros relevantes.
- [x] Adicionar rastreabilidade de cada história para FRs, NFRs, cenários e ACs aplicáveis.
- [x] Verificar cada história contra INVEST: Independent, Negotiable, Valuable, Estimable, Small e Testable.
- [x] Verificar a cobertura integral dos requisitos aprovados e registrar uma matriz de rastreabilidade em `stories.md`.
- [x] Verificar que PBT-02 e PBT-03 sejam sinalizadas nos critérios aplicáveis, sem transformar técnica de teste em requisito de usuário.
- [x] Verificar que futuras etapas contemplem geradores de domínio reutilizáveis, shrinking/reprodução por seed e Hypothesis conforme PBT-07, PBT-08 e PBT-09.
- [x] Validar Markdown, links internos, IDs, tabelas e todos os blocos de conteúdo antes de salvar os artefatos finais.
- [x] Atualizar imediatamente estes checkboxes e `aidlc-docs/aidlc-state.md` após cada passo concluído.

## Artefatos obrigatórios

- [x] Gerar `stories.md` com histórias que atendam aos critérios INVEST.
- [x] Gerar `personas.md` com arquétipos e características dos usuários.
- [x] Incluir critérios de aceite em todas as histórias.
- [x] Mapear personas às histórias relevantes.

## Limites desta etapa

- Não definir arquitetura, bibliotecas além das já exigidas, cronograma, sprints ou ordem de implementação.
- Não adicionar funcionalidades fora da v1 aprovada.
- Não tratar revisão automática, múltiplos agentes, RAG, embeddings, memória de longo prazo, interface web ou publicação automática como histórias da v1.

## Extension Compliance

| Extension              | Status    | Planning-stage applicability                                                                                                                                             |
| ---------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Resiliency Baseline    | Disabled  | Não aplicada; desabilitada em Requirements Analysis.                                                                                                                     |
| Security Baseline      | Disabled  | Não aplicada; desabilitada em Requirements Analysis.                                                                                                                     |
| Property-Based Testing | Compliant | O plano preserva PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09 como restrições das etapas técnicas aplicáveis; não há implementação ou design técnico a verificar nesta etapa. |
