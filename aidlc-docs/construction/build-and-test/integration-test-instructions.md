# Instruções de testes de integração

## Cenários prioritários

1. **Arquivo local → draft → aprovação → exportação**: use uma bible válida e um capítulo UTF-8; confirme a criação de `run.json`, `source.txt`, `draft.md` e do Markdown exportado somente após aprovação.
2. **Provider falso → retry**: use um transporte HTTP falso que falhe transitoriamente duas vezes e tenha sucesso na terceira; confirme três tentativas e um draft completo.
3. **Colisão de exportação**: prepare um Markdown diferente no destino; confirme que a exportação falha sem `--overwrite` e que não há publicação automática.
4. **URL Kakuyomu**: execute apenas contra fixture ou URL de teste autorizada; confirme que URL não suportada falha antes da chamada ao provider.

## Ambiente e execução

Não há serviços locais para iniciar. Use `tmp_path`/diretório temporário e provider falso para impedir escrita no `novels-site` e chamadas pagas.

```powershell
uv run pytest tests/integration -m integration
```

Crie a suíte em `tests/integration/` antes de tornar esta verificação obrigatória no CI. Limpe somente os diretórios temporários criados pelo runner.
