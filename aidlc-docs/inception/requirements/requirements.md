# Requisitos da v1 - Novel Translator

## 1. Resumo da análise de intenção

- **Solicitação**: desenvolver, com AI-DLC, a aplicação descrita em `REQUIREMENTS.md`.
- **Tipo**: novo projeto.
- **Classificação**: greenfield.
- **Escopo estimado**: múltiplos componentes internos e duas integrações externas.
- **Complexidade estimada**: moderada.
- **Profundidade da análise**: padrão.
- **Objetivo**: criar uma CLI em Python para tradução assistida por LLM de capítulos de web novels japonesas para inglês, com contexto por obra, rastreabilidade, aprovação e exportação desacoplada da publicação.

## 2. Contexto e fronteiras do produto

### 2.1 Responsabilidade do `novel-translator`

O sistema é responsável por:

- receber texto japonês por arquivo local ou URL suportada;
- validar e carregar a translation bible da obra;
- construir o contexto e o prompt de tradução;
- dividir capítulos que excedam a capacidade de uma única chamada;
- chamar um provider LLM configurável;
- preservar fontes, prompts, respostas, drafts e metadados;
- permitir aprovação humana;
- exportar conteúdo aprovado no formato do `gregori/novels-site`.

### 2.2 Responsabilidade do `novels-site`

O site é responsável por:

- armazenar conteúdo editorial aprovado;
- validar suas coleções de conteúdo Astro;
- gerar o site estático;
- publicar o conteúdo.

O `novel-translator` não deve disparar build, commit, push ou publicação automática do site na v1.

### 2.3 Atores

- **Tradutor/operador**: configura a obra, inicia traduções, inspeciona drafts, aprova e exporta.
- **Provider LLM**: recebe o contexto e a fonte e devolve texto traduzido.
- **Site de origem**: fornece o capítulo japonês quando uma URL suportada é usada.
- **`novels-site`**: recebe o Markdown e os metadados editoriais exportados.

## 3. Decisões confirmadas

- A aplicação será uma CLI em Python.
- As novels serão definidas por arquivos YAML; não haverá comando obrigatório de cadastro.
- A CLI oferecerá operações separadas de tradução, aprovação e exportação.
- Uma exportação poderá aprovar interativamente um draft ainda não aprovado.
- A entrada poderá ser arquivo local UTF-8 ou URL, começando por `kakuyomu.jp`.
- Cada execução será imutável e terá identificador único; um ponteiro separado poderá indicar o draft atual.
- A integração inicial com OpenCode Go será feita por API HTTP compatível com OpenAI.
- Configuração não sensível ficará em TOML ou YAML.
- Segredos poderão vir de variáveis de ambiente ou arquivo `.env` ignorado pelo Git.
- O sistema preservará snapshots completos e hashes, sem registrar segredos.
- Falhas transitórias terão retries automáticos limitados e auditados.
- As plataformas oficialmente suportadas serão Windows e macOS.
- Campos desconhecidos na translation bible serão rejeitados.
- Capítulos grandes serão divididos e recompostos automaticamente.
- Metadados editoriais ficarão em manifesto YAML separado da translation bible.
- A data de publicação padrão será a data da exportação.
- O volume terá precedência: argumento da CLI, metadado extraído da origem, campo omitido.

## 4. Requisitos funcionais

### 4.1 CLI e configuração

#### FR-CLI-001 - Interface por linha de comando

O sistema deve fornecer uma CLI com operações distintas para, no mínimo:

- traduzir um capítulo;
- aprovar um draft sem necessariamente exportá-lo;
- exportar um draft aprovado;
- consultar o resultado e o status de uma execução.

#### FR-CLI-002 - Identificação da entrada

O comando de tradução deve receber explicitamente:

- identificador ou slug da novel;
- identificador do capítulo;
- título do capítulo em inglês;
- uma fonte, representada por caminho de arquivo ou URL;
- volume opcional.

#### FR-CLI-003 - Configuração não sensível

Provider, modelo, endpoint, parâmetros do modelo, limites de retry, timeout, diretórios e outras opções não sensíveis devem ser configuráveis em TOML ou YAML, sem alterar a lógica de tradução.

#### FR-CLI-004 - Segredos

Tokens e chaves devem ser lidos de variáveis de ambiente. Um arquivo `.env` local e ignorado pelo Git poderá alimentar essas variáveis. Segredos não devem ser persistidos nos artefatos de execução.

### 4.2 Translation bible

#### FR-BIB-001 - Bible por obra

Cada novel deve possuir uma translation bible YAML própria.

#### FR-BIB-002 - Conteúdo mínimo do schema

O schema deve representar:

- título da obra;
- idioma de origem e destino;
- versão opcional da bible;
- personagens;
- nomes e aliases;
- terminologia recorrente;
- regras de honoríficos;
- convenções de nomes;
- instruções gerais de estilo.

#### FR-BIB-003 - Validação estrita

A bible deve ser validada antes de qualquer chamada ao LLM. Campos obrigatórios ausentes, tipos inválidos, referências incoerentes ou campos desconhecidos devem produzir erro claro e impedir a tradução.

#### FR-BIB-004 - Contexto de tradução

O sistema deve transformar a bible validada em contexto determinístico, apropriado ao prompt e independente do provider escolhido.

### 4.3 Ingestão da fonte

#### FR-ING-001 - Arquivo local

O sistema deve aceitar um arquivo UTF-8 contendo um capítulo japonês, validar que seja legível e preservar uma cópia imutável do conteúdo utilizado.

#### FR-ING-002 - URL suportada

O sistema deve aceitar uma URL de origem suportada e preservar:

- a URL solicitada;
- o conteúdo japonês extraído;
- os metadados relevantes encontrados;
- o instante da captura;
- informações suficientes para identificar o extrator utilizado.

#### FR-ING-003 - Kakuyomu

A v1 deve implementar um extrator para páginas de capítulo de `kakuyomu.jp`. O extrator deve distinguir URLs não suportadas, páginas ausentes e alterações incompatíveis na estrutura do site.

#### FR-ING-004 - Identidade do capítulo

Novel e capítulo informados pela CLI são a identidade canônica da execução. Metadados extraídos da URL podem complementar a execução, mas não devem trocar silenciosamente essa identidade.

### 4.4 Prompt e tradução

#### FR-TRN-001 - Construção do prompt

O sistema deve construir o prompt a partir de:

- template versionado;
- contexto determinístico derivado da bible;
- texto japonês do capítulo ou segmento;
- instruções necessárias para preservar continuidade entre segmentos.

#### FR-TRN-002 - Abstração de LLM

A lógica de tradução não deve depender de SDK, modelo ou provider específico. A camada de LLM deve expor um contrato interno que permita trocar provider, endpoint e modelo por configuração.

#### FR-TRN-003 - OpenCode Go

A v1 deve fornecer um adaptador HTTP para OpenCode Go usando uma API compatível com OpenAI. Endpoint, modelo, credencial, timeout e parâmetros suportados devem ser configuráveis.

#### FR-TRN-004 - Divisão de capítulos

Quando o capítulo completo não couber com segurança na janela de contexto configurada, o sistema deve:

- dividi-lo automaticamente em segmentos ordenados;
- preservar a ordem e todo o conteúdo da fonte;
- incluir o contexto necessário em cada chamada;
- impedir perda ou duplicação silenciosa de segmentos;
- recompor um único draft na ordem original;
- registrar a estratégia e os limites usados.

#### FR-TRN-005 - Retries

Falhas classificadas como transitórias devem receber número limitado e configurável de retries. Cada tentativa deve ser registrada. Falhas permanentes, esgotamento dos retries ou interrupção devem encerrar a execução com status explícito, preservando os artefatos já obtidos.

#### FR-TRN-006 - Draft sem publicação

Uma tradução concluída deve ser armazenada como draft. A conclusão da tradução não aprova, exporta ou publica automaticamente o conteúdo.

### 4.5 Workspace e histórico

#### FR-RUN-001 - Execução imutável

Cada tentativa de tradução deve criar uma execução com identificador único. Artefatos de execuções anteriores não podem ser sobrescritos silenciosamente.

#### FR-RUN-002 - Draft atual

O sistema poderá manter um ponteiro ou índice mutável indicando o draft atual de um capítulo, sem alterar os diretórios imutáveis das execuções.

#### FR-RUN-003 - Snapshots auditáveis

Cada execução deve preservar, excluindo segredos:

- fonte normalizada utilizada;
- translation bible ou contexto exato utilizado;
- prompt renderizado de cada chamada;
- requisição serializável enviada ao provider;
- resposta recebida;
- segmentos intermediários, quando houver;
- draft recomposto;
- hashes e versões;
- parâmetros e métricas disponibilizadas pelo provider.

#### FR-RUN-004 - `run.json`

Cada execução deve gerar `run.json` contendo pelo menos:

- `run_id`;
- `novel`;
- `chapter`;
- `source_type`;
- `source_uri` ou referência local;
- `source_hash`;
- `model`;
- `provider`;
- `provider_endpoint_id` não sensível;
- `model_parameters` não sensíveis;
- `prompt_version`;
- `prompt_hash`;
- `translation_bible_version`, quando disponível;
- `translation_bible_hash`;
- `chunking_strategy` e quantidade de segmentos;
- timestamps de início e término;
- tentativas e falhas observadas;
- métricas disponibilizadas pelo provider;
- `execution_status`.

#### FR-RUN-005 - Estados da execução

O modelo de estados deve distinguir, no mínimo:

- iniciada;
- em tradução;
- concluída com draft;
- falha;
- interrompida.

Aprovação e exportação devem ser eventos ou estados editoriais separados do status técnico da tradução.

### 4.6 Aprovação

#### FR-APR-001 - Aprovação explícita

O sistema deve permitir aprovar explicitamente um draft, registrando:

- execução aprovada;
- timestamp;
- identidade opcional do aprovador;
- hash do draft aprovado.

#### FR-APR-002 - Aprovação durante exportação

Ao exportar um draft ainda não aprovado em uma sessão interativa, a CLI deve solicitar confirmação e registrar a aprovação antes de escrever o arquivo de destino. Em execução não interativa, draft não aprovado deve causar falha, salvo quando houver opção explícita e auditável autorizando aprovação.

#### FR-APR-003 - Integridade após aprovação

Se o conteúdo do draft mudar após a aprovação, o hash deve deixar de corresponder e uma nova aprovação deve ser exigida.

### 4.7 Manifesto editorial

#### FR-EDT-001 - Separação de responsabilidades

Cada novel deve possuir um manifesto editorial YAML separado da translation bible. A bible governa tradução e consistência; o manifesto governa exportação e publicação.

#### FR-EDT-002 - Campos editoriais

O manifesto deve representar os campos exigidos pelo contrato atual do `novels-site`:

- `title`;
- `originalAuthor`;
- `categories` como lista de strings não vazias;
- `status` com um dos valores `ongoing`, `completed`, `paused` ou `dropped`;
- `synopsis`;
- `coverImage` apontando para uma imagem disponível para exportação;
- `credits`.

#### FR-EDT-003 - Validação editorial

O manifesto e o arquivo de capa devem ser validados antes da criação ou atualização do `index.md` da obra.

### 4.8 Exportação para `novels-site`

#### FR-EXP-001 - Contrato versionado

O exportador deve implementar o contrato observado no branch `main` de [`gregori/novels-site`](https://github.com/gregori/novels-site/tree/d2038d7669cac1db8687ba61828bde0f57ce3ddc), commit `d2038d7669cac1db8687ba61828bde0f57ce3ddc`.

#### FR-EXP-002 - Estrutura da obra

O exportador deve criar ou atualizar:

```text
src/content/titles/<novel-slug>/index.md
src/content/titles/<novel-slug>/<chapter-file>.md
src/content/titles/<novel-slug>/<cover-file>
```

O slug deve usar letras minúsculas e hífens. O nome do capítulo deve ordenar corretamente por sequência, usando zero-padding suficiente para a numeração adotada.

#### FR-EXP-003 - Frontmatter da obra

O `index.md` deve usar os campos validados do manifesto editorial e formato compatível com o schema Astro do site.

#### FR-EXP-004 - Frontmatter do capítulo

O Markdown de capítulo deve conter:

- `chapterTitle`, informado no comando de tradução e preservado no workspace;
- `publishDate`, usando por padrão a data da exportação;
- `volume`, inteiro positivo e opcional.

#### FR-EXP-005 - Precedência do volume

O volume exportado deve usar a seguinte precedência:

1. valor explícito informado pela CLI para o capítulo;
2. valor extraído de metadado confiável da fonte;
3. ausência do campo.

Valores conflitantes ou inválidos devem gerar diagnóstico e nunca ser resolvidos silenciosamente.

#### FR-EXP-006 - Escrita segura

Antes de escrever, o exportador deve validar o destino e detectar colisões. Arquivo existente com conteúdo diferente não pode ser sobrescrito silenciosamente; a CLI deve falhar ou exigir confirmação explícita e auditável.

#### FR-EXP-007 - Sem publicação automática

A exportação deve somente escrever os artefatos compatíveis no checkout configurado do `novels-site`. Ela não deve executar Git, build Astro ou deployment.

## 5. Requisitos não funcionais

### NFR-001 - Portabilidade

A CLI deve funcionar oficialmente em Windows e macOS, sem depender de caminhos, shell ou separadores específicos de uma plataforma.

### NFR-002 - Manutenibilidade

Ingestão, validação, construção de contexto, chunking, tradução, persistência, aprovação e exportação devem ter responsabilidades separadas e interfaces testáveis.

### NFR-003 - Substituição de provider

Adicionar ou trocar provider e modelo não deve exigir mudança na lógica de ingestão, construção de contexto, workspace, aprovação ou exportação.

### NFR-004 - Observabilidade local

A CLI deve informar progresso, identificador da execução, tentativas, falhas e caminhos dos artefatos sem expor segredos ou despejar conteúdo sensível por padrão.

### NFR-005 - Confiabilidade dos artefatos

Escritas de metadados, ponteiros e arquivos exportados devem evitar estados parcialmente gravados. Falhas devem deixar diagnóstico e estado recuperável ou claramente inválido.

### NFR-006 - Segurança mínima de segredos

Credenciais não devem aparecer em logs, prompts persistidos, `run.json`, mensagens de erro ou arquivos destinados ao Git. O uso da extensão completa de segurança foi dispensado para a v1, sem dispensar este requisito básico.

### NFR-007 - Codificação e Unicode

Entradas, snapshots, YAML, JSON, prompts e Markdown devem preservar corretamente UTF-8, incluindo japonês e caracteres tipográficos ingleses.

### NFR-008 - Desempenho

Não há SLA de latência para a v1. O sistema deve evitar chamadas duplicadas desnecessárias, aplicar timeout configurável e apresentar progresso em operações que dependam de rede.

### NFR-009 - Testabilidade

Chamadas HTTP, relógio, filesystem e providers devem poder ser substituídos por doubles de teste. Testes não devem exigir chamadas pagas reais para validar a lógica principal.

### NFR-010 - Testes baseados em propriedades

A extensão PBT está ativa em modo parcial. Devem ser aplicadas como restrições bloqueantes:

- PBT-02 para round-trips de serialização e desserialização;
- PBT-03 para invariantes documentados de funções puras;
- PBT-07 para geradores de domínio válidos e reutilizáveis;
- PBT-08 para shrinking e reprodução por seed;
- PBT-09 para seleção do framework Python Hypothesis.

As demais regras PBT são consultivas, não bloqueantes.

### NFR-011 - Idioma do código

Todo código-fonte deve ser escrito em inglês, incluindo identificadores e, quando fizerem sentido, comentários e docstrings.

### NFR-012 - Idioma da documentação

Toda documentação produzida para o projeto deve ser escrita em português. Termos técnicos, nomes de formatos, APIs, comandos, identificadores e trechos de código podem permanecer em inglês quando essa for sua forma canônica.

## 6. Cenários principais

### SCN-001 - Tradução a partir de arquivo

1. O operador escolhe uma novel e um capítulo.
2. Informa título, caminho UTF-8 e volume opcional.
3. A aplicação valida configurações, bible e fonte.
4. Constrói o contexto, traduz e cria uma execução imutável.
5. O draft fica disponível, mas não aprovado.

### SCN-002 - Tradução a partir de Kakuyomu

1. O operador informa uma URL de capítulo de `kakuyomu.jp`.
2. A aplicação baixa e extrai fonte e metadados.
3. Preserva o snapshot extraído e sua proveniência.
4. Executa o mesmo fluxo de tradução usado para arquivo local.

### SCN-003 - Capítulo dividido

1. A aplicação determina que o prompt completo excederia o limite seguro.
2. Divide o capítulo em segmentos ordenados.
3. Traduz cada segmento, com retries transitórios quando necessário.
4. Recompõe o draft sem perda, duplicação ou reordenação.
5. Registra estratégia, segmentos, prompts e respostas.

### SCN-004 - Aprovação e exportação

1. O operador seleciona um draft.
2. Aprova previamente ou confirma a aprovação durante a exportação.
3. A aplicação valida o hash aprovado e o manifesto editorial.
4. Gera ou atualiza o `index.md`, copia a capa e escreve o capítulo Markdown.
5. Registra o evento de exportação sem publicar o site.

### SCN-005 - Falha transitória do provider

1. Uma chamada recebe falha classificada como transitória.
2. A aplicação executa retries limitados.
3. Todas as tentativas são registradas.
4. Se o limite for esgotado, a execução termina como falha sem destruir artefatos anteriores.

## 7. Casos de erro e borda

O sistema deve tratar explicitamente:

- bible ou manifesto inexistente, inválido ou com campo desconhecido;
- encoding inválido ou arquivo vazio;
- URL malformada, host não suportado, página ausente ou estrutura não reconhecida;
- capítulo grande com falha em um segmento intermediário;
- resposta vazia ou inválida do provider;
- timeout, rate limit e indisponibilidade transitória;
- credencial ausente sem revelar seu valor;
- conflito entre volume explícito e extraído;
- tentativa de aprovar draft alterado;
- destino de exportação incorreto ou fora do checkout configurado;
- colisão com arquivo de capítulo ou capa já existente;
- falha de escrita sem sobrescrita parcial silenciosa.

## 8. Critérios de aceite consolidados

### AC-001

Dada uma translation bible YAML válida, a CLI deve carregá-la e construir contexto de tradução determinístico.

### AC-002

Dado um arquivo japonês UTF-8 válido, a CLI deve criar um draft inglês por meio do provider configurado.

### AC-003

Dada uma URL válida de capítulo do Kakuyomu, a CLI deve extrair e preservar o texto japonês antes da tradução.

### AC-004

Dado um capítulo maior que o limite seguro, a CLI deve dividi-lo, traduzir todos os segmentos e recompor um draft ordenado sem perda ou duplicação detectável.

### AC-005

Cada execução deve criar um diretório ou registro imutável único e um `run.json` com todos os campos mínimos especificados.

### AC-006

Snapshots, hashes, parâmetros, tentativas e métricas disponíveis devem permitir auditar exatamente o material enviado e recebido, sem persistir segredos.

### AC-007

Trocar provider, endpoint ou modelo por configuração não deve alterar a lógica do tradutor.

### AC-008

A v1 deve traduzir por OpenCode Go através do adaptador HTTP compatível com OpenAI.

### AC-009

Um draft concluído não deve ser exportado ou publicado automaticamente.

### AC-010

Um draft aprovado e íntegro deve ser exportado como Markdown aceito pelo schema atual do `novels-site`, com `chapterTitle`, `publishDate` e `volume` opcional.

### AC-011

Um manifesto editorial válido deve permitir criar ou atualizar o `index.md` e disponibilizar a capa exigida pela obra no destino.

### AC-012

Exportar um draft não aprovado deve exigir confirmação interativa ou autorização explícita em modo não interativo, registrando a aprovação.

### AC-013

Execuções anteriores e arquivos existentes no destino não devem ser sobrescritos silenciosamente.

### AC-014

Os fluxos suportados devem funcionar em Windows e macOS.

### AC-015

Testes com Hypothesis devem verificar round-trips de serialização, invariantes de funções puras e reprodutibilidade de falhas conforme o modo PBT parcial.

### AC-016

Código, identificadores, comentários e docstrings produzidos para a aplicação devem estar em inglês, ressalvados dados de domínio e conteúdo traduzido.

### AC-017

Documentação do projeto deve estar em português, preservando em inglês apenas termos e elementos cuja forma técnica canônica assim exigir.

## 9. Fora do escopo da v1

- revisão automática;
- múltiplos agentes;
- RAG, embeddings ou vector database;
- memória de longo prazo;
- interface web;
- publicação automática;
- execução automática de Git no `novels-site`;
- suporte genérico a qualquer site de web novel;
- certificação de segurança ou resiliência para produção;
- Linux como plataforma oficialmente suportada nesta versão.

## 10. Rastreabilidade

| Origem | Requisitos derivados |
|---|---|
| `REQUIREMENTS.md` | FR-CLI-001, FR-BIB-001 a FR-BIB-004, FR-TRN-001 a FR-TRN-003, FR-RUN-001 a FR-RUN-005, FR-EXP-007 |
| Respostas Q1 a Q5 | FR-CLI-001 a FR-CLI-004, FR-RUN-001, FR-TRN-002, FR-TRN-003 |
| Respostas Q7 a Q12 | FR-APR-001 a FR-APR-003, FR-RUN-003, FR-TRN-004, FR-TRN-005, NFR-001 |
| Esclarecimento de ingestão | FR-ING-001 a FR-ING-004 |
| Inspeção de `novels-site` e esclarecimentos editoriais | FR-EDT-001 a FR-EDT-003, FR-EXP-001 a FR-EXP-007 |
| PBT parcial | NFR-010, AC-015 |
| Restrições técnicas adicionadas após User Stories | NFR-011, NFR-012, AC-016, AC-017 |

## 11. Configuração das extensões

| Extensão | Estado | Aplicação nesta etapa |
|---|---|---|
| Resiliency Baseline | Desabilitada | Regras não carregadas nem aplicadas |
| Security Baseline | Desabilitada | Regras não carregadas nem aplicadas |
| Property-Based Testing | Parcial | Nenhuma regra é diretamente aplicável à produção do documento de requisitos; PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09 tornam-se bloqueantes nas etapas de design, código e testes indicadas pelas regras da extensão |
