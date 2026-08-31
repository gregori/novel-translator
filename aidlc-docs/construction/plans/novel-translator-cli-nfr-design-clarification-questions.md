# Esclarecimentos de NFR Design — `novel-translator-cli`

As nove respostas originais foram preenchidas e validadas. Quatro pontos precisam ser reconciliados com requisitos ou fronteiras já aprovados antes da geração dos artefatos.

## Contradição 1 — Gate de desempenho

A resposta Q6=B escolhe baseline de tempo absoluto por sistema operacional. O requisito NFR-PERF-001 determina que não exista SLA absoluto na v1 e que o gate detecte regressão de classe de complexidade, pois tempos absolutos variam entre máquinas.

### Questão de esclarecimento 1

Qual combinação deve prevalecer?

A) Gate obrigatório pela razão de crescimento em série geométrica; tempos absolutos são registrados apenas como informação por ambiente.

B) Gate duplo: razão de crescimento obrigatória e baseline absoluta por runner específico, aplicada somente quando o ambiente corresponder exatamente ao perfil versionado.

C) Substituir NFR-PERF-001 por baseline absoluta por sistema operacional, mesmo entre máquinas diferentes.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Contradição 2 — Redação de segredos

A resposta Q8=C restringe redação ao adapter HTTP. NFR-SEC-002 exige que segredos vindos de ambiente ou `.env` também nunca apareçam em logs, mensagens, arquivos ou `--json`; erros podem ocorrer antes de uma chamada HTTP.

### Questão de esclarecimento 2

Como atender à proteção já aprovada?

A) Excluir segredos dos modelos persistíveis e aplicar `SecretRedactor` defensivo em todas as bordas de log, erro e apresentação, incluindo o adapter HTTP.

B) Redigir no adapter HTTP e também no carregamento de configuração, sem redator central para outras bordas.

C) Alterar NFR-SEC-002 para garantir redação somente no tráfego HTTP.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Ambiguidade 1 — Alcance do streaming

A resposta Q4=B pede streaming completo, mas prompt, request ao provider e draft recomposto ainda precisam existir como unidades auditáveis. É necessário definir onde o streaming termina.

### Questão de esclarecimento 3

Qual fronteira de memória deve ser adotada na v1?

A) Streaming para ingestão, normalização, hashing, segmentação e snapshots; cada segmento e a resposta correspondente podem ficar em memória, enquanto o draft final é montado por arquivo temporário.

B) Streaming ponta a ponta, inclusive requests e responses do provider, exigindo suporte de streaming no contrato LLM.

C) Streaming somente para aquisição e snapshots; segmentação e recomposição carregam o capítulo completo em memória.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Ambiguidade 2 — Responsabilidade do `WorkspaceSafetyService`

A resposta Q9=B pode representar uma facade coesa ou um componente único com lock, escrita, transação e retenção, o que afetaria separação de responsabilidades e testabilidade.

### Questão de esclarecimento 4

Qual desenho foi pretendido?

A) `WorkspaceSafetyService` é uma facade de aplicação; internamente delega a ports/componentes separados para lock, escrita atômica, transação de exportação e planejamento de retenção.

B) `WorkspaceSafetyService` implementa diretamente todas essas responsabilidades em uma única classe.

C) Manter somente componentes separados, sem facade compartilhada.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Validação

- Todas as perguntas têm opções significativas e `Outro` como última opção.
- Cada pergunta contém uma tag `[Answer]:`.
- O documento não contém Mermaid, diagrama ASCII, JSON ou YAML embutido.
