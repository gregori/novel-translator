# Plano de Application Design

## Objetivo e contexto

Definir, em profundidade abrangente, componentes, contratos de alto nível, serviços, dependências e comunicação do `novel-translator`. A lógica detalhada será especificada em Functional Design por unidade.

- CLI local greenfield em Python para Windows e macOS.
- Entrada por arquivo UTF-8 ou Kakuyomu; bible e manifesto em YAML com validação estrita.
- LLM desacoplado; OpenCode Go por API HTTP compatível com OpenAI na v1.
- Runs imutáveis, snapshots, hashes, aprovação explícita e exportação segura para `novels-site`.
- Código em inglês e documentação em português.
- Security e Resiliency desabilitadas; PBT parcial preservado para etapas técnicas aplicáveis.

## Plano de execução

- [x] Reconciliar requisitos, persona, histórias, extensões e execution plan.
- [x] Avaliar ambiguidades de componentes, métodos, serviços, dependências e padrões.
- [x] Coletar todas as respostas abaixo.
- [x] Validar respostas quanto a completude, ambiguidade e contradição.
- [x] Avaliar perguntas de acompanhamento; não foram necessárias.
- [x] Gerar `components.md` com componentes, responsabilidades e interfaces.
- [x] Gerar `component-methods.md` com assinaturas, finalidades e tipos.
- [x] Gerar `services.md` com serviços e orquestração.
- [x] Gerar `component-dependency.md` com matriz, comunicação e fluxos de dados.
- [x] Gerar `application-design.md` consolidando os artefatos.
- [x] Validar rastreabilidade, consistência, conteúdo e extensões.
- [x] Atualizar plano, estado e audit log e solicitar aprovação explícita.

## Decisões de design

Preencha uma opção em cada `[Answer]:`. Ao escolher “Other”, descreva a decisão.

### Question 1 - Estilo arquitetural

Qual estrutura deve orientar os componentes internos?

A) Hexagonal leve: domínio e casos de uso no centro, ports nos contratos e adapters nas bordas

B) Camadas tradicionais: CLI, services, domain e infrastructure, abstraindo apenas integrações externas

C) Módulos por capacidade, agrupando domínio, serviço e adapter por área funcional

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 2 - Granularidade dos casos de uso

Como a camada de aplicação deve expor as jornadas?

A) Um caso de uso por operação: translate, approve, export e inspect

B) Um único facade com todas as operações

C) Serviços agrupados por domínio: translation, editorial e workspace

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 3 - Contratos internos

Qual forma deve ser usada nas entradas e saídas entre componentes?

A) Commands/queries e modelos tipados, preferencialmente imutáveis; conversão nas bordas

B) Primitivos e mappings simples; validação concentrada nos pontos de entrada

C) Modelos de schema compartilhados diretamente por todas as camadas

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 4 - Erros e resultados

Como falhas esperadas devem chegar à CLI?

A) Exceções tipadas convertidas centralmente em mensagens e exit codes estáveis

B) Objetos `Result` explícitos em todos os métodos que podem falhar

C) Híbrido: resultados para outcomes de negócio e exceções tipadas para falhas técnicas

D) Other (please describe after [Answer]: tag below)

[Answer]: C

### Question 5 - Lifecycle e persistência do run

Quem controla snapshots, estados e escrita final da tradução?

A) O caso de uso controla a sequência; um `RunRepository` oferece operações atômicas

B) Um componente dedicado de run lifecycle controla a máquina de estados

C) Cada componente persiste seus artefatos e um agregador monta o `run.json`

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 6 - Segmentos de capítulos grandes

Qual orquestração a v1 deve adotar?

A) Sequencial e determinística, propagando contexto entre segmentos

B) Paralela com concorrência limitada e segmentos independentes

C) Selecionável: sequencial por padrão e paralela opcional

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 7 - Seleção de adapters

Como providers de LLM e extratores devem ser resolvidos?

A) Registries/factories explícitas mapeiam nomes configurados para implementações de ports

B) Wiring estático no composition root com condicionais simples para a v1

C) Plugins e entry points com descoberta dinâmica desde a v1

D) Other (please describe after [Answer]: tag below)

[Answer]: A

### Question 8 - Eventos editoriais e projeções

Como aprovação, exportação e ponteiro de draft atual coexistem com runs imutáveis?

A) Eventos append-only com projeções reconstruíveis para todos os estados editoriais

B) Arquivos mutáveis separados por capítulo, escritos atomicamente e auditados

C) Híbrido: aprovação e exportação append-only; draft atual como ponteiro mutável atômico

D) Other (please describe after [Answer]: tag below)

[Answer]: C

## Critérios de conclusão

- As oito respostas estão completas, válidas e não contraditórias.
- Os cinco artefatos obrigatórios são gerados e validados.
- Componentes e serviços têm responsabilidade coesa, contratos explícitos e dependências sem ciclos indevidos.
- Tradução, consulta, aprovação e exportação permanecem rastreáveis e não sobrescrevem dados silenciosamente.

## Extension Compliance

| Extensão               | Estado          | Tratamento                                                      |
| ---------------------- | --------------- | --------------------------------------------------------------- |
| Resiliency Baseline    | Desabilitada    | Não aplicada conforme `aidlc-state.md`.                         |
| Security Baseline      | Desabilitada    | Não aplicada conforme `aidlc-state.md`.                         |
| Property-Based Testing | N/A nesta etapa | O modo parcial segue encaminhado às etapas técnicas aplicáveis. |

## Validação de conteúdo

- Markdown, headings, checkboxes, tabela e tags `[Answer]:` verificados.
- Cada pergunta possui opções distinguíveis e “Other” como última opção.
- Não há Mermaid, JSON, YAML ou diagrama ASCII neste plano.
