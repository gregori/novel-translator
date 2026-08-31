# User Stories da v1

## Convenções

- **Persona**: Operador de Tradução, nos contextos interativo, automatizado ou de manutenção definidos em `personas.md`.
- **Estrutura**: épicos por jornada/capacidade, com histórias verticais e um resultado observável por história.
- **Critérios**: comportamento em Given/When/Then e restrições transversais em lista separada.
- **Rastreabilidade**: cada história referencia requisitos funcionais (FR), não funcionais (NFR), cenários (SCN) e critérios consolidados (AC).

## EP-01 - Preparar a tradução

### US-001 - Carregar configuração sem expor segredos

Como Operador de Tradução, quero configurar provider, modelo e opções operacionais fora do código, para trocar o ambiente de tradução sem alterar meu fluxo nem expor credenciais.

**Contexto**: manutenção e automação.

**Critérios de aceite**

- **Cenário: configuração válida** - Given um arquivo TOML ou YAML válido e as credenciais disponíveis no ambiente ou em `.env` ignorado pelo Git, When inicio um comando, Then a CLI usa provider, modelo, endpoint, parâmetros, timeout, retries e diretórios configurados.
- **Cenário: credencial ausente** - Given uma credencial obrigatória ausente, When inicio uma operação que depende do provider, Then a CLI falha antes da chamada e identifica a variável ausente sem revelar valores sensíveis.
- **Cenário: troca de provider** - Given outra configuração compatível com o contrato interno, When troco provider, endpoint ou modelo, Then ingestão, contexto, workspace, aprovação e exportação permanecem inalterados.

**Restrições transversais**

- Segredos não aparecem em logs, mensagens, prompts persistidos ou `run.json`.
- A configuração é validável sem chamadas pagas reais.

**Rastreabilidade**: FR-CLI-003, FR-CLI-004, FR-TRN-002, FR-TRN-003; NFR-003, NFR-006, NFR-009; AC-007, AC-008.

### US-002 - Validar a translation bible e construir contexto

Como Operador de Tradução, quero validar a translation bible específica da novel antes de traduzir, para aplicar nomes, terminologia e estilo de forma consistente.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: bible válida** - Given uma bible YAML com título, idiomas, personagens, aliases, terminologia, honoríficos, convenções e estilo válidos, When preparo a tradução, Then a CLI produz contexto determinístico e independente do provider.
- **Cenário: bible inválida** - Given campo obrigatório ausente, tipo inválido, referência incoerente ou campo desconhecido, When preparo a tradução, Then a CLI apresenta erro claro e não chama o LLM.
- **Cenário: bible versionada** - Given versão opcional informada, When uma execução é criada, Then versão e hash da bible usada ficam associados à execução.

**Restrições transversais**

- YAML, nomes japoneses e caracteres tipográficos preservam UTF-8.
- Invariantes documentados da normalização e do contexto determinístico devem ser verificáveis por PBT.

**Rastreabilidade**: FR-BIB-001, FR-BIB-002, FR-BIB-003, FR-BIB-004, FR-RUN-003, FR-RUN-004; NFR-002, NFR-007, NFR-010; AC-001, AC-006, AC-015.

### US-003 - Validar os metadados editoriais da novel

Como Operador de Tradução, quero validar um manifesto editorial separado da bible, para preparar a exportação sem misturar regras de tradução e publicação.

**Contexto**: manutenção e interativo.

**Critérios de aceite**

- **Cenário: manifesto válido** - Given um manifesto com `title`, `originalAuthor`, categorias não vazias, status permitido, `synopsis`, `coverImage` e `credits`, When valido a novel para exportação, Then a CLI confirma que os metadados e a capa estão disponíveis.
- **Cenário: manifesto ou capa inválidos** - Given manifesto ausente/inválido ou capa indisponível, When preparo a exportação, Then a CLI bloqueia a escrita do `index.md` e informa cada problema acionável.

**Restrições transversais**

- Campos editoriais não alteram a construção do contexto de tradução.
- Texto e caminhos são tratados de forma portátil e em UTF-8.

**Rastreabilidade**: FR-EDT-001 a FR-EDT-003; NFR-001, NFR-002, NFR-007; AC-011.

## EP-02 - Adquirir a fonte

### US-004 - Ingerir um capítulo de arquivo local

Como Operador de Tradução, quero fornecer um arquivo japonês local, para traduzir exatamente o conteúdo que preparei.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: arquivo válido** - Given um arquivo UTF-8 legível e não vazio, When inicio a tradução, Then a CLI preserva uma cópia imutável do conteúdo usado e calcula seu hash.
- **Cenário: arquivo inválido** - Given caminho inexistente, arquivo vazio, ilegível ou encoding inválido, When inicio a tradução, Then a CLI falha antes do LLM com diagnóstico claro.

**Restrições transversais**

- O comportamento é equivalente em Windows e macOS.
- O snapshot preserva japonês e caracteres Unicode sem transformação silenciosa.

**Rastreabilidade**: FR-CLI-002, FR-ING-001, FR-RUN-003; NFR-001, NFR-007; SCN-001; AC-002, AC-005, AC-014.

### US-005 - Ingerir um capítulo do Kakuyomu

Como Operador de Tradução, quero fornecer uma URL de capítulo do Kakuyomu, para capturar e traduzir o original sem copiar o texto manualmente.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: página suportada** - Given uma URL válida de capítulo em `kakuyomu.jp`, When inicio a tradução, Then a CLI extrai o japonês e metadados relevantes e preserva URL, captura, instante e identidade do extrator.
- **Cenário: origem inválida** - Given URL malformada, host não suportado ou página ausente, When tento ingerir, Then a CLI distingue a causa e não cria um draft.
- **Cenário: estrutura incompatível** - Given uma página cuja estrutura não é reconhecida, When o extrator atua, Then a CLI falha explicitamente e preserva diagnóstico suficiente para manutenção.

**Restrições transversais**

- Progresso e timeout de rede são observáveis sem despejar o conteúdo por padrão.
- O snapshot extraído preserva UTF-8 e sua proveniência.

**Rastreabilidade**: FR-ING-002, FR-ING-003, FR-RUN-003, FR-RUN-004; NFR-004, NFR-007, NFR-008; SCN-002; AC-003, AC-005, AC-006.

### US-006 - Preservar identidade e resolver volume

Como Operador de Tradução, quero que a identidade informada por mim permaneça canônica e que o volume siga uma precedência explícita, para evitar catalogação silenciosamente incorreta.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: identidade canônica** - Given novel e capítulo informados na CLI e metadados divergentes na fonte, When a fonte é ingerida, Then a execução mantém os valores da CLI e registra os metadados extraídos sem substituir a identidade.
- **Cenário: precedência de volume** - Given volume explícito e/ou volume confiável extraído, When preparo a exportação, Then a CLI usa primeiro o valor explícito, depois o extraído e, na ausência de ambos, omite o campo.
- **Cenário: conflito ou valor inválido** - Given metadados conflitantes ou volume inválido, When a CLI resolve os dados, Then apresenta diagnóstico e não toma decisão silenciosa.

**Restrições transversais**

- A precedência e a preservação da identidade são invariantes cobertas por PBT com dados de domínio válidos.

**Rastreabilidade**: FR-CLI-002, FR-ING-004, FR-EXP-005; NFR-010; AC-010, AC-015.

## EP-03 - Produzir e acompanhar o draft

### US-007 - Iniciar uma execução imutável

Como Operador de Tradução, quero que cada tentativa tenha identidade e estado próprios, para nunca perder ou confundir resultados anteriores.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: nova tentativa** - Given uma solicitação de tradução válida, When a CLI inicia o trabalho, Then cria um `run_id` único e um local imutável sem sobrescrever outra execução do capítulo.
- **Cenário: evolução de estado** - Given uma execução iniciada, When ela avança ou termina, Then seu status distingue iniciada, em tradução, concluída com draft, falha e interrompida.
- **Cenário: metadados mínimos** - Given uma execução, When seu estado é persistido, Then `run.json` contém todos os campos mínimos definidos em FR-RUN-004 e não contém segredos.

**Restrições transversais**

- Serialização e desserialização do modelo de `run.json` têm propriedade de round-trip.
- Estados técnicos permanecem separados de aprovação e exportação.
- A CLI informa `run_id`, progresso e caminhos dos artefatos.

**Rastreabilidade**: FR-CLI-001, FR-RUN-001, FR-RUN-004, FR-RUN-005; NFR-004, NFR-005, NFR-006, NFR-010; AC-005, AC-006, AC-013, AC-015.

### US-008 - Gerar um draft pelo provider configurado

Como Operador de Tradução, quero traduzir a fonte com a bible e o provider configurado, para obter um draft inglês consistente sem acoplar meu fluxo a um modelo específico.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: tradução concluída** - Given fonte e bible válidas, When executo a tradução, Then a CLI renderiza um prompt versionado, chama o adaptador OpenCode Go compatível com OpenAI e armazena a resposta como draft inglês.
- **Cenário: resposta inválida** - Given resposta vazia ou incompatível do provider, When a chamada termina, Then a execução não é marcada como concluída com draft e registra a falha observada.
- **Cenário: separação editorial** - Given um draft concluído, When a tradução termina, Then nenhum evento de aprovação, exportação ou publicação ocorre automaticamente.

**Restrições transversais**

- Fonte, contexto, prompt, requisição serializável, resposta, hashes, parâmetros e métricas disponíveis são preservados sem segredos.
- Chamadas de rede têm timeout configurável e podem ser substituídas por doubles de teste.

**Rastreabilidade**: FR-TRN-001 a FR-TRN-003, FR-TRN-006, FR-RUN-003; NFR-003, NFR-007 a NFR-009; SCN-001, SCN-002; AC-002, AC-006 a AC-009.

### US-009 - Traduzir um capítulo maior que o limite seguro

Como Operador de Tradução, quero que capítulos grandes sejam segmentados e recompostos automaticamente, para obter um único draft completo e ordenado.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: segmentação necessária** - Given um prompt que excederia o limite seguro configurado, When a tradução começa, Then a CLI divide a fonte em segmentos ordenados, preserva cada segmento e inclui o contexto necessário em cada chamada.
- **Cenário: recomposição** - Given todos os segmentos traduzidos, When a CLI recompõe o draft, Then produz um único conteúdo na ordem original sem segmento perdido, duplicado ou silenciosamente reordenado.
- **Cenário: rastreabilidade** - Given uma execução segmentada, When consulto seus artefatos, Then encontro estratégia, limites, quantidade, prompts, respostas e resultados intermediários.

**Restrições transversais**

- Divisão seguida de recomposição da fonte é uma propriedade de round-trip.
- Preservação de ordem, cobertura integral e unicidade dos segmentos são invariantes verificadas por PBT.
- Geradores incluem capítulos vazios inválidos, limites exatos, Unicode e capítulos grandes válidos.

**Rastreabilidade**: FR-TRN-004, FR-RUN-003, FR-RUN-004; NFR-007, NFR-008, NFR-010; SCN-003; AC-004, AC-006, AC-015.

### US-010 - Tratar falhas transitórias e interrupções

Como Operador de Tradução, quero retries limitados e estados finais explícitos, para distinguir recuperação automática de uma falha que exige nova ação.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: falha transitória recuperada** - Given timeout, rate limit ou indisponibilidade classificada como transitória, When ainda há tentativas, Then a CLI repete a chamada dentro do limite e registra cada tentativa.
- **Cenário: retries esgotados** - Given falhas transitórias até o limite, When a última tentativa falha, Then a execução termina como falha e preserva os artefatos obtidos.
- **Cenário: falha permanente ou interrupção** - Given erro permanente, falha de segmento ou interrupção, When a execução encerra, Then não há retry indevido, o status é explícito e nenhum draft incompleto vira draft concluído.

**Restrições transversais**

- Limite, timeout e classificação são configuráveis e observáveis.
- O mecanismo evita chamadas duplicadas depois de sucesso confirmado.

**Rastreabilidade**: FR-TRN-005, FR-RUN-003 a FR-RUN-005; NFR-004, NFR-005, NFR-008; SCN-003, SCN-005; AC-006, AC-013.

### US-011 - Consultar status, draft atual e auditoria

Como Operador de Tradução, quero consultar uma execução e o draft atual do capítulo, para entender o resultado sem alterar o histórico.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: consulta por execução** - Given um `run_id`, When consulto o resultado, Then a CLI mostra status, tentativas, falhas e caminhos relevantes sem exibir segredos ou conteúdo sensível por padrão.
- **Cenário: draft atual** - Given múltiplas execuções do capítulo, When consulto o draft atual, Then um ponteiro mutável identifica a execução escolhida sem modificar seus artefatos imutáveis.
- **Cenário: auditoria** - Given uma execução concluída ou falha, When examino seu workspace, Then consigo identificar fonte, bible/contexto, prompts, requisições, respostas, segmentos, draft, hashes, versões e métricas disponíveis.

**Restrições transversais**

- Serialização dos registros auditáveis deve preservar round-trip quando houver operação inversa.
- Alterar o ponteiro atual nunca muda hashes ou conteúdo das execuções.

**Rastreabilidade**: FR-CLI-001, FR-RUN-002 a FR-RUN-005; NFR-004 a NFR-006, NFR-010; AC-005, AC-006, AC-013, AC-015.

## EP-04 - Governar a aprovação

### US-012 - Aprovar explicitamente um draft

Como Operador de Tradução, quero aprovar um draft específico, para registrar qual conteúdo revisado está elegível para exportação.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: aprovação válida** - Given um draft concluído, When executo a aprovação explícita, Then a CLI registra execução, timestamp, hash do draft e identidade opcional do aprovador.
- **Cenário: execução inelegível** - Given execução sem draft concluído, When tento aprová-la, Then a CLI rejeita a ação sem criar evento editorial.

**Restrições transversais**

- Aprovação é separada do status técnico da tradução.
- O hash aprovado é calculado sobre os bytes efetivamente elegíveis para exportação.

**Rastreabilidade**: FR-CLI-001, FR-APR-001, FR-RUN-005; SCN-004; AC-009, AC-010.

### US-013 - Aprovar com segurança durante a exportação

Como Operador de Tradução, quero confirmar a aprovação durante uma exportação interativa ou autorizá-la explicitamente em automação, para evitar exportação acidental de drafts não revisados.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: modo interativo** - Given um draft ainda não aprovado, When solicito exportação interativa, Then a CLI pede confirmação e registra a aprovação antes de escrever o destino.
- **Cenário: automação sem autorização** - Given draft não aprovado e sessão não interativa, When solicito exportação sem opção explícita, Then a CLI falha sem escrever arquivos.
- **Cenário: automação autorizada** - Given opção explícita e auditável de aprovação, When exporto em modo não interativo, Then a CLI registra a aprovação antes da escrita.

**Restrições transversais**

- A confirmação identifica a execução e a consequência da ação.
- Ausência de terminal interativo nunca implica consentimento.

**Rastreabilidade**: FR-APR-002; NFR-004, NFR-005; SCN-004; AC-012.

### US-014 - Invalidar aprovação de um draft alterado

Como Operador de Tradução, quero que alterações posteriores invalidem a aprovação anterior, para nunca exportar conteúdo diferente do que revisei.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: draft íntegro** - Given hash atual igual ao hash aprovado, When preparo a exportação, Then a aprovação permanece válida.
- **Cenário: draft alterado** - Given conteúdo atual diferente do conteúdo aprovado, When aprovo novamente ou exporto, Then a CLI detecta a divergência, rejeita a aprovação anterior e exige nova aprovação.

**Restrições transversais**

- A relação entre conteúdo e hash aprovado é uma invariante verificável por PBT.
- A aprovação anterior permanece no histórico de auditoria.

**Rastreabilidade**: FR-APR-003; NFR-005, NFR-010; SCN-004; AC-010, AC-013, AC-015.

## EP-05 - Entregar ao `novels-site`

### US-015 - Exportar metadados e capa da novel

Como Operador de Tradução, quero criar ou atualizar os artefatos da novel conforme o contrato versionado do `novels-site`, para que o capítulo pertença a uma obra válida.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: estrutura da obra** - Given manifesto e capa válidos, When exporto a novel, Then a CLI cria ou atualiza `src/content/titles/<novel-slug>/index.md` e disponibiliza a capa no diretório da obra.
- **Cenário: frontmatter** - Given os campos editoriais validados, When escreve `index.md`, Then o frontmatter contém o formato compatível com o schema Astro do contrato fixado em FR-EXP-001.
- **Cenário: slug** - Given a identidade da novel, When calcula o destino, Then usa slug em letras minúsculas e hífens.

**Restrições transversais**

- Markdown, frontmatter e textos editoriais preservam UTF-8.
- A escrita do índice e da capa participa da validação e da proteção contra estado parcial.

**Rastreabilidade**: FR-EDT-002, FR-EDT-003, FR-EXP-001 a FR-EXP-003; NFR-005, NFR-007; SCN-004; AC-010, AC-011, AC-013.

### US-016 - Exportar o capítulo aprovado em Markdown

Como Operador de Tradução, quero exportar um draft aprovado como capítulo Markdown, para entregá-lo no formato aceito pelo `novels-site`.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: capítulo válido** - Given draft aprovado e íntegro, When exporto, Then a CLI escreve o capítulo no diretório da novel com `chapterTitle`, `publishDate` padrão da exportação e `volume` inteiro positivo quando disponível.
- **Cenário: ordenação de arquivo** - Given a numeração do capítulo, When cria o nome, Then aplica zero-padding suficiente para ordenar corretamente a sequência adotada.
- **Cenário: metadados inválidos** - Given título ausente, data inválida ou volume inválido/conflitante, When preparo a escrita, Then a CLI falha antes de produzir capítulo incompatível.

**Restrições transversais**

- A renderização preserva o draft aprovado em UTF-8.
- Invariantes de precedência, slug, nome ordenável e campos opcionais são candidatas obrigatórias a PBT.

**Rastreabilidade**: FR-EXP-002, FR-EXP-004, FR-EXP-005; NFR-007, NFR-010; SCN-004; AC-010, AC-014, AC-015.

### US-017 - Escrever no destino sem sobrescrever nem publicar

Como Operador de Tradução, quero validar o checkout e colisões antes de exportar, para não destruir conteúdo nem acionar publicação fora do meu controle.

**Contexto**: interativo e automatizado.

**Critérios de aceite**

- **Cenário: destino seguro** - Given checkout configurado e arquivos sem conflito, When exporto, Then a CLI escreve apenas os artefatos previstos dentro de `src/content/titles`.
- **Cenário: destino inválido** - Given caminho incorreto ou fora do checkout configurado, When preparo a exportação, Then a CLI bloqueia toda escrita.
- **Cenário: colisão** - Given capítulo ou capa existente com conteúdo diferente, When tento exportar, Then a CLI falha ou exige confirmação explícita e auditável antes de substituir.
- **Cenário: limite de responsabilidade** - Given uma exportação concluída, When a operação termina, Then nenhum comando Git, build Astro ou deployment foi executado.

**Restrições transversais**

- Falha de escrita não deixa sobrescrita parcial silenciosa.
- Os caminhos do resultado são informados ao operador.

**Rastreabilidade**: FR-EXP-006, FR-EXP-007; NFR-004, NFR-005; SCN-004; AC-009, AC-013.

## EP-06 - Operar com confiança

### US-018 - Obter comportamento portátil e Unicode correto

Como Operador de Tradução, quero executar os mesmos fluxos em Windows e macOS preservando japonês e inglês, para mover meu trabalho entre ambientes sem corrupção ou ajustes específicos de shell.

**Contexto**: todos.

**Critérios de aceite**

- **Cenário: plataformas suportadas** - Given entradas equivalentes em Windows e macOS, When executo os fluxos suportados, Then a CLI aceita caminhos e separadores nativos e produz artefatos semanticamente equivalentes.
- **Cenário: Unicode extremo** - Given japonês, aliases, espaços, pontuação tipográfica e caracteres combinantes válidos, When dados percorrem YAML, JSON, prompt e Markdown, Then os caracteres são preservados em UTF-8.

**Restrições transversais**

- Não há dependência de comandos ou convenções exclusivas de um shell.
- Geradores PBT de domínio incluem Unicode, caminhos válidos das duas plataformas e limites de tamanho realistas.

**Rastreabilidade**: NFR-001, NFR-007, NFR-010; AC-014, AC-015.

### US-019 - Recuperar-se de falhas de persistência sem corromper artefatos

Como Operador de Tradução, quero que metadados, ponteiros e exportações sejam gravados de forma recuperável, para confiar no estado relatado após uma falha local.

**Contexto**: todos.

**Critérios de aceite**

- **Cenário: escrita concluída** - Given uma atualização de metadado, ponteiro ou exportação, When a escrita termina com sucesso, Then o artefato completo e seu estado correspondente ficam observáveis.
- **Cenário: falha durante escrita** - Given falha de filesystem durante a operação, When a CLI encerra, Then não apresenta arquivo parcial como válido e deixa diagnóstico e estado anterior recuperável ou novo estado explicitamente inválido.
- **Cenário: testes sem efeitos reais** - Given doubles de filesystem, relógio, HTTP e provider, When os fluxos são testados, Then falhas e limites podem ser reproduzidos sem chamadas pagas nem alterar checkouts reais.

**Restrições transversais**

- Responsabilidades de ingestão, validação, contexto, chunking, tradução, persistência, aprovação e exportação permanecem separáveis e testáveis.
- Operações com inversa e invariantes documentadas usam Hypothesis com geradores reutilizáveis, shrinking ativo e seed reproduzível.
- Código-fonte, identificadores, comentários e docstrings são escritos em inglês quando aplicáveis.
- Documentação do projeto é escrita em português, preservando termos técnicos canônicos quando necessário.

**Rastreabilidade**: NFR-002, NFR-005, NFR-009, NFR-010, NFR-011, NFR-012; AC-013, AC-015, AC-016, AC-017.

## Verificação INVEST

| Story | Independent | Negotiable | Valuable | Estimable | Small | Testable |
|---|---|---|---|---|---|---|
| US-001 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-002 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-003 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-004 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-005 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-006 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-007 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-008 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-009 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-010 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-011 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-012 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-013 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-014 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-015 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-016 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-017 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-018 | Sim | Sim | Sim | Sim | Sim | Sim |
| US-019 | Sim | Sim | Sim | Sim | Sim | Sim |

Cada história possui um resultado observável, deixa solução interna negociável, cabe em uma unidade estimável de comportamento e contém critérios verificáveis. Dependências de dados entre histórias não exigem implementação conjunta.

## Matriz de rastreabilidade

| Origem | Stories |
|---|---|
| FR-CLI-001 a FR-CLI-004 | US-001, US-004, US-006, US-007, US-011, US-012 |
| FR-BIB-001 a FR-BIB-004 | US-002 |
| FR-ING-001 a FR-ING-004 | US-004 a US-006 |
| FR-TRN-001 a FR-TRN-006 | US-001, US-008 a US-010 |
| FR-RUN-001 a FR-RUN-005 | US-002, US-004, US-005, US-007 a US-011 |
| FR-APR-001 a FR-APR-003 | US-012 a US-014 |
| FR-EDT-001 a FR-EDT-003 | US-003, US-015 |
| FR-EXP-001 a FR-EXP-007 | US-006, US-015 a US-017 |
| NFR-001 | US-003, US-004, US-018 |
| NFR-002 | US-002, US-003, US-019 |
| NFR-003 | US-001, US-008 |
| NFR-004 | US-005, US-007, US-010, US-011, US-013, US-017 |
| NFR-005 | US-007, US-010, US-011, US-013 a US-015, US-017, US-019 |
| NFR-006 | US-001, US-007, US-011 |
| NFR-007 | US-002 a US-005, US-008, US-009, US-015, US-016, US-018 |
| NFR-008 | US-005, US-008 a US-010 |
| NFR-009 | US-001, US-008, US-019 |
| NFR-010 | US-002, US-006, US-007, US-009, US-011, US-014, US-016, US-018, US-019 |
| NFR-011 | US-019 e todos os artefatos de código posteriores |
| NFR-012 | US-019 e todos os artefatos documentais posteriores |
| SCN-001 | US-004, US-007, US-008, US-011 |
| SCN-002 | US-005, US-007, US-008 |
| SCN-003 | US-009, US-010 |
| SCN-004 | US-012 a US-017 |
| SCN-005 | US-010 |
| AC-001 a AC-003 | US-002, US-004, US-005, US-008 |
| AC-004 a AC-006 | US-005, US-007, US-009 a US-011 |
| AC-007 a AC-009 | US-001, US-008, US-012, US-017 |
| AC-010 a AC-012 | US-003, US-006, US-012 a US-016 |
| AC-013 a AC-015 | US-004, US-007, US-010, US-011, US-014 a US-019 |
| AC-016, AC-017 | US-019 |

## Obrigações PBT para etapas técnicas

| Rule | Aplicação rastreada |
|---|---|
| PBT-02 | Round-trips de modelos serializáveis, `run.json` e divisão/recomposição da fonte quando existirem pares de operações inversas. |
| PBT-03 | Invariantes de identidade, precedência de volume, estados, imutabilidade, aprovação por hash, chunking, nomes ordenáveis e normalização determinística. |
| PBT-07 | Estratégias reutilizáveis para bibles, manifestos, capítulos Unicode, metadados, runs, segmentos, estados e caminhos válidos. |
| PBT-08 | Shrinking do Hypothesis ativo; falhas registram exemplo mínimo e seed reproduzível; execução incluída em CI. |
| PBT-09 | Hypothesis é o framework Python obrigatório e deve integrar-se ao runner de testes escolhido. |

Estas obrigações complementam testes por exemplos derivados dos cenários Given/When/Then; não substituem os cenários críticos explícitos.

## Extension Compliance

| Extension | Status | Applicability |
|---|---|---|
| Resiliency Baseline | Disabled | Não aplicada; as decisões de retry existentes vêm dos requisitos aprovados. |
| Security Baseline | Disabled | Não aplicada; proteção mínima de segredos permanece coberta por NFR-006. |
| Property-Based Testing | Compliant | PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09 estão mapeadas para histórias e obrigações verificáveis nas etapas técnicas. Não há achado bloqueante nesta etapa. |
