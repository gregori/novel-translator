# Plano de NFR Design — `novel-translator-cli`

## Objetivo

Incorporar os requisitos não funcionais aprovados ao desenho lógico da unidade, definindo padrões de resiliência, escala local, desempenho, segurança e componentes técnicos sem introduzir infraestrutura de deployment.

## Progresso

- [x] Carregar requisitos, arquitetura, design funcional e NFR Requirements aprovados.
- [x] Avaliar ambiguidades nas cinco categorias obrigatórias de NFR Design.
- [x] Registrar decisões pendentes com opções explícitas.
- [x] Validar todas as respostas e resolver ambiguidades ou contradições.
- [x] Definir padrões de NFR e sua aplicação aos fluxos da unidade.
- [x] Definir componentes lógicos, contratos, responsabilidades e interações.
- [x] Mapear requisitos NFR e riscos para padrões e componentes.
- [x] Validar Markdown, rastreabilidade e extensões habilitadas.
- [x] Gerar `nfr-design-patterns.md` e `logical-components.md`.

## Premissas já aprovadas

- CLI local, síncrona e de processo único por operação.
- Um único writer por workspace, com leituras somente sobre artefatos publicados atomicamente.
- Timeout padrão de 120 segundos e até três tentativas totais para falhas transitórias.
- Escrita por temporário e promoção atômica quando suportada.
- Windows e macOS são plataformas obrigatórias.
- Security Baseline e Resiliency Baseline estão desabilitadas; os requisitos mínimos aprovados continuam obrigatórios.
- Hypothesis aplica PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09.

## Questão 1 — Resiliência do lock do workspace

Qual padrão deve implementar exclusão mútua e recuperação conservadora de lock obsoleto?

A) Biblioteca `filelock`, com timeout, metadados sanitizados em arquivo separado e remoção de lock obsoleto somente após verificação conservadora e confirmação explícita.

B) Biblioteca `portalocker`, usando lock nativo cross-platform; metadados sanitizados e recuperação conservadora ficam em componente separado.

C) Lock próprio baseado em criação exclusiva de arquivo, sem dependência externa, com lease e recuperação implementados pela aplicação.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Questão 2 — Espera pelo lock

Quando o workspace já estiver bloqueado, qual deve ser o comportamento padrão de comandos mutáveis?

A) Falhar imediatamente; `--lock-timeout` permite espera explícita.

B) Aguardar por um timeout curto padrão e permitir sobrescrita por configuração.

C) Aguardar indefinidamente até aquisição ou interrupção do usuário.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Questão 3 — Recuperação de exportação parcial

Como tratar falha durante a promoção de um conjunto de arquivos do `novels-site`, já que atomicidade multiarquivo não é garantida?

A) Staging no checkout, inventário persistido e rollback best-effort dos arquivos promovidos; se o rollback falhar, bloquear nova exportação até reconciliação explícita.

B) Staging e inventário persistido, sem rollback automático; bloquear nova exportação até comando explícito de recuperação concluir ou reverter o plano.

C) Apenas registrar o inventário e permitir nova exportação idempotente reparar o conjunto automaticamente.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: A

## Questão 4 — Escala local e uso de memória

Como processar capítulos grandes na v1?

A) Carregar a fonte normalizada em memória, mas processar hashing, segmentação e snapshots em passagens lineares; documentar que o limite prático é a memória local.

B) Implementar streaming completo de leitura, segmentação, hashing e persistência desde a v1.

C) Aplicar limite configurável de bytes e rejeitar entradas acima dele antes do processamento.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Questão 5 — Orçamento de contexto e desempenho

Qual estratégia deve decidir se o capítulo precisa ser segmentado quando providers podem usar tokenizações diferentes?

A) Orçamento conservador configurável em caracteres, com overhead explícito de contexto/prompt e sem dependência de tokenizer do provider na v1.

B) Port `TokenEstimator` com implementação específica por provider e fallback conservador em caracteres.

C) Usar somente limite fixo de caracteres igual para todos os providers.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Questão 6 — Gate de regressão algorítmica

Como tornar o requisito de complexidade verificável sem criar um SLA frágil entre máquinas?

A) Benchmark por série geométrica de tamanhos e limite sobre a razão de crescimento, com relatório informativo de tempo absoluto.

B) Baseline de tempo absoluto versionada por sistema operacional, com tolerância percentual.

C) Revisão de complexidade e teste com um único capítulo grande, sem gate quantitativo.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Questão 7 — Segurança de caminhos e symlinks

Como o exportador deve tratar symlinks/junctions dentro do checkout configurado?

A) Resolver cada ancestral e destino existente; rejeitar qualquer caminho cuja resolução escape da raiz e não seguir symlink inexistente durante criação.

B) Rejeitar qualquer symlink ou junction em todo o caminho de exportação, mesmo quando permanece dentro da raiz.

C) Confiar somente em `Path.resolve()` e no teste de ancestralidade do destino final.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Questão 8 — Redação de segredos

Qual padrão deve proteger logs, exceções e saída JSON de segredos provenientes de ambiente, `.env` e headers HTTP?

A) Modelos persistíveis excluem segredos por tipo; um `SecretRedactor` central aplica redação defensiva nas bordas de observabilidade e erro.

B) Somente impedir que campos de credencial sejam serializados; não aplicar redação textual adicional.

C) Aplicar redação apenas no adapter HTTP e confiar que camadas internas não recebem segredos.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: C

## Questão 9 — Fronteiras dos componentes lógicos

Como agrupar lock, escrita atômica, staging/recuperação e retenção?

A) Componentes separados (`WorkspaceLock`, `AtomicFileWriter`, `ExportTransactionCoordinator`, `RetentionPlanner`) atrás de ports pequenos.

B) Um único `WorkspaceSafetyService` com todas as operações de segurança do filesystem.

C) Incorporar cada comportamento diretamente nos repositories e no exporter, sem componentes compartilhados.

D) Outro (descreva após a tag `[Answer]:`).

[Answer]: B

## Validação pré-criação

- Markdown revisado, com opções separadas por linhas em branco.
- Todas as questões possuem ao menos duas opções significativas e `Outro` como última opção.
- Todas as decisões usam a tag `[Answer]:`.
- Não há Mermaid, diagrama ASCII, JSON ou YAML embutido.
