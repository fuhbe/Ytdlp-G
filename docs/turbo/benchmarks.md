# Ytdlp-G 1.4.0 Beta 1 — Turbo Engine

Comparação local com a tag v1.3.0. Beta compilada a partir de fc603f68001397ffd99a7bb6435c32f908eef064. Três repetições por fluxo; valores medianos. Ambiente Linux x64 compartilhado, Python 3.12.14, ffmpeg version 7.1.5-0+deb13u1 Copyright (c) 2000-2026 the FFmpeg developers. Mídia sintética, HTTP em loopback, sem limite de banda. O teste HLS acrescenta 40 ms de espera por GET de segmento. A playlist HTML tem seis itens. O benchmark de disco usa 32 MiB no mesmo volume. A medição de inicialização inclui a janela offscreen, diagnóstico e encerramento; não mede tempo até o primeiro pixel. As cargas do ambiente podem variar entre execuções.

| Medida | 1.3.0 | Beta 1 | Variação |
|---|---:|---:|---:|
| Inicialização com diagnóstico (s) | 0.825605 | 0.865109 | +4.8% |
| Primeira análise de MP4 (s) | 0.155135 | 0.178248 | +14.9% |
| Reanálise do mesmo link (s) | 0.132696 | 0.00021444 | -99.8% |
| Extrações por análise + download | 3 | 1 | -66.7% |
| Seleção até o primeiro evento de transferência (s) | 0.190022 | 0.124373 | -34.5% |
| Download e publicação do MP4 (s) | 0.275189 | 0.240208 | -12.7% |
| Publicação de arquivo concluído de 32 MiB (s) | 0.135342 | 0.000105821 | -99.9% |
| ZIP de 32 MiB com verificação e publicação (s) | 0.259686 | 0.183617 | -29.3% |
| Análise HLS (s) | 0.221822 | 0.225396 | +1.6% |
| Download HLS com pós-processamento (s) | 1.35653 | 0.574152 | -57.7% |
| Vazão HLS efetiva (MiB/s) | 0.620738 | 1.4666 | +136.3% |
| Tamanho final do HLS (bytes) | 882954 | 882954 | +0.0% |
| Análise da playlist (s) | 0.523919 | 0.397012 | -24.2% |
| Playlist para MP3, incluindo conversão (s) | 2.77029 | 1.68923 | -39.0% |
| Seis MP3 finais (bytes) | 1.93811e+06 | 1.93811e+06 | +0.0% |
| Pico de RSS do processo principal (KiB) | 76812 | 87948 | +14.5% |
| Maior pico de RSS de um filho (KiB) | 111948 | 111688 | -0.2% |
| CPU do processo principal (s) | 5.20074 | 3.64221 | -30.0% |
| CPU acumulada dos filhos (s) | 22.4342 | 20.5262 | -8.5% |
| Blocos de entrada do processo | 280 | 0 | -100.0% |
| Blocos de saída do processo | 59552 | 42704 | -28.3% |

## Conversão de CPU

Uma execução por preset na mesma máquina. Amostra de oito segundos a 640×360, 24 fps, duas threads x264, CRF 18. SSIM calculado contra a entrada decodificada. Medições não demonstram equivalência perceptual em outros conteúdos.

| Preset | Tempo (s) | Bytes | SSIM |
|---|---:|---:|---:|
| medium | 1.212 | 1053683 | 0.998191 |
| fast | 1.038 | 1077234 | 0.998103 |
| faster | 0.976 | 1040366 | 0.997881 |
| veryfast | 0.806 | 1017111 | 0.997238 |

## Limites e reprodução

O teste sem cache de MP4 e a inicialização com diagnóstico ficaram mais lentos nesta rodada. O cache retém dados em RAM e elevou o pico do processo. Ganhos em loopback não são previsão de velocidade na internet. Os tempos incluem pós-processamento onde indicado. Não foi isolado o tempo de mux, nem medido o uso de GPU. Sem GPU/driver disponível para comparar Quick Sync, NVENC e AMF, decodificação acelerada, consumo ou qualidade. Acesso ao YouTube bloqueado pelo proxy com HTTP 403. A responsividade numa máquina Iris Xe de 8 GB com mídia 4K requer teste no equipamento. Não foi medido ganho de aria2c em servidores públicos.

Execute bench_local.py e bench_network.py com PYTHONPATH apontando para src de cada checkout, no mesmo ambiente de dependências. Os scripts imprimem JSON com as amostras agregadas. Compare as mesmas versões de FFmpeg, yt-dlp e Python.
