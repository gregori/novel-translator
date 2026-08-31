# Modelo de lógica de negócio — `novel-translator-cli`

## 1. Fluxo `translate`

1. Validar comando, configuração, provider/modelo e referências a segredos sem materializar segredos em dados auditáveis.
2. Carregar e validar estritamente a translation bible.
3. Adquirir a fonte por reader compatível e fixar a identidade canônica informada pela CLI.
4. Criar um novo run imutável e persistir fonte, bible/contexto e metadados iniciais.
5. Construir contexto determinístico e calcular o orçamento seguro.
6. Criar o `SegmentPlan`: preferir parágrafos; para parágrafo acima do limite, usar limites de sentença. Offsets preservam todos os caracteres e separadores.
7. Transicionar o run para `translating`.
8. Para cada segmento, em ordem:
   - derivar `ContinuityState` local dos segmentos anteriores;
   - renderizar e snapshotar o prompt versionado;
   - criar request sanitizada e chamar o gateway;
   - repetir somente falhas transitórias dentro da política;
   - snapshotar tentativas, resposta e tradução do segmento.
9. Rejeitar recomposição se houver lacuna, duplicata, inversão ou resultado vazio.
10. Recompor um único draft, persistir o conteúdo/hash e transicionar para `draft_completed`.
11. Atualizar atomicamente o ponteiro atual somente depois da conclusão.

Uma nova tradução do mesmo capítulo sempre cria outro run. Falha ou interrupção preserva artefatos confirmados e não altera o ponteiro atual.

## 2. Segmentação e continuidade

### Divisão

- Se o capítulo couber no orçamento, existe um único segmento com toda a fonte.
- Caso contrário, quebras de parágrafo são candidatas preferenciais.
- Um parágrafo acima do limite é dividido em limites de sentença japonesa ou ocidental.
- Se uma única sentença ainda exceder o orçamento, a operação falha com diagnóstico de segmento indivisível; não há corte silencioso por caracteres.
- Cada segmento é um slice contíguo da fonte; delimitadores e espaços pertencem a exatamente um slice.

### Continuidade

Antes de cada segmento posterior, o sistema deriva um resumo curto, determinístico e limitado pelo orçamento. A síntese reúne entidades/termos observados e excertos mínimos relevantes dos resultados anteriores; não executa chamada adicional e não reproduz traduções anteriores completas.

### Recomposição

A recomposição valida índices e hashes, ordena pelo índice declarado e rejeita qualquer conjunto que não corresponda exatamente ao plano. O draft reúne as traduções com a política de separadores definida pelo plano, sem omitir segmento.

## 3. Fluxo `approve`

1. Carregar um run em `draft_completed` e seu draft.
2. Recalcular o hash sobre os bytes elegíveis para exportação.
3. Criar e acrescentar `ApprovalEvent` com identificador, hash, timestamp e aprovador opcional.
4. Recalcular a projeção: para `run_id + draft_hash`, a aprovação com ordenação temporal/event ID mais recente é vigente.
5. Preservar todos os eventos anteriores.

Run sem draft concluído é inelegível. Alteração do draft produz outro hash e torna a aprovação anterior inválida para exportação.

## 4. Fluxo `export`

1. Carregar run/draft e recalcular o hash.
2. Localizar a aprovação vigente mais recente para o mesmo run e hash.
3. Se ausente, retornar decisão de aprovação pendente. Modo não interativo só prossegue com autorização explícita; modo interativo coleta consentimento e repete o comando.
4. Validar manifesto, capa, título do capítulo, data e volume.
5. Resolver volume: valor explícito, depois extraído confiável, depois ausência; conflito é diagnóstico bloqueante.
6. Criar o plano completo de índice, capa e capítulo e validar todos os destinos.
7. Inspecionar todas as colisões antes de escrever.
8. Havendo arquivos diferentes:
   - modo interativo apresenta o conjunto inteiro e coleta uma confirmação única;
   - modo não interativo falha, salvo flag explícita e auditável;
   - a autorização vincula-se ao fingerprint do plano e do relatório.
9. Escrever temporários, promover destinos autorizados e verificar hashes finais.
10. Acrescentar `ExportEvent` e retornar caminhos; nunca executar Git, Astro ou deployment.

## 5. Fluxo `inspect`

1. Resolver run diretamente ou pela combinação novel/capítulo no ponteiro atual.
2. Carregar run e eventos sem mutação.
3. Calcular aprovação vigente por hash e listar exportações.
4. Retornar status, tentativas, falhas e caminhos sanitizados.
5. Fonte, prompt, resposta e draft só são incluídos por opção explícita.

## 6. Estados e decisões

| Estado atual | Evento | Próximo estado | Condição |
|---|---|---|---|
| inexistente | criar run | `started` | Local único reservado. |
| `started` | iniciar chamadas | `translating` | Preflight e snapshots iniciais confirmados. |
| `started`/`translating` | falha | `failed` | Falha permanente ou retries esgotados. |
| `started`/`translating` | interrupção | `interrupted` | Interrupção observada e registrada. |
| `translating` | concluir draft | `draft_completed` | Todos os segmentos válidos e draft persistido. |

Estados finais são terminais. Aprovação e exportação não alteram `RunStatus`.

## 7. Falhas e resultados

- Erros de entrada/configuração ocorrem antes de chamadas ao LLM.
- Falhas de negócio esperadas são outcomes: aprovação requerida, colisão, conflito de volume e inelegibilidade.
- Falhas técnicas são classificadas e sanitizadas; somente as transitórias recebem retry.
- Nenhum sucesso é reportado antes de o artefato correspondente estar persistido e verificável.

## 8. Rastreabilidade

| Fluxo | Requisitos/stories predominantes |
|---|---|
| `translate` | FR-BIB-001–004, FR-ING-001–004, FR-TRN-001–006, FR-RUN-001–005; US-002, US-004–011. |
| `approve` | FR-APR-001–003; US-012–014. |
| `export` | FR-EDT-001–003, FR-EXP-001–007; US-003, US-013–017. |
| `inspect` | FR-CLI-001, FR-RUN-002–005; US-011. |

## 9. Conformidade e validação

- PBT-02/PBT-03 cobrem round-trip de segmentação e invariantes dos fluxos; PBT-07–09 orientam geradores e execução.
- Security Baseline e Resiliency Baseline: N/A por configuração.
- Markdown e tabelas foram verificados; não há diagrama, Mermaid, JSON ou YAML embutido.
