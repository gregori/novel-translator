# Handoff — Fase 3 da versão web

## Objetivo concluído

Implementação do **Web MVP de leitura e revisão** definido em
`WEB_VERSION_PLAN.md`.

A revisão editorial completa passa a ser possível pelo navegador: dashboard,
busca, leitura do source, draft gerado, working copy mutável, preview, diff,
histórico de revisões, aprovação, revogação e exportação. A tradução continua
sendo iniciada pela CLI, como previsto para esta fase.

## Arquitetura adicionada

```text
src/novel_translator/
├── application/
│   └── working_copy.py
├── infrastructure/
│   ├── database.py
│   ├── working_copies.py
│   └── migrations/
└── web/
    ├── app.py
    ├── services.py
    ├── viewmodels.py
    ├── routes/
    │   ├── __init__.py
    │   ├── support.py
    │   ├── catalog.py
    │   ├── chapter.py
    │   ├── working_copy.py
    │   └── actions.py
    ├── templates/
    └── static/
```

Responsabilidades:

- `application/working_copy.py`: contrato de persistência e casos de uso de
  working copy, incluindo optimistic locking e congelamento em revisão;
- `application/inspect.py`: leitura da sala de revisão com degradação
  independente por artefato;
- `infrastructure/database.py`: engine SQLite em WAL e migrações Alembic;
- `infrastructure/working_copies.py`: implementação SQLAlchemy do repositório;
- `web/app.py`: composição da aplicação, filtros de template e mapeamento de
  erros tipados para status HTTP;
- `web/services.py`: contêiner de casos de uso compartilhados pelas rotas;
- `web/viewmodels.py`: apresentação, filtros, agrupamentos e diff HTML;
- `web/routes/*`: adaptação HTTP fina, sem regra editorial;
- `web/static/app.js`: abas, autosave, conflito e recuperação local.

## Execução

```powershell
novel-translator-web
```

Configuração operacional por ambiente:

```text
NOVEL_TRANSLATOR_CATALOG     novels.yaml
NOVEL_TRANSLATOR_WORKSPACE   .novel-translator
NOVEL_TRANSLATOR_DATABASE    SQLite dentro do workspace
NOVEL_TRANSLATOR_WEB_HOST    127.0.0.1
NOVEL_TRANSLATOR_WEB_PORT    8000
NOVEL_TRANSLATOR_SITE_ROOT   não definido
```

As migrações são aplicadas na inicialização. Exportação exige checkout externo
explícito; nenhuma árvore de publicação é criada silenciosamente.

## Páginas entregues

- **Dashboard**: novels, capítulos recentes e grupos por estado acionável;
- **Página da novel**: listagem, busca por capítulo e filtros por estado, com
  atualização parcial via HTMX;
- **Página do capítulo**: source japonês, draft gerado, working copy, preview
  Markdown, diff, histórico de revisões e detalhes técnicos recolhidos;
- **Seletor de run**: exigido quando o capítulo possui mais de um run válido.

## Working copy

Modelo persistido:

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

Contratos:

- uma única working copy ativa por run;
- o draft gerado nunca é modificado;
- o congelamento cria revisão imutável apontando para o parent exato e seu
  hash verificado;
- descartar remove somente a working copy;
- a base é verificada antes de diff e congelamento;
- uma base superada por artefato mais novo bloqueia o congelamento.

## Concorrência

- cada salvamento envia a identidade da working copy e a versão lida;
- versão obsoleta retorna `409` com os dois conteúdos preservados;
- o autosave é suspenso até a escolha explícita do revisor;
- a versão do servidor nunca é adotada implicitamente;
- uma aba cuja working copy foi substituída é rejeitada por identidade;
- o congelamento é idempotente após falha parcial entre workspace e SQLite,
  reutilizando a identidade determinística da revisão.

## Integridade de conteúdo

- quebras de linha são normalizadas para `\n` antes de hash e persistência,
  cobrindo o envio multipart do navegador;
- `pre` e `textarea` recebem newline de guarda, preservando texto iniciado por
  linha em branco;
- Markdown é renderizado com HTML bruto desabilitado;
- aprovação exibida corresponde ao artefato e run exatos, não ao estado
  agregado do capítulo.

## Estados HTTP

```text
404  novel ou capítulo inexistente
400  entrada inválida ou exportação não configurada
409  conflito, integridade, aprovação ausente ou colisão de export
```

## Mobile

- leitura em coluna única, sem overflow horizontal em 390×844;
- alternância entre source, edição e preview;
- alvos de toque amplos;
- estado do autosave sempre visível;
- recuperação local isolada por working copy, limpa após salvar, descartar ou
  criar revisão.

## Verificação final

```text
pytest:               108 passed
ruff check:           aprovado
ruff format --check:  57 arquivos formatados
pyright strict:       0 errors, 0 warnings
```

Verificação em navegador real, viewport móvel:

- autosave multiline por formulário multipart;
- revisão criada e diff imutável legível, sem falha de integridade;
- conflito entre duas abas com resolução explícita;
- sessão descartada externamente reportada como não salva, sem mensagem
  enganosa de conexão;
- ausência de erros de página.

Cobertura relevante inclui conflito sem autoresolução, aba obsoleta contra
working copy recriada, draft legível sem source, estado `in_review` por sessão
ativa, migração SQLite em memória, falha parcial durante congelamento, hashes
técnicos consultáveis, busca textual sem correspondência e aprovação isolada
por run.

## Próximo passo recomendado

Iniciar a **Fase 4 — Acesso remoto e operação segura**:

1. empacotar `web` e `worker` em Docker Compose com volume persistente;
2. publicar por HTTPS com acesso protegido por proxy de identidade;
3. mover a tradução para job persistente fora da requisição HTTP;
4. expor acompanhamento do processamento na interface;
5. preservar a separação entre tradução, aprovação e publicação.
