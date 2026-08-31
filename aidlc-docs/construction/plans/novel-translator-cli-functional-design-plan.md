# Plano de Functional Design — `novel-translator-cli`

## Objetivo

Detalhar o comportamento de negócio, os modelos de domínio, as regras de validação e os fluxos da única unidade implantável da v1, sem decidir bibliotecas, SDKs ou recursos de infraestrutura.

## Contexto carregado

- Requisitos funcionais e não funcionais aprovados;
- 19 stories, atribuídas à unidade `novel-translator-cli`;
- arquitetura hexagonal leve e quatro casos de uso: traduzir, aprovar, exportar e inspecionar;
- módulos internos `shared`, `workspace`, `source`, `translation`, `editorial`, `cli` e `adapters`.

## Plano de execução

- [x] Analisar limites, responsabilidades, stories e dependências da unidade.
- [x] Identificar decisões funcionais ainda necessárias para modelos, fluxos e regras de negócio.
- [x] Registrar as perguntas de decisão abaixo.
- [x] Validar todas as respostas quanto a completude, ambiguidade e contradições.
- [x] Criar pergunta de esclarecimento para compatibilizar a resposta 6 com o histórico append-only.
- [x] Definir modelos e relações de domínio.
- [x] Definir fluxos de negócio, estados e transições.
- [x] Definir regras de validação, decisões e erros de negócio.
- [x] Registrar propriedades PBT aplicáveis.
- [x] Gerar e validar os três artefatos de Functional Design.
- [x] Atualizar este plano, estado e auditoria; solicitar aprovação do Functional Design.

## Decisões funcionais

## Question 1 — Schema da translation bible

Além dos campos obrigatórios, como a bible deve organizar personagens e terminologia na v1?

A) Personagens como lista de objetos com `canonical_name`, `aliases` e observações opcionais; terminologia como lista de objetos com origem, tradução preferida e notas opcionais.

B) Personagens e terminologia como mapas YAML indexados pelo nome canônico/origem.

C) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 2 — Regra de segmentação

Quando um capítulo exceder o limite seguro, qual regra deve determinar os segmentos?

A) Preferir quebras de parágrafo; se um parágrafo exceder o limite, quebrá-lo apenas em limites de sentença, preservando e recompondo exatamente todos os caracteres.

B) Dividir por quantidade fixa de caracteres, independentemente de parágrafos ou sentenças.

C) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 3 — Contexto entre segmentos

Qual continuidade deve ser enviada ao traduzir um segmento posterior?

A) Bible completa e contexto determinístico, mais um resumo curto gerado localmente a partir dos segmentos anteriores; não reenviar traduções completas anteriores.

B) Bible completa e a tradução completa do segmento imediatamente anterior.

C) Bible completa sem contexto adicional entre segmentos.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 4 — Reexecução da mesma identidade

Se o operador traduzir novamente a mesma combinação de novel e capítulo, qual deve ser a regra funcional?

A) Sempre criar uma nova execução imutável e atualizar o ponteiro de draft atual somente quando a nova tradução concluir com sucesso.

B) Recusar a nova execução enquanto já existir um draft concluído para a identidade.

C) Reutilizar a execução anterior se a fonte e a bible tiverem os mesmos hashes.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Question 5 — Conflitos de exportação

Quando o destino já contiver um arquivo diferente, como deve funcionar a confirmação explícita?

A) No modo interativo, mostrar os caminhos e exigir confirmação por arquivo; no modo não interativo, falhar salvo uma flag explícita de sobrescrita auditável.

B) No modo interativo, uma única confirmação cobre todas as colisões; no modo não interativo, falhar salvo flag explícita.

C) Nunca permitir sobrescrita, mesmo com confirmação.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Question 6 — Validade de aprovação

Como tratar mais de uma aprovação válida para o mesmo hash de draft?

A) Manter todos os eventos append-only; qualquer evento de aprovação para o hash atual torna o draft elegível, e nova aprovação explícita cria um novo evento.

B) Manter apenas a aprovação mais recente por run e hash.

C) Impedir nova aprovação enquanto existir aprovação válida para o mesmo hash.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Cobertura e conformidade

- O plano abrange os módulos `translation`, `workspace`, `editorial` e suas fronteiras de domínio.
- PBT parcial permanece obrigatório: PBT-02 (round-trips), PBT-03 (invariantes), PBT-07 (estratégias compartilhadas), PBT-08 (shrinking/reprodução) e PBT-09 (integração com o runner).
- Security Baseline e Resiliency Baseline estão desabilitadas no estado do projeto; seus requisitos funcionais aprovados continuam no escopo.

## Validação de conteúdo

- Markdown, checkboxes e seis tags `[Answer]:` foram verificados.
- Não há Mermaid, diagramas ASCII, JSON ou YAML embutidos.
