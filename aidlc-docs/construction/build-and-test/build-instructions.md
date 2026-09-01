# Instruções de build

## Pré-requisitos

- Python 3.14.
- `uv` instalado e disponível no `PATH`.
- Windows ou macOS com acesso de escrita ao workspace.
- Para usar a tradução real: `NOVEL_TRANSLATOR_BASE_URL`, `NOVEL_TRANSLATOR_MODEL` e `NOVEL_TRANSLATOR_API_KEY`.

## Passos

```powershell
uv sync --extra dev
uv build
```

O resultado esperado são `dist/novel_translator-0.1.0.tar.gz` e `dist/novel_translator-0.1.0-py3-none-any.whl`. O build não requer credenciais de provider, pois apenas empacota a aplicação.

## Solução de problemas

- Se o build indicar `README.md` ausente, restaure o arquivo declarado em `[project].readme` no `pyproject.toml`.
- Se o Python estiver abaixo de 3.14, instale a versão compatível e execute novamente `uv sync --extra dev`.
