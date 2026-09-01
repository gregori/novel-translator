# Resumo da implementação

- Criado package Python instalável com CLI Typer e configuração de Ruff, Pyright, Pytest e Hypothesis.
- Implementados bible, fonte local/Kakuyomu, segmentação, gateway OpenAI-compatible, workspace imutável e lifecycle de draft.
- Implementados aprovação append-only e exportação Markdown sem publicação automática.
- Criados testes unitários e de propriedade para regras centrais e CLI.

## Verificação

- `uv sync --extra dev`: concluído.
- `uv run pytest`: concluído com sucesso (8 testes).
- `uv run ruff check src tests`: concluído sem achados.
- `uv run ruff format --check src tests`: concluído sem alterações necessárias.
