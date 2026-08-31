# Esclarecimentos do Contrato de Exportação

A inspeção do contrato atual de `gregori/novels-site` identificou metadados obrigatórios que ainda não possuem uma fonte definida. Preencha cada campo `[Answer]:` com a letra escolhida. Quando escolher `X`, descreva a decisão na mesma linha após a letra.

## Contexto verificado

No commit `d2038d7669cac1db8687ba61828bde0f57ce3ddc` do branch `main`, cada obra usa `src/content/titles/<slug>/index.md` com `title`, `originalAuthor`, `categories`, `status`, `synopsis`, `coverImage` e `credits`. Cada capítulo usa um arquivo Markdown ordenável com `chapterTitle`, `publishDate` e `volume` opcional.

## Question 1

Como a v1 deve tratar os metadados obrigatórios de uma obra no `novels-site`?

A) Exportar capítulos apenas para obras que já possuam diretório e `index.md` válidos no `novels-site`; a criação da página da obra fica fora do escopo

B) Ampliar a translation bible com todos os metadados editoriais e um caminho para a capa, permitindo criar ou atualizar também o `index.md`

C) Manter a translation bible focada na tradução e criar um manifesto editorial separado por obra para gerar o `index.md`

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 2

De onde devem vir `chapterTitle`, `publishDate` e o `volume` opcional no Markdown exportado?

A) De argumentos do comando de exportação; `chapterTitle` e `publishDate` são obrigatórios e `volume` é opcional

B) De um manifesto YAML do capítulo armazenado no workspace junto da fonte e dos drafts

C) `chapterTitle` é informado na tradução, `publishDate` assume a data da exportação e `volume` é opcional na exportação

X) Other (please describe after [Answer]: tag below)

[Answer]: C, sendo que volume pode vir da linha de comando, referente ao capítulo em questão a ser traduzido, ou, se informado no original, extrair de lá
