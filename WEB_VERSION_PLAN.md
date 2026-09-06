# Plano de implementação — Novel Translator Web

## 1. Objetivo

Transformar o Novel Translator em uma aplicação web pessoal, acessível por celular e diferentes computadores, preservando:

- drafts e revisões imutáveis;
- proveniência e hashes;
- separação entre tradução e publicação;
- compatibilidade com a CLI;
- segurança das credenciais;
- possibilidade de auditoria e recuperação.

O fluxo final desejado é:

```text
Adicionar source
→ iniciar tradução
→ acompanhar o processamento
→ revisar em uma working copy
→ criar revisão imutável
→ aprovar
→ exportar/publicar
```

Hashes, run IDs e caminhos continuam existindo internamente, mas não fazem parte do uso cotidiano.

## 2. Princípios arquiteturais

- A CLI e a interface web devem chamar os mesmos casos casos de use cases.
- Nenhuma regra de negócio deve ficar nas rotas HTTP.
- O navegador nunca acessa diretamente o workspace.
- O servidor é a autoridade central para diferentes dispositivos.
- O draft original nunca pode ser edit.
- Working copies são mutáveis; revisões são imutáveis.
- Traduções são jobs persistentes executados fora da requisição HTTP.
- Publicação continua separada de tradução e aprovação.
- Falhas não podem causar perda silenciosa de conteúdo.

## 3. Stack recomendada

### Backend

- FastAPI;
- Pydantic;
- SQLAlchemy e Alembic;
- SQLite em modo WAL inicialmente;
- workspace persistente para artefatos;
- worker Python separado.

### Frontend

- Jinja2;
- HTMX para atualizações parciais;
- JavaScript mínimo para autosave e editor;
- layout mobile-first;
- textarea Markdown inicialmente, com preview e diff.

### Execução

Um deployment com dois processos:

```text
web     → interface e API
worker  → tradução e tarefas demoradas
```

Ambos compartilham:

- banco SQLite;
- volume do workspace;
- configuração do provider.

Não introduzir Redis, Celery, React ou PostgreSQL até existir uma necessidade concreta.

---

# Fase 1 — Extrair uma camada de aplicação

## Objetivo

Preparar o código para ser usado tanto pela CLI quanto pela web.

## Estrutura sugerida

```text
novel_translator/
├── domain/
│   ├── models.py
│   ├── revisions.py
│   └── errors.py
├── application/
│   ├── translate.py
│   ├── review.py
│   ├── approve.py
│   ├── export.py
│   └── inspect.py
├── infrastructure/
│   ├── workspace.py
│   ├── providers.py
│   └── database.py
├── cli/
└── web/
```

Não é necessário seguir exatamente esses nomes, mas é importante retirar responsabilidades editoriais, workspace e orquestração do atual `core.py`.

## Casos de uso mínimos

- `ListNovels`;
- `ListChapters`;
- `GetChapter`;
- `StartTranslation`;
- `CreateRevision`;
- `ListRevisions`;
- `GetDiff`;
- `ApproveArtifact`;
- `RevokeApproval`;
- `ExportArtifact`.

Cada caso de uso deve receber dados tipados e retornar resultados tipados, sem depender de Typer, FastAPI ou HTML.

## Critérios de aceite

- CLI continua funcionando;
- web pode chamar os mesmos casos de uso;
- regras não são duplicadas;
- testes existentes permanecem verdes.

---

# Fase 2 — Catálogo de novels e capítulos

## Objetivo

Eliminar paths e configurações repetitivas.

## Configuração por novel

```yaml
novels:
  gariben:
    title: The Studious Boy and the Secret Account Girl
    bible: config/gariben.translation-bible.yaml
    source_directory: novel-sources/gariben-kun-to-uraaka-san
    export:
      repository: gregori/novels-site
      directory: src/content/novels/gariben
      filename_template: "{chapter:03}.md"
    translation:
      provider: opencode-go
      model: glm-5.3-flash
      default_volume: 3
```

Segredos permanecem em variáveis de ambiente ou secret store.

## Entregas

- cadastro e listagem de novels;
- resolução de capítulo para run;
- estado agregado por capítulo;
- seleção amigável sem copiar hashes;
- indexação dos runs existentes.

## Estados apresentados

```text
Sem source
Pronto para traduzir
Traduzindo
Draft disponível
Em revisão
Aprovado
Exportado
Falhou
```

## Critérios de aceite

- run IDs completos ficam ocultos no fluxo normal;
- ambiguidades são apresentadas para escolha;
- nenhum run é escolhido silenciosamente quando houver mais de um candidato válido.

---

# Fase 3 — Web MVP de leitura e revisão

Nesta fase, traduções ainda podem ser iniciadas pela CLI.

## Páginas

### Dashboard

- novels;
- capítulos recentes;
- traduções em andamento;
- itens aguardando revisão;
- itens aprovados e exportados.

### Página da novel

- lista de capítulos;
- busca;
- filtros por estado;
- ação para abrir o capítulo.

### Página do capítulo

- source japonês;
- draft gerado;
- working copy;
- preview Markdown;
- diff;
- histórico de revisões;
- detalhes técnicos recolhidos por padrão.

## Working copy

A working copy é mutável e armazenada no banco:

```text
id
run_id
base_artifact_kind
base_artifact_id
base_content_hash
content
version
created_at
updated_at
```

## Concorrência

Usar optimistic locking:

- cada salvamento envia a versão lida;
- o servidor aceita apenas se ela ainda for atual;
- conflito preserva os dois conteúdos;
- nunca aplicar “último salvamento vence” silenciosamente.

## Ações

- iniciar working copy;
- salvar automaticamente;
- descartar working copy;
- mostrar diff;
- criar revisão imutável;
- aprovar ou revogar;
- exportar revisão aprovada.

## Mobile

- leitura em coluna única;
- alternância entre source, edição e preview;
- botões grandes;
- autosave visível;
- nenhuma tabela larga obrigatória;
- recuperação do texto após perda de conexão.

## Critérios de aceite

- revisão completa utilizável pelo celular;
- troca entre celular e computador sem copiar arquivos;
- conflito entre duas abas não perde dados;
- hashes permanecem ocultos, mas consultáveis;
- nenhuma edição modifica o draft original.

---

# Fase 4 — Acesso remoto e operação segura

## Deployment inicial

- aplicação em uma máquina sempre ligada ou VPS;
- Docker Compose com `web` e `worker`;
- volume persistente;
- HTTPS;
- acesso preferencialmente protegido por Tailscale ou Cloudflare Access.

Não criar autenticação própria com senha se um proxy de identidade puder cuidar disso.

## Segurança

- credenciais do LLM somente no servidor;
- cookies seguros;
- proteção CSRF;
- limites de upload;
- validação UTF-8;
- nenhum path fornecido pelo navegador;
- logs sem chaves, prompts completos ou conteúdo sensível;
- permissões mínimas para integração com GitHub.

## Backups

Backup conjunto de:

- banco;
- workspace;
- configuração das novels.

Testar restauração, não apenas criação do backup.

## Critérios de aceite

- acesso pelo celular fora da máquina de desenvolvimento;
- reinício não perde working copies;
- backup pode ser restaurado em ambiente limpo.

---

# Fase 5 — Tradução iniciada pela web

## Formulário

A interface deve permitir:

- selecionar novel;
- informar capítulo e volume;
- enviar arquivo japonês ou escolher source existente;
- selecionar provider/model permitido;
- ajustar opções avançadas;
- iniciar tradução.

A maioria dos campos vem preenchida pela configuração da novel.

## Job persistente

Schema conceitual:

```text
job_id
job_type
status
run_id
novel
chapter
progress_current
progress_total
attempt
created_at
started_at
heartbeat_at
completed_at
error_type
cancel_requested
```

Estados:

```text
queued
running
succeeded
failed
interrupted
cancel_requested
cancelled
```

## Worker

O worker deve:

1. reservar atomicamente um job;
2. registrar lease e heartbeat;
3. executar o caso de uso `StartTranslation` existente;
4. atualizar progresso por segmento;
5. persistir o run imediatamente;
6. registrar falha segura;
7. liberar ou finalizar o job.

## Recuperação

Após reinício:

- jobs `queued` continuam disponíveis;
- jobs `running` com heartbeat expirado tornam-se `interrupted`;
- não reiniciar automaticamente chamadas ao modelo cuja conclusão seja desconhecida;
- oferecer ação explícita de retry;
- retry cria uma execução auditável.

## Interface de progresso

```text
Capítulo 32
Traduzindo segmento 2 de 4
Tentativa 1 de 3
Iniciado há 3 minutos
```

A tela pode usar polling com HTMX. WebSocket não é necessário inicialmente.

## Critérios de aceite

- tradução pode ser iniciada e acompanhada pelo celular;
- fechar o navegador não interrompe o job;
- reiniciar o servidor não apaga o estado;
- falhas aparecem sem expor segredos;
- o resultado aparece automaticamente como draft disponível para revisão.

---

# Fase 6 — Exportação e publicação

## Primeira entrega

Exportar o Markdown aprovado no servidor e permitir:

- download;
- visualização;
- cópia;
- gravação em um checkout configurado do `novels-site`.

## Entrega posterior

Integração com GitHub:

1. criar branch;
2. adicionar o Markdown;
3. criar commit;
4. abrir pull request;
5. apresentar o link na interface.

Preferir pull request a push direto em `main`.

## Proveniência da exportação

Registrar:

```text
run_id
artifact_kind
revision_id
content_hash
destination
exported_at
git_commit
pull_request_url
```

## Critérios de aceite

- somente revisão aprovada é exportada;
- publicação aponta para o hash exato;
- reexportação idêntica é idempotente;
- conteúdo diferente exige confirmação;
- falha no GitHub não altera a aprovação.

---

# Fase 7 — Dados editoriais e avaliação

Após alguns capítulos revisados, começar a extrair:

- número de alterações por capítulo;
- linhas adicionadas e removidas;
- termos corrigidos;
- mudanças de nomes e honoríficos;
- tempo entre tradução e aprovação;
- modelo e versão do prompt utilizados.

Esses dados formarão o conjunto de avaliação para:

- comparar modelos;
- modificar prompts;
- atualizar a translation bible;
- construir futuramente um revisor automático.

Não implementar RAG antes de identificar uma necessidade recorrente que a bible não resolva.

---

# Estratégia de testes

## Unidade

- casos de uso;
- working copy e controle de versão;
- integridade;
- transições de jobs;
- resolução de novels/capítulos;
- aprovação e exportação.

## Integração

- API + SQLite;
- workspace real temporário;
- worker com provider fake;
- reinício e recuperação de job;
- migração dos runs atuais;
- exportação para repositório Git temporário.

## Interface

- fluxo completo no navegador;
- viewport de celular;
- autosave;
- conflito entre abas;
- perda e recuperação de conexão;
- tradução em background;
- revisão, aprovação e exportação.

## Quality gates

```text
pytest
ruff check
ruff format --check
pyright
```

Adicionar também migrações de banco a um teste em banco vazio.

---

# Ordem recomendada das entregas

1. Workflow editorial e migração — issue #22.
2. Extração da camada de aplicação.
3. Catálogo de novels e resolução por capítulo.
4. Web MVP para revisão.
5. Deployment privado, autenticação e backups.
6. Jobs persistentes e tradução pela web.
7. Exportação/publicação via GitHub.
8. Métricas editoriais e avaliações.
9. Revisor automático.
10. RAG somente se os dados demonstrarem necessidade.

# Definição de sucesso

O projeto alcança a nova etapa quando for possível, pelo celular:

```text
abrir a aplicação
→ enviar ou selecionar o capítulo japonês
→ iniciar tradução
→ fechar o navegador
→ voltar mais tarde
→ revisar com autosave
→ criar e aprovar uma revisão
→ exportar ou abrir PR no novels-site
```

sem copiar run IDs, hashes ou paths e sem perder a proveniência técnica.
