# Clarificação do Functional Design — `novel-translator-cli`

## Ambiguidade identificada

Na Question 6 foi escolhida a opção B, “manter apenas a aprovação mais recente por run e hash”. O Application Design aprovado estabelece que eventos editoriais são append-only. É necessário esclarecer se “apenas a mais recente” se refere à projeção vigente ou à remoção do histórico.

## Clarification Question 1 — Histórico e projeção de aprovação

Como conciliar a aprovação mais recente com o histórico append-only?

A) Preservar todos os eventos; consultas e elegibilidade usam apenas a aprovação mais recente para o par `run_id + draft_hash`.

B) Substituir ou remover aprovações anteriores, mantendo fisicamente apenas o evento mais recente.

C) Preservar todos os eventos; qualquer aprovação existente para o hash atual torna o draft elegível, independentemente de ser a mais recente.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Validação de conteúdo

- Markdown e a tag `[Answer]:` foram verificados.
- As opções distinguem projeção, remoção de histórico e elegibilidade cumulativa.
- Não há Mermaid, diagrama ASCII, JSON ou YAML embutido.
