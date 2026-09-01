# Instruções de testes de desempenho

## Objetivo

Validar o gate algorítmico de segmentação/contexto, sem usar um provider real. O critério é crescimento aproximadamente linear para entradas maiores, com memória limitada ao capítulo e contexto local.

## Execução proposta

1. Gere capítulos UTF-8 de 10 KiB, 100 KiB e 1 MiB com sentenças abaixo do limite.
2. Meça `segment_text` e `build_context` com `time.perf_counter` em processo isolado.
3. Compare a razão `tempo_1MiB / tempo_100KiB`; investigue razão muito acima de 10, após descontar ruído do ambiente.
4. Registre máquina, versão Python, tamanhos, tempos e seed no relatório de CI.

Não faça carga contra OpenCode Go neste MVP: custo, limites do provider e latência de rede não são um benchmark determinístico do algoritmo local.
