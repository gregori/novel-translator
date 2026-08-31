# Clarificação de NFR Requirements — `novel-translator-cli`

## Ambiguidade identificada

A resposta Q11=B escolhe retenção configurável por idade, mas não define o gatilho nem a proteção do histórico necessário para auditoria, aprovação e exportação.

## Clarification Question 1 — Política de retenção

Como a retenção por idade deve operar na v1?

A) Política desabilitada por padrão; limpeza somente por comando explícito com dry-run e confirmação; nunca remover o draft atual nem runs aprovados ou exportados.

B) Limpeza automática quando configurada; nunca remover o draft atual nem runs aprovados ou exportados.

C) Limpeza automática quando configurada; qualquer run terminal mais antigo que o limite pode ser removido.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Validação de conteúdo

- Markdown e a tag `[Answer]:` foram verificados.
- As opções distinguem gatilho explícito, automação e proteção do histórico editorial.
- Não há Mermaid, diagrama ASCII, JSON ou YAML embutido.
