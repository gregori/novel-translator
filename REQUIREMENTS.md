# Novel Translator

Sistema para tradução assistida por LLM de web novels do japonês para o inglês, projetado para evoluir para uma pipeline agêntica de tradução, revisão e controle de consistência.

O sistema ingere o texto original, constrói o contexto de tradução a partir de uma translation bible específica da obra, gera uma tradução e, posteriormente, permitirá etapas adicionais de revisão.

O resultado final da pipeline deve poder ser exportado para o repositório `gregori/novels-site`, responsável exclusivamente pela publicação.

## Arquitetura de produto

`novel-translator`:

- ingestão do japonês;
- construção de contexto;
- tradução;
- revisão futura;
- exportação.

`novels-site`:

- conteúdo aprovado;
- geração do site Astro;
- publicação.

A pipeline de tradução e o site de publicação são sistemas separados.

## Escopo da v1

A v1 é um MVP de tradução.

Ela deve:

1. fornecer uma CLI;
2. carregar uma translation bible específica por novel;
3. receber um arquivo contendo um capítulo em japonês;
4. gerar um draft em inglês através de um LLM;
5. preservar informações suficientes sobre cada execução;
6. manter source, draft e metadados em um workspace;
7. exportar drafts aprovados para o formato Markdown esperado pelo `gregori/novels-site`.

## Fora do escopo da v1

A v1 não inclui:

- revisão automática;
- múltiplos agentes;
- RAG;
- embeddings;
- vector database;
- memória de longo prazo;
- interface web;
- publicação automática no `novels-site`.

Esses recursos poderão ser considerados em versões posteriores.

## Restrições técnicas

- A implementação deve ser em Python.
- A aplicação deve fornecer uma CLI.
- A camada de acesso a LLMs deve ser desacoplada do restante da aplicação.
- Deve ser possível trocar modelo e provider sem alterar a lógica de tradução.
- A v1 deve suportar OpenCode Go como provider.
- A escolha da biblioteca ou estratégia de abstração de LLM faz parte do design da solução.
- Artefatos de execuções anteriores não devem ser sobrescritos silenciosamente.
- Código em inglês, incluindo comentários/docstrings, quando fizerem sentido.
- Documentação em português.

## Critérios de aceite da v1

A v1 será considerada concluída quando:

1. O usuário puder definir uma novel por meio de uma translation bible em YAML.
2. O usuário puder fornecer um arquivo contendo um capítulo em japonês.
3. A aplicação validar e carregar a translation bible correspondente.
4. A aplicação construir o contexto de tradução a partir da bible.
5. O conteúdo do capítulo e o contexto de tradução forem enviados ao modelo configurado.
6. A tradução for armazenada como draft, sem publicação automática.
7. Forem registrados metadados suficientes para reproduzir e auditar a execução.
8. O draft puder ser exportado para um Markdown compatível com `gregori/novels-site`.
9. O provider e o modelo puderem ser trocados por configuração, sem alteração da lógica do tradutor.

## Metadados de execução

Cada tradução deve gerar um `run.json` contendo pelo menos:

- `novel`;
- `chapter`;
- `source_hash`;
- `model`;
- `provider`;
- `prompt_version`;
- `prompt_hash`;
- `translation_bible_version`, quando disponível;
- `translation_bible_hash`;
- `timestamp`;
- `execution_status`.

O formato exato e metadados adicionais podem ser definidos durante o design.

## Translation Bible

Cada novel deve possuir sua própria translation bible.

A bible deve poder representar, inicialmente:

- título da obra;
- idioma de origem e destino;
- personagens;
- nomes e aliases;
- terminologia recorrente;
- regras de honoríficos;
- convenções de nomes;
- instruções gerais de estilo.

O schema exato deve ser definido durante o design.

A aplicação deve validar a translation bible antes de iniciar uma tradução.
