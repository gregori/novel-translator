# Personas da v1

## Persona principal: Operador de Tradução

### Perfil

O Operador de Tradução prepara e acompanha capítulos de web novels japonesas até a entrega editorial em inglês. Trabalha localmente por linha de comando, conhece a estrutura básica da obra e precisa controlar conscientemente quando um draft está pronto para exportação.

### Objetivos

- Traduzir capítulos provenientes de arquivos UTF-8 ou do Kakuyomu com consistência terminológica.
- Entender o estado de cada execução e localizar rapidamente seus artefatos.
- Preservar fontes, prompts, respostas e metadados suficientes para auditoria e reprodução.
- Aprovar apenas o conteúdo exato que foi revisado.
- Exportar conteúdo compatível com `novels-site` sem sobrescrever trabalho existente nem publicar automaticamente.
- Trocar provider, modelo e parâmetros por configuração, sem mudar seu fluxo de trabalho.

### Responsabilidades

- Manter a translation bible e o manifesto editorial da novel.
- Informar a identidade canônica e o título do capítulo.
- Escolher a fonte e, quando necessário, o volume.
- Acompanhar progresso e diagnosticar falhas informadas pela CLI.
- Revisar manualmente o draft antes da aprovação.
- Confirmar colisões ou aprovações somente por mecanismos explícitos e auditáveis.

### Motivações

- Produzir traduções inglesas consistentes sem perder o vínculo com a fonte japonesa.
- Evitar retrabalho causado por perda de versões, metadados incompletos ou exportações incorretas.
- Ter confiança de que uma falha de rede, mudança de arquivo ou nova execução não corromperá resultados anteriores.

### Pontos de dor

- Limites de contexto e falhas transitórias de providers de LLM.
- Mudanças na estrutura de páginas do Kakuyomu.
- Inconsistências de nomes, honoríficos e terminologia entre capítulos.
- Dificuldade de reconstruir exatamente o que foi enviado ao provider.
- Risco de aprovar um draft e exportar outro conteúdo.
- Frontmatter inválido, capas ausentes e colisões no checkout de destino.
- Diferenças de caminhos, encoding e shells entre Windows e macOS.

### Ambiente e proficiência

- Usa Windows ou macOS.
- Consegue executar comandos, editar YAML e configurar variáveis de ambiente ou `.env` local.
- Entende a revisão editorial, mas não deve precisar conhecer a implementação interna ou o SDK do provider.
- Pode executar a CLI interativamente ou por scripts locais não interativos.

## Contextos operacionais da mesma persona

### Contexto interativo

O operador acompanha mensagens no terminal e pode confirmar uma aprovação durante a exportação. Confirmações devem explicar a consequência e registrar a decisão.

### Contexto automatizado

O mesmo operador invoca a CLI por script. Não há prompt interativo; ações sensíveis precisam de opção explícita e auditável, e estados de saída devem permitir que o script detecte sucesso ou falha.

### Contexto de manutenção

O operador configura provider, modelo, endpoint, diretórios e políticas operacionais. A manutenção da ferramenta é tratada como contexto porque a decisão aprovada definiu apenas uma persona. Necessidades estritamente internas só se tornam histórias habilitadoras quando produzem um resultado observável e independente.

## Jornada resumida

1. Preparar configuração, translation bible e manifesto editorial.
2. Informar novel, capítulo, título, fonte e volume opcional.
3. Validar e preservar a fonte local ou extraída do Kakuyomu.
4. Traduzir, acompanhando progresso, segmentação e tentativas.
5. Consultar o draft e os artefatos imutáveis da execução.
6. Revisar e aprovar explicitamente o conteúdo exato.
7. Exportar título, capa e capítulo para o checkout configurado.
8. Resolver erros sem perder execuções ou sobrescrever arquivos silenciosamente.

## Mapeamento para épicos

| Epic | Necessidade da persona | Contextos predominantes |
|---|---|---|
| EP-01 Preparar a tradução | Configurar a execução e validar os documentos da novel antes de consumir o LLM. | Manutenção e interativo |
| EP-02 Adquirir a fonte | Ingerir um capítulo confiável e preservar identidade, conteúdo e proveniência. | Interativo e automatizado |
| EP-03 Produzir e acompanhar o draft | Traduzir com previsibilidade, lidar com capítulos grandes e entender falhas. | Interativo e automatizado |
| EP-04 Governar a aprovação | Garantir que somente o conteúdo revisado e íntegro se torne elegível para exportação. | Interativo e automatizado |
| EP-05 Entregar ao `novels-site` | Gerar Markdown e ativos compatíveis sem publicar nem destruir conteúdo existente. | Interativo e automatizado |
| EP-06 Operar com confiança | Obter comportamento portátil, Unicode correto e artefatos recuperáveis. | Todos |

## Mapeamento para histórias

O Operador de Tradução é a persona de US-001 a US-019. O valor muda conforme o contexto operacional indicado em cada história; automação e manutenção não constituem personas separadas na v1.

## Validação da persona

- A persona representa todos os fluxos humanos definidos nos requisitos aprovados.
- Os contextos interativo e automatizado distinguem as regras de confirmação sem inventar novos atores.
- O contexto de manutenção permite expressar substituição de provider, configuração e testabilidade sem transformar componentes internos em personas.
- Nenhuma responsabilidade futura de revisão automática, múltiplos agentes ou publicação foi incorporada.

## Extension Compliance

| Extension | Status | Applicability |
|---|---|---|
| Resiliency Baseline | Disabled | Não aplicada. |
| Security Baseline | Disabled | Não aplicada. |
| Property-Based Testing | Compliant | PBT-02, PBT-03, PBT-07, PBT-08 e PBT-09 não impõem critérios à definição de persona; serão rastreadas nas histórias e etapas técnicas aplicáveis. |
