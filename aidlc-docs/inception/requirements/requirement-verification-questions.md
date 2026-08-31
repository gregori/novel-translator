# Verificação dos Requisitos da v1

Preencha cada campo `[Answer]:` com a letra da opção escolhida. Quando escolher `X`, descreva a decisão na mesma linha após a letra. As respostas serão incorporadas ao documento de requisitos e verificadas quanto a ambiguidades e contradições.

## Question 1

Qual deve ser o fluxo principal da CLI na v1?

A) Comandos separados para registrar/configurar a novel, traduzir, aprovar e exportar

B) Comandos separados apenas para traduzir, aprovar e exportar; a novel é definida diretamente por arquivos YAML no workspace

C) Um único comando executa tradução e exportação, mantendo a aprovação como confirmação interativa

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 2

Como a identidade do capítulo deve ser fornecida à tradução?

A) Por argumentos explícitos da CLI para novel e capítulo, além do caminho do arquivo fonte

B) Inferida da estrutura de diretórios e do nome do arquivo fonte

C) Lida de um cabeçalho de metadados contido no próprio arquivo fonte

X) Other (please describe after [Answer]: tag below)

[Answer]: X, entendo que o yaml + argumentos da linha de comando. Imagino o sistema buscando a fonte direto da web em alguns casos (por exemplo kakuyomu.jp).

## Question 3

Como os artefatos de múltiplas execuções do mesmo capítulo devem ser preservados?

A) Cada execução recebe um diretório imutável com identificador único; um ponteiro separado indica o draft atual

B) Cada execução recebe um arquivo com timestamp dentro do diretório do capítulo

C) Apenas a execução anterior é preservada como backup antes de uma nova tradução

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4

Qual mecanismo deve integrar o provider OpenCode Go na v1?

A) Invocar uma CLI local do OpenCode como subprocesso, usando a autenticação já configurada nessa ferramenta

B) Consumir diretamente uma API HTTP compatível com OpenAI, configurada com endpoint e credenciais do provider

C) Suportar ambos desde a v1 por adaptadores distintos

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 5

Como configurações e segredos devem ser fornecidos?

A) Configuração não sensível em arquivo TOML ou YAML, com segredos exclusivamente em variáveis de ambiente

B) Toda configuração por variáveis de ambiente

C) Configuração não sensível e segredos em arquivo local ignorado pelo Git

X) Other (please describe after [Answer]: tag below)

[Answer]: A, mas os segredos podem estar em um `.env` (ignorado pelo git) ou nas variáveis de ambiente

## Question 6

Qual contrato de exportação para `gregori/novels-site` deve orientar a v1?

A) Usar um exemplo ou especificação que será fornecido neste repositório antes do design

B) Inspecionar o repositório `gregori/novels-site` e implementar exatamente sua estrutura e frontmatter atuais

C) Criar um exportador configurável com um contrato Markdown mínimo nesta fase e adicionar o formato exato quando estiver disponível

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 7

Como um draft passa ao estado aprovado e fica elegível para exportação?

A) Por um comando explícito da CLI que registra aprovação, timestamp e identidade opcional do aprovador

B) Por edição manual do status em um arquivo de metadados

C) O comando de exportação solicita confirmação e registra a aprovação no mesmo ato

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 8

Quanto do material enviado ao LLM deve ser preservado para auditoria e reprodução?

A) Snapshot completo do prompt renderizado, contexto da bible, fonte e resposta, excluindo segredos

B) Apenas hashes, versões, parâmetros e referências aos arquivos de origem

C) Snapshot completo mais hashes, versões, parâmetros e métricas disponíveis do provider

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 9

Qual comportamento é esperado quando a chamada ao LLM falha ou é interrompida?

A) Registrar a execução como falha e exigir uma nova execução explícita, sem retries automáticos

B) Fazer retries automáticos limitados para falhas transitórias e registrar todas as tentativas

C) Salvar o estado parcial e oferecer retomada da mesma execução

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 10

Quais plataformas precisam ser suportadas oficialmente na v1?

A) Windows, Linux e macOS

B) Windows e Linux

C) Apenas o ambiente de desenvolvimento atual em Windows

X) Other (please describe after [Answer]: tag below)

[Answer]: X, windows e macOS

## Question 11

Como a validação da translation bible deve tratar campos desconhecidos?

A) Rejeitar campos desconhecidos para detectar erros de digitação e divergências de schema

B) Aceitar campos desconhecidos e preservá-los, permitindo extensão por novel

C) Aceitar campos desconhecidos com aviso, preservando-os sem usá-los no prompt da v1

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 12

Qual limite operacional deve orientar capítulos na v1?

A) Um arquivo UTF-8 deve caber integralmente na janela de contexto; exceder o limite gera erro claro antes da chamada

B) A aplicação deve dividir automaticamente capítulos grandes em partes e recompor o draft

C) Não impor validação prévia; o provider decide se aceita o conteúdo

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 13

O baseline de resiliência deve ser aplicado a este projeto?

Esta extensão oferece práticas direcionais de design para tolerância a falhas, observabilidade e recuperação. Ela é um ponto de partida, não uma certificação de prontidão para produção.

A) Sim - aplicar o baseline de resiliência como boas práticas direcionais e orientação de design

B) Não - dispensar o baseline de resiliência neste MVP

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 14

As regras da extensão de segurança devem ser obrigatórias neste projeto?

A) Sim - aplicar todas as regras do baseline de segurança como restrições bloqueantes

B) Não - dispensar as regras do baseline de segurança neste MVP

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 15

As regras de testes baseados em propriedades devem ser aplicadas neste projeto?

A) Sim - aplicar todas as regras de testes baseados em propriedades como restrições bloqueantes

B) Parcial - aplicá-las apenas a funções puras e ciclos de serialização e desserialização

C) Não - dispensar as regras de testes baseados em propriedades

X) Other (please describe after [Answer]: tag below)

[Answer]: B
