# Benchmarks locais do Ytdlp-G 1.4.0 Beta 2

Referência da Beta 2 `38f6e895ce17470bfbce47d0133c874438c954be`. Comparação com as medições registradas da versão 1.3.0 e da Beta 1. Medianas de três execuções por fluxo, com mídia sintética em HTTP local, Linux x64, Python 3.12.14 e FFmpeg 7.1.5. Nos testes HLS, cada pedido de segmento recebeu 40 ms de latência. As rodadas ocorreram em momentos diferentes no ambiente compartilhado.

| Medida | 1.3.0 | Beta 1 | Beta 2 |
|---|---:|---:|---:|
| Inicialização com diagnóstico (s) | 0.825605 | 0.865109 | 0.789602 |
| Primeira análise de MP4 (s) | 0.155135 | 0.178248 | 0.19683 |
| Reanálise (s) | 0.132696 | 0.00021444 | 9.9976e-05 |
| Extrações por análise + download | 3 | 1 | 1 |
| Download até primeiro evento de transferência após análise (s) | 0.190022 | 0.124373 | 0.055655 |
| Download e publicação de MP4 após análise (s) | 0.275189 | 0.240208 | 0.236083 |
| Publicação de 32 MiB no mesmo volume (s) | 0.135342 | 0.000105821 | 5.7973e-05 |
| ZIP de 32 MiB verificado (s) | 0.259686 | 0.183617 | 0.171976 |
| Análise HLS (s) | 0.221822 | 0.225396 | 0.268586 |
| Download e processamento HLS (s) | 1.35653 | 0.574152 | 0.698825 |
| Análise de playlist (s) | 0.523919 | 0.397012 | 0.457359 |
| Download e conversão de seis MP3 (s) | 2.77029 | 1.68923 | 1.83856 |
| Pico de RSS do processo principal (KiB) | 76812 | 87948 | 88660 |
| Maior pico de RSS de processo filho (KiB) | 111948 | 111688 | 111048 |
| CPU do processo principal (s) | 5.20074 | 3.64221 | 3.62667 |
| CPU acumulada dos filhos (s) | 22.4342 | 20.5262 | 21.5568 |

Em relação à Beta 1, caiu o tempo entre o início do download de MP4 e a transferência. A análise inicial, o HLS e a playlist MP3 ficaram mais lentos nesta rodada. A Beta 2 ainda foi mais rápida que a 1.3.0 nos dois downloads HLS e playlist. Os tempos de HLS e playlist incluem processamento. O pico de RSS do processo principal subiu de 87.948 para 88.660 KiB entre as betas.

A seleção padrão progressiva elimina a etapa de análise detalhada obrigatória. Os números acima medem a mesma sequência de análise opcional seguida de download para comparar as três versões. O custo de pós-processamento foi medido junto do download. Os dados de rede local não estimam velocidade na internet.

O proxy local bloqueou o YouTube com HTTP 403. O relatório de validação contém uma tentativa independente no runner Windows. Não houve dispositivo compatível disponível para testar Quick Sync, NVENC e AMF em hardware. O fallback por CPU foi exercitado com falha simulada de encoder.

Scripts reproduzíveis em `docs/turbo/bench_local.py` e `docs/turbo/bench_network.py`.
