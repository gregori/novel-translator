# Regras de negócio — `novel-translator-cli`

## 1. Configuração e definições

| ID | Regra | Falha |
|---|---|---|
| BR-CFG-001 | Provider, modelo e source reader devem existir nos registries explícitos. | Configuração inválida antes do workflow. |
| BR-CFG-002 | Segredos são resolvidos nas bordas e nunca entram em modelos serializáveis, logs ou snapshots. | Configuração inválida ou valor redigido. |
| BR-BIB-001 | A bible é YAML estrito e rejeita campos desconhecidos, tipos inválidos e campos obrigatórios ausentes. | Tradução bloqueada antes do LLM. |
| BR-BIB-002 | Personagens e termos são listas de objetos; chaves canônicas conflitantes ou aliases incoerentes são rejeitados. | Bible inválida. |
| BR-BIB-003 | O contexto canônico é determinístico para a mesma bible validada. | Erro de integridade. |
| BR-EDT-001 | Manifesto e capa são validados antes de planejar arquivos da novel. | Exportação bloqueada. |

## 2. Fonte e identidade

| ID | Regra | Falha |
|---|---|---|
| BR-SRC-001 | Fonte local deve ser arquivo legível, UTF-8 válido e não vazio. | Fonte inválida. |
| BR-SRC-002 | URL deve pertencer a reader suportado; Kakuyomu distingue ausência, URL incompatível e mudança estrutural. | Falha permanente tipada. |
| BR-SRC-003 | Novel e capítulo da CLI são canônicos; metadados extraídos apenas complementam o run. | Metadado conflitante é diagnosticado. |
| BR-SRC-004 | Conteúdo normalizado e hash são snapshotados antes da tradução. | Run não avança. |

## 3. Runs e persistência

| ID | Regra | Falha |
|---|---|---|
| BR-RUN-001 | Toda reexecução cria `run_id` e local novos, mesmo com hashes idênticos. | Colisão de ID/local é erro de integridade. |
| BR-RUN-002 | Artefato imutável existente nunca é sobrescrito. | Operação rejeitada. |
| BR-RUN-003 | Transições seguem `started -> translating -> draft_completed`, com `failed`/`interrupted` terminais. | Transição inválida. |
| BR-RUN-004 | O ponteiro atual muda somente após draft completo persistido e verificado. | Ponteiro anterior permanece. |
| BR-RUN-005 | Falha preserva snapshots confirmados e registra estado explícito. | Nunca promove draft parcial. |

## 4. Segmentação, prompt e provider

| ID | Regra | Falha |
|---|---|---|
| BR-TRN-001 | Segmentação prefere parágrafos e, dentro de parágrafo excedente, limites de sentença. | Sentença indivisível acima do limite bloqueia a tradução. |
| BR-TRN-002 | Os slices dos segmentos concatenados devem ser equivalentes à fonte normalizada. | Plano inválido. |
| BR-TRN-003 | Índices são únicos, contíguos e ordenados; nenhum offset se sobrepõe. | Plano/recomposição rejeitado. |
| BR-TRN-004 | Continuidade é local, determinística, limitada e não contém traduções anteriores completas. | Prompt inválido. |
| BR-TRN-005 | Prompt, request sanitizada, resposta e tentativa são snapshotados por chamada. | Run não pode concluir sem trilha completa. |
| BR-TRN-006 | Apenas falhas transitórias recebem retry; depois de sucesso confirmado não há repetição. | Falha final explícita. |
| BR-TRN-007 | Draft só é concluído com uma tradução não vazia para todos os segmentos. | Run `failed`; sem atualização do ponteiro. |

## 5. Aprovação

| ID | Regra | Falha |
|---|---|---|
| BR-APR-001 | Somente run `draft_completed` pode ser aprovado. | Outcome de inelegibilidade. |
| BR-APR-002 | Hash é recalculado sobre os bytes efetivamente exportáveis. | Aprovação não registrada se leitura/hash falhar. |
| BR-APR-003 | Eventos de aprovação são append-only. | Sobrescrita/remoção proibida. |
| BR-APR-004 | Para `run_id + draft_hash`, a projeção vigente é o evento mais recente; eventos anteriores permanecem auditáveis. | Projeção inconsistente é erro de integridade. |
| BR-APR-005 | Se o hash atual divergir, nenhuma aprovação de outro hash é válida. | Nova aprovação exigida. |

## 6. Exportação

| ID | Regra | Falha |
|---|---|---|
| BR-EXP-001 | Exportação exige aprovação vigente para run e hash atuais. | `ApprovalRequired`. |
| BR-EXP-002 | Sem terminal interativo, ausência de flag explícita nunca implica consentimento. | Falha sem escrita. |
| BR-EXP-003 | Volume explícito prevalece sobre extraído; conflito ou valor não positivo é diagnosticado. | Plano rejeitado. |
| BR-EXP-004 | Slug usa minúsculas/hífens e o capítulo usa zero-padding coerente com a sequência adotada. | Metadado/destino inválido. |
| BR-EXP-005 | Todos os destinos devem estar confinados ao checkout e ser pré-validados antes da primeira escrita. | Nenhuma escrita começa. |
| BR-EXP-006 | Arquivo idêntico é idempotente; arquivo diferente é colisão. | Decisão explícita requerida. |
| BR-EXP-007 | Uma confirmação interativa cobre o conjunto completo de colisões exibido. | Plano alterado invalida a autorização. |
| BR-EXP-008 | No modo não interativo, substituição exige flag explícita e evento auditável. | Falha sem escrita. |
| BR-EXP-009 | Exportação não executa Git, build, Astro, push ou deployment. | Comportamento fora do contrato. |

## 7. Consulta, Unicode e portabilidade

| ID | Regra | Falha |
|---|---|---|
| BR-OPS-001 | Consulta é read-only e omite conteúdo sensível por padrão. | Conteúdo só aparece com opção explícita. |
| BR-OPS-002 | Artefatos textuais usam UTF-8 e preservam japonês, inglês e caracteres combinantes válidos. | Entrada/saída inválida. |
| BR-OPS-003 | Caminhos são semânticos e independentes de separador/shell de Windows ou macOS. | Caminho inválido. |

## 8. Catálogo de propriedades

| Propriedade | Regra PBT | Formulação |
|---|---|---|
| Round-trip de fonte | PBT-02 | Concatenar os slices do plano recupera a fonte. |
| Round-trip de serialização | PBT-02 | Decodificar um modelo codificado preserva igualdade semântica. |
| Identidade canônica | PBT-03 | Metadados extraídos nunca alteram `ChapterIdentity`. |
| Estados monotônicos | PBT-03 | Nenhuma sequência válida sai de estado terminal. |
| Aprovação por hash | PBT-03 | Elegibilidade implica hash atual igual ao hash do evento vigente. |
| Volume | PBT-03 | Explícito válido vence extraído; ausência de ambos omite o campo. |
| Exportação segura | PBT-03 | Todo destino normalizado permanece sob a raiz permitida. |
| Estratégias comuns | PBT-07 | Geradores são reutilizados entre testes de domínio e adapters. |
| Reprodução | PBT-08 | Falhas mantêm exemplo mínimo e seed reproduzível. |
| Runner | PBT-09 | Hypothesis executa no mesmo runner dos demais testes. |

## 9. Rastreabilidade e conformidade

- BR-CFG/BIB/SRC/TRN/RUN cobrem US-001, US-002 e US-004–011.
- BR-APR cobre US-012–014; BR-EXP cobre US-003 e US-013–017.
- BR-OPS e o catálogo PBT cobrem US-018–019 e NFR-001, NFR-005–012.
- Property-Based Testing parcial: compliant; Security e Resiliency: N/A por estarem desabilitadas.
- Markdown e tabelas foram verificados; não há Mermaid, diagrama ASCII, JSON ou YAML embutido.
