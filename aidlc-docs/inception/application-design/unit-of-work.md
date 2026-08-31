# Unidade de trabalho

## 1. Decisão de decomposição

A v1 possui uma única unidade de trabalho implantável: `novel-translator-cli`. Ela produz um único package Python e um único processo de CLI. As fronteiras internas são módulos por capacidade; não representam serviços independentes.

Essa escolha acompanha o caráter local do produto, evita distribuição prematura e preserva as fronteiras necessárias para trocar provider, readers e persistência por configuração ou composição.

## 2. Definição da unidade

| Campo | Definição |
|---|---|
| Nome | `novel-translator-cli` |
| Tipo | Aplicação Python instalável com CLI local |
| Responsabilidade | Ingerir capítulos, construir contexto, gerar e auditar drafts, registrar aprovação e exportar para o contrato do `novels-site` |
| Stories próprias | US-001 a US-019 |
| Dependências entre units | Nenhuma |
| Sistemas externos | Arquivo local, Kakuyomu, endpoint OpenCode Go compatível com OpenAI, filesystem do workspace e checkout do `novels-site` |
| Artefato distribuível | Um package `novel_translator` com entry point de console |
| Ownership | Revisão e responsabilidade por camada técnica: domain, application e adapters |

## 3. Módulos internos

| Módulo | Domain | Application | Adapters e bordas | Responsabilidade |
|---|---|---|---|---|
| `shared` | Tipos fundamentais, erros e valores comuns | Configuração tipada e contratos auxiliares | Relógio, IDs, hashing e carregadores de configuração | Fornecer o núcleo mínimo compartilhado sem concentrar regras de capacidades |
| `workspace` | `RunRecord`, estados, eventos e projeções | Lifecycle do run, consulta e integridade de artefatos | Repositórios de filesystem e escrita atômica de `run.json`/ponteiro | Preservar runs imutáveis, auditoria, eventos editoriais e draft atual |
| `source` | Identidade, proveniência e `SourceDocument` | Aquisição e resolução de identidade/metadados | Reader de arquivo local, HTTP e reader Kakuyomu | Obter fonte UTF-8 sem substituir silenciosamente a identidade canônica |
| `translation` | Bible, contexto, segmentos, prompts, requests e responses | Validação, construção de contexto, chunking, retry e `TranslateChapter` | Gateway OpenAI-compatible/OpenCode Go | Produzir um draft rastreável e independente do provider concreto |
| `editorial` | Manifesto, aprovação, integridade, volume e plano de exportação | `ApproveDraft` e `ExportDraft` | Store de eventos e writer seguro para `novels-site` | Governar aprovação e exportação sem publicar nem sobrescrever silenciosamente |
| `cli` | Commands, queries e outcomes tipados | Adaptação de uma invocação para um caso de uso | Parser, terminal e progress reporter | Expor `translate`, `approve`, `export` e `inspect` com exit codes estáveis |
| `adapters` | Nenhum domínio próprio | Nenhuma orquestração de caso de uso | Implementações concretas agrupadas por port | Conectar filesystem, HTTP, provider, relógio, IDs e terminal ao composition root |

Os módulos de capacidade podem conter subpackages `domain` e `application` quando o volume justificar. `adapters` implementa ports internos, mas não coordena workflows nem chama outro adapter diretamente.

## 4. Fronteiras e ownership técnico

| Camada | Responsabilidade de ownership | Pode depender de | Não pode depender de |
|---|---|---|---|
| Domain | Modelos imutáveis, validação e transformações determinísticas | Tipos internos estáveis | CLI, filesystem, HTTP, SDKs e adapters concretos |
| Application | Casos de uso, ordem dos workflows e ports | Domain, serviços puros e contratos de ports | Implementações concretas e formatos externos |
| Adapters | Conversão de dados e efeitos externos | Ports e tipos internos que implementam | Outros adapters como mecanismo de orquestração |

O `CompositionRoot` pertence à borda da aplicação e é o único ponto que conhece todas as implementações concretas. O ownership por camada orienta revisão técnica, sem alterar a coesão por capacidade.

## 5. Organização greenfield do código

```text
src/
  novel_translator/
    cli/
    shared/
    workspace/
    source/
    translation/
    editorial/
    adapters/
    composition.py
tests/
  unit/
    shared/
    workspace/
    source/
    translation/
    editorial/
    cli/
  integration/
  contract/
  property/
  strategies/
config/
```

Regras de organização:

- application code fica em `src/novel_translator/`; documentação AI-DLC permanece em `aidlc-docs/`;
- `tests/unit/` espelha capacidades, enquanto integração e contrato validam bordas reais;
- `tests/property/` contém propriedades e `tests/strategies/` centraliza estratégias Hypothesis reutilizáveis;
- YAML, TOML, JSON, HTTP e argumentos de CLI são convertidos nas bordas; modelos externos não atravessam ports;
- código, nomes, comentários e docstrings são em inglês; documentação é em português.

## 6. Sequência de implementação

1. **Foundation**: package, tipos, configuração, erros, ports, hashing/relógio/IDs e workspace básico.
2. **Source e translation**: ingestão local/Kakuyomu, bible/contexto, run, gateway, retry, chunking e draft.
3. **Editorial e export**: manifesto, aprovação, integridade, volume, renderização e escrita segura.
4. **Hardening transversal**: portabilidade Windows/macOS, Unicode, recuperação de persistência, contratos e obrigações PBT.

Cada incremento mantém uma única unidade distribuível. A sequência reduz stubs e respeita o fluxo `cli -> application -> domain/ports <- adapters`.

## 7. Critérios de prontidão

- Uma única unidade cobre todo o escopo da v1 e todas as 19 stories.
- Os sete módulos têm responsabilidade distinta e uma direção de dependência verificável.
- Integrações externas e persistência possuem ports; não há ports preventivos entre todos os módulos.
- Não há dependência de rede interna, plugin discovery, publicação automática ou serviço separado.
- A estrutura é compatível com o padrão greenfield single-unit de Code Generation.
- As transformações serializáveis e invariantes ficam isoladas para PBT nas etapas técnicas.

## 8. Extension Compliance

| Extensão | Resultado | Justificativa |
|---|---|---|
| Resiliency Baseline | N/A | Desabilitada em `aidlc-state.md`. |
| Security Baseline | N/A | Desabilitada; NFR-006 continua no escopo funcional. |
| Property-Based Testing parcial | Compliant | A estrutura reserva `tests/property/` e estratégias centralizadas para PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09; implementação será verificada nas etapas aplicáveis. |

Não há achado bloqueante de extensão.

## 9. Validação de conteúdo

- Markdown, tabelas, identificadores e bloco de árvore textual foram revisados.
- O bloco de árvore não é diagrama ASCII e não usa conectores gráficos.
- Não há Mermaid, JSON ou YAML embutido que exija validação adicional.
