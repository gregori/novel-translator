# Padrões de NFR — `novel-translator-cli`

## 1. Objetivo e princípios

Este desenho aplica os requisitos não funcionais aprovados à CLI local sem criar serviço residente ou infraestrutura de deployment. Os padrões priorizam histórico imutável, falha explícita, recuperação conservadora, memória limitada por segmento e isolamento das bordas técnicas.

Princípios transversais:

- operações mutáveis possuem um único owner por workspace;
- um estado só é publicado depois que seu artefato foi persistido e verificado;
- cada efeito externo é precedido por validação e por um plano sem efeitos;
- retries nunca ocultam falhas permanentes nem repetem sucesso confirmado;
- segredos não pertencem a modelos persistíveis;
- caminhos de exportação não atravessam symlinks, junctions ou a raiz autorizada;
- processamento de capítulos grandes é incremental, porém cada request e response do provider permanece uma unidade auditável.

## 2. Resiliência do workspace

### 2.1 Lock exclusivo com recuperação conservadora

`filelock` fornece o mecanismo cross-platform. O adapter mantém o arquivo de lock separado de um registro sanitizado de owner contendo versão do formato, PID, hostname não sensível, instante de aquisição e identificador da operação.

Comportamento:

1. comandos mutáveis tentam adquirir o lock sem espera por padrão;
2. `--lock-timeout` habilita espera limitada e cancelável;
3. falha de aquisição retorna diagnóstico acionável sem mutação;
4. um lock suspeito de abandono nunca é removido apenas por idade;
5. recuperação exige evidência de owner inexistente, revalidação imediatamente antes da ação e confirmação explícita;
6. dúvida ou falha de verificação preserva o lock.

Consultas read-only não adquirem o lock, mas leem somente arquivos promovidos atomicamente. Temporários, staging e inventários incompletos não integram projeções de leitura.

### 2.2 Persistência por prepare, persist, verify, publish

Toda publicação individual segue o mesmo protocolo:

1. serializar conteúdo canônico para temporário no mesmo filesystem;
2. flush e sincronização best-effort apropriada à plataforma;
3. verificar tamanho, parse e hash quando aplicável;
4. promover por replace atômico oferecido pela API Python;
5. verificar o artefato publicado;
6. somente então publicar estado ou ponteiro dependente.

Falhas anteriores à promoção removem apenas temporários próprios. Falhas posteriores mantêm diagnóstico e nunca avançam silenciosamente o estado lógico.

### 2.3 Transação compensável de exportação

Como o filesystem não oferece transação atômica multiarquivo, a exportação usa staging, inventário durável e compensação:

1. produzir `ExportPlan` completo e validar conteúdo, confinamento e colisões;
2. criar staging dentro do checkout e no mesmo filesystem dos destinos;
3. persistir inventário com destinos, hashes esperados, estado anterior e passos;
4. materializar e verificar todos os arquivos em staging;
5. promover cada item e registrar imediatamente o progresso no inventário;
6. em falha, executar rollback best-effort apenas sobre itens promovidos pela operação;
7. se o rollback não restaurar o conjunto, marcar reconciliação pendente e bloquear novas exportações;
8. após sucesso integral, registrar `ExportEvent` e remover staging recuperável.

Uma reconciliação explícita pode concluir ou reverter o plano após revalidar hashes. Ela nunca assume que um arquivo divergente pertence à transação.

### 2.4 Retry controlado

`RetryExecutor` aplica até três tentativas totais, timeout configurável e backoff exponencial com jitter injetável. A classificação de erro pertence à aplicação; o transport HTTP não adiciona retry oculto.

- timeout, indisponibilidade e rate limit explicitamente classificados podem ser transitórios;
- autenticação, request inválida, resposta semanticamente inválida e estrutura incompatível são permanentes;
- cada tentativa é snapshotada antes da decisão seguinte;
- sucesso confirmado encerra o executor;
- interrupção preserva artefatos e produz estado `interrupted`.

## 3. Escala local e memória

### 3.1 Pipeline incremental

A fonte é processada como stream nas etapas de aquisição, decodificação UTF-8 incremental, normalização, hashing, segmentação e snapshots. O sistema usa arquivos temporários controlados como spool quando uma fronteira requer releitura.

- o normalizador preserva equivalência textual definida e emite blocos ordenados;
- o hash é atualizado incrementalmente sobre os bytes canônicos;
- o segmentador mantém somente o buffer necessário para fechar parágrafo ou sentença;
- cada segmento é persistido e verificado antes de liberar o buffer anterior;
- request e response de um segmento podem residir em memória;
- o draft final é montado incrementalmente em temporário e promovido após validação de completude.

Uma sentença indivisível maior que o orçamento falha explicitamente. O streaming não altera a ordem sequencial das chamadas nem permite concluir draft parcial.

### 3.2 Estimativa de tokens extensível

`TokenEstimator` é um port do núcleo. Cada provider pode fornecer estimativa específica; na ausência dela, `ConservativeCharacterEstimator` usa limite configurável em caracteres e reserva explícita para template, bible, continuidade e resposta.

O `ContextBudgetPlanner` recebe a estimativa total, aplica margem de segurança e produz o orçamento de fonte por segmento. A estratégia e os valores usados integram `run.json`, permitindo reproduzir a decisão de chunking.

### 3.3 Gate de complexidade

Benchmarks usam uma série geométrica de entradas válidas e verificam a razão de crescimento para hashing, normalização, segmentação e serialização. O gate rejeita evidência compatível com comportamento quadrático sobre o capítulo completo.

Tempos absolutos são registrados somente como informação do ambiente. Não constituem SLA nem gate portátil. A suite de performance permanece separada dos testes funcionais e registra runtime, plataforma e tamanhos usados.

## 4. Segurança e privacidade local

### 4.1 Segredo fora do modelo persistível

Credenciais são representadas por tipos opacos resolvidos somente no composition root e nos adapters que delas necessitam. Commands, events, exceptions de domínio, requests sanitizadas e presenters não aceitam esses tipos em serialização.

`SecretRedactor` mantém um conjunto efêmero dos valores resolvidos e padrões estruturais sensíveis. Ele é aplicado defensivamente nas bordas de HTTP, logging, progresso, exceções apresentadas e `--json`. A proteção estrutural é primária; redação textual é a segunda barreira para mensagens de bibliotecas externas.

Testes com canários verificam stdout, stderr, logs, snapshots e artefatos. A redação nunca persiste a lista de segredos.

### 4.2 Confinamento sem symlinks ou junctions

O exportador rejeita qualquer symlink ou junction em ancestrais existentes ou destinos da árvore de exportação, mesmo quando a resolução aparente permanece dentro da raiz. Para cada item:

1. canonicalizar a raiz configurada;
2. percorrer componentes existentes sem seguir reparse points;
3. rejeitar symlink, junction, traversal e mudança de volume inesperada;
4. validar ancestralidade do destino;
5. repetir as verificações imediatamente antes de staging e promoção.

Esse padrão reduz risco de troca de caminho entre planejamento e escrita. Alteração concorrente detectada invalida todo o `ExportPlan`.

### 4.3 Permissões locais

Arquivos e diretórios recebem permissões restritivas best-effort por adapter de plataforma. Falha em endurecimento produz diagnóstico sanitizado e segue a política do tipo de artefato; não há promessa de criptografia ou isolamento além do sistema operacional.

## 5. Observabilidade e automação

- progresso estruturado vai para stderr;
- resultado humano ou JSON versionado vai para stdout;
- conteúdo de fonte, prompt, response e draft é omitido por padrão;
- categorias de erro determinam exit codes estáveis;
- `run_id`, tentativas, status e caminhos sanitizados são correlacionáveis;
- eventos são acrescentados somente após o efeito correspondente ser verificável.

## 6. Retenção segura

Retenção é um fluxo de plano e confirmação, nunca tarefa automática. `RetentionPlanner` seleciona por idade, exclui draft atual e qualquer run aprovado ou exportado, e gera dry-run completo. A execução revalida todas as proteções sob lock antes de cada remoção. Divergência entre plano e estado cancela a operação.

## 7. Rastreabilidade

| Padrão | Requisitos principais |
|---|---|
| Lock exclusivo e recuperação conservadora | NFR-CAP-004, NFR-REL-004 |
| Escrita atômica ordenada | NFR-REL-001, NFR-REL-002, NFR-REL-003 |
| Exportação compensável | NFR-REL-006, FR-EXP-006 |
| Retry controlado | NFR-PERF-002, NFR-PERF-003, NFR-PERF-004 |
| Pipeline incremental | NFR-CAP-002, NFR-CAP-003, NFR-PORT-004 |
| Estimativa extensível | FR-TRN-002, FR-TRN-004, NFR-003 |
| Gate por razão de crescimento | NFR-PERF-001, NFR-CAP-002 |
| Redação em profundidade | NFR-SEC-002, NFR-SEC-004, NFR-006 |
| Confinamento sem links | NFR-SEC-005, FR-EXP-006 |
| Retenção protegida | NFR-CAP-005, NFR-REL-005 |

## 8. Property-Based Testing e extensões

- PBT-02: round-trip de modelos e equivalência entre stream segmentado/recomposto e fonte normalizada.
- PBT-03: ordem, cobertura, monotonicidade de estado, confinamento e proteção de retenção.
- PBT-07: strategies reutilizáveis para Unicode incremental, segmentos, caminhos, inventários e eventos.
- PBT-08: shrinking e reprodução permanecem requisitos dos testes futuros.
- PBT-09: Hypothesis continua integrado ao Pytest.
- Security Baseline: N/A, desabilitada; os requisitos mínimos do produto foram incorporados.
- Resiliency Baseline: N/A, desabilitada; os requisitos de confiabilidade aprovados foram incorporados.

Não há achado bloqueante de extensão nesta etapa.

## 9. Validação de conteúdo

Markdown, tabelas, identificadores e referências foram revisados. Não há Mermaid, diagrama ASCII, JSON ou YAML embutido.

