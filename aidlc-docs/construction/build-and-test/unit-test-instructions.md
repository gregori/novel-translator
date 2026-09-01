# Instruções de testes unitários

## Execução

```powershell
uv run pytest tests/unit
uv run pyright
uv run ruff check src tests
uv run ruff format --check src tests
```

O resultado atual esperado é 10 testes aprovados, sem achados de Pyright, lint ou formatação. Os testes unitários cobrem segmentação com propriedade Hypothesis, bible, contexto, workspace, aprovação, exportação segura, volume, carregamento de `.env`, redaction e superfície da CLI.

Cada falha deve ser corrigida no código de produção ou no teste que viola um contrato aprovado; execute novamente os três comandos até não haver falhas.
