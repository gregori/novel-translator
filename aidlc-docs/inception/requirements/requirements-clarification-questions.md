# Esclarecimentos dos Requisitos da v1

Foram identificadas duas ambiguidades nas respostas originais. Preencha cada campo `[Answer]:` com a letra escolhida. Quando escolher `X`, descreva a decisão na mesma linha após a letra.

## Ambiguidade 1: origem do capítulo na v1

Na Question 2, a resposta menciona tanto argumentos da CLI quanto a possibilidade de buscar a fonte diretamente em sites como `kakuyomu.jp`. O `REQUIREMENTS.md` atualmente limita a v1 ao recebimento de um arquivo com o capítulo.

### Clarification Question 1

Qual origem de conteúdo deve fazer parte da v1?

A) Somente arquivo local UTF-8; a CLI recebe novel, capítulo e caminho da fonte, deixando ingestão web para uma versão futura

B) Arquivo local ou URL; a v1 deve baixar capítulos diretamente da web, começando por `kakuyomu.jp`

C) Somente URL; a CLI baixa a fonte, sem exigir arquivo local fornecido pelo usuário

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Resposta inválida 2: contrato de exportação

Na Question 6, foi informado `[Answer]: Bs`, que não corresponde a nenhuma opção válida.

### Clarification Question 2

Qual opção confirma sua intenção para o contrato de exportação?

A) Confirmar a opção B original: inspecionar `gregori/novels-site` e implementar sua estrutura e frontmatter atuais

B) Adotar a opção C original: criar agora um contrato Markdown mínimo e configurável, adaptando-o futuramente

X) Other (please describe after [Answer]: tag below)

[Answer]: A
