# Requisitos não funcionais — `novel-translator-cli`

## 1. Escopo operacional

A v1 é uma aplicação CLI local, de processo único por operação, sem serviço residente, SLA de uptime ou escalabilidade horizontal. O desempenho percebido é dominado pelo provider; o núcleo local deve permanecer previsível, recuperável e sem degradação algorítmica quadrática.

## 2. Capacidade e escalabilidade local

| ID | Requisito | Verificação |
|---|---|---|
| NFR-CAP-001 | Cada run deve usar diretório próprio e preservar todos os artefatos confirmados. | Testes com múltiplos runs da mesma identidade. |
| NFR-CAP-002 | O processamento local de fonte, segmentação, hashing e serialização deve ser linear ou `O(n log n)` em relação ao tamanho da entrada; algoritmos quadráticos sobre o capítulo completo são proibidos. | Benchmarks com tamanhos crescentes e revisão de complexidade. |
| NFR-CAP-003 | Não há limite funcional fixo de tamanho além do orçamento de contexto e dos recursos locais; uma sentença indivisível maior que o orçamento falha explicitamente. | Testes de limites e capítulos grandes. |
| NFR-CAP-004 | Um lock exclusivo deve permitir somente um processo mutável por workspace. Consultas read-only podem ocorrer se observarem apenas arquivos atomicamente publicados. | Testes multiprocesso de lock e leitura. |
| NFR-CAP-005 | Histórico não deve ser removido automaticamente por padrão. A retenção por idade é opt-in e executada somente por comando explícito. | Configuração padrão e testes do comando de limpeza. |

## 3. Desempenho e rede

| ID | Requisito | Verificação |
|---|---|---|
| NFR-PERF-001 | Não existe SLA absoluto em segundos para processamento local na v1; benchmarks devem detectar regressão de classe de complexidade e registrar baseline por ambiente. | Suite de performance separada dos testes funcionais. |
| NFR-PERF-002 | Chamadas HTTP usam timeout total padrão de 120 segundos, com limites explícitos de conexão, leitura, escrita e aquisição de conexão. | Testes com transporte simulado. |
| NFR-PERF-003 | Falhas transitórias admitem no máximo três tentativas totais, com backoff exponencial e jitter; todos os valores são configuráveis. | Clock/HTTP doubles e registro de tentativas. |
| NFR-PERF-004 | Não deve haver retry após sucesso confirmado nem retry automático de falhas permanentes. | Testes por classificação de erro. |

## 4. Confiabilidade e recuperabilidade

| ID | Requisito | Verificação |
|---|---|---|
| NFR-REL-001 | `run.json`, ponteiro atual, eventos e arquivos exportados devem usar escrita temporária e promoção atômica quando suportada. | Injeção de falhas antes/durante/depois da promoção. |
| NFR-REL-002 | O estado reportado nunca pode anteceder a persistência verificável do artefato correspondente. | Testes de ordem de operações. |
| NFR-REL-003 | Falha ou interrupção preserva snapshots completos já confirmados e mantém o draft atual anterior. | Testes de falha em cada etapa. |
| NFR-REL-004 | O lock de workspace deve falhar com diagnóstico acionável ou aguardar até timeout configurado; lock abandonado deve possuir estratégia segura de recuperação. | Testes multiprocesso e de lock obsoleto. |
| NFR-REL-005 | Limpeza por idade é desabilitada por padrão, exige dry-run e confirmação, e nunca remove draft atual nem runs aprovados ou exportados. | Testes de seleção e proteção. |
| NFR-REL-006 | Exportação deve validar o conjunto completo antes da primeira escrita e registrar inventário caso uma promoção parcial não possa ser revertida. | Falhas simuladas no writer. |

## 5. Segurança e privacidade local

| ID | Requisito | Verificação |
|---|---|---|
| NFR-SEC-001 | A v1 não implementa autenticação nem criptografia interna do workspace. | Revisão arquitetural. |
| NFR-SEC-002 | Segredos vêm de variáveis de ambiente ou `.env` ignorado pelo Git e nunca aparecem em modelos persistíveis, logs, mensagens ou `--json`. | Testes com canários de segredo. |
| NFR-SEC-003 | Arquivos criados recebem permissões restritivas best-effort compatíveis com Windows/macOS, sem prometer isolamento além do sistema operacional. | Testes por plataforma e diagnóstico de fallback. |
| NFR-SEC-004 | Saída padrão omite fonte, prompt, resposta e draft; exposição exige opção explícita. | Testes de snapshots de CLI. |
| NFR-SEC-005 | Caminhos exportados devem permanecer confinados ao checkout configurado após normalização e resolução. | PBT com caminhos e traversal. |

Security Baseline continua desabilitada. Estes requisitos decorrem do escopo funcional e do NFR-006 aprovado, não reativam a extensão.

## 6. Portabilidade e compatibilidade

| ID | Requisito | Verificação |
|---|---|---|
| NFR-PORT-001 | Runtime mínimo: CPython 3.14. | Metadado `requires-python` e execução na matriz. |
| NFR-PORT-002 | Windows e macOS são gates obrigatórios. Linux é best-effort e não integra o suporte oficial da v1. | CI em Windows/macOS; job Linux informativo. |
| NFR-PORT-003 | Código não pode depender de shell, separador ou semântica de rename exclusiva de uma plataforma. | Testes por plataforma e uso de APIs Python. |
| NFR-PORT-004 | Todo texto persistido usa UTF-8 explícito e preserva japonês, inglês, pontuação e caracteres combinantes. | Testes por exemplos e PBT Unicode. |

## 7. Usabilidade e automação

| ID | Requisito | Verificação |
|---|---|---|
| NFR-UX-001 | Saída humana é o padrão; `--json` produz outcome versionado e estável para automação. | Testes de contrato da CLI. |
| NFR-UX-002 | Progresso estruturado usa stderr; resultado usa stdout. Nenhum canal inclui segredos. | Captura independente de streams. |
| NFR-UX-003 | Help, erros e decisões pendentes devem ser acionáveis e manter exit codes estáveis por categoria. | Golden tests e matriz de outcomes. |
| NFR-UX-004 | Operações destrutivas de cleanup e overwrite exigem intenção explícita, apresentação do plano e confirmação adequada ao modo. | Testes interativos/não interativos. |

## 8. Manutenibilidade e qualidade

| ID | Requisito | Verificação |
|---|---|---|
| NFR-MNT-001 | Código, identificadores, comentários e docstrings são em inglês; documentação é em português. | Revisão e lint aplicável. |
| NFR-MNT-002 | Ruff lint/format e Pyright strict devem passar em `src/`. | Gates automatizados. |
| NFR-MNT-003 | Testes usam Pytest e Hypothesis; cobertura de branches deve ser ao menos 90% em domain/application e 80% no total. | Coverage gate por paths e total. |
| NFR-MNT-004 | Dependências diretas são declaradas em `pyproject.toml`; resolução exata e transitive dependencies ficam em `uv.lock` versionado. | `uv lock --check`/sync travado. |
| NFR-MNT-005 | Adapters de filesystem, relógio, HTTP e provider devem ser substituíveis por doubles sem rede paga ou checkout real. | Testes unitários/integrados herméticos. |

## 9. Property-Based Testing

| Regra habilitada | Aplicação obrigatória |
|---|---|
| PBT-02 | Round-trip de modelos serializáveis, `run.json` e divisão/recomposição da fonte. |
| PBT-03 | Identidade, estados, hash aprovado, volume, segmentos, nomes e confinamento de caminhos. |
| PBT-07 | Estratégias reutilizáveis para modelos, Unicode, segmentos, eventos e caminhos. |
| PBT-08 | Shrinking ativo, exemplo mínimo e informação reproduzível em CI. |
| PBT-09 | Hypothesis integrado ao Pytest e aos gates normais. |

## 10. Critérios de aceite de NFR

- Gates de Windows e macOS passam com Python 3.14.
- Lint, format e Pyright strict passam sem supressões globais não justificadas.
- Cobertura atinge 90% de branches em domain/application e 80% total.
- Testes de falha demonstram atomicidade, recuperação e lock exclusivo.
- Canários de segredo não aparecem em arquivos nem outputs.
- Benchmarks não evidenciam comportamento quadrático sobre a fonte.
- Cleanup preserva todos os runs protegidos e nunca roda implicitamente.

## 11. Conformidade e validação

- Property-Based Testing parcial: compliant; todas as regras habilitadas possuem aplicação verificável.
- Security Baseline e Resiliency Baseline: N/A, desabilitadas.
- Markdown e tabelas foram verificados; não há Mermaid, diagrama ASCII, JSON ou YAML embutido.
