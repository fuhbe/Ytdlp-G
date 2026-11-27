# Ytdlp-G 1.4.0 Beta 3 — medições de compatibilidade

Comparamos a tag Beta 2 (`adf637a`) com a Beta 3 (`f86d50f`) no mesmo ambiente Linux x64, com Python 3.12.14, yt-dlp 2026.11.23 e FFmpeg 8.1.3. Usamos as mesmas entradas sintéticas de dois segundos em 640×360 a 25 FPS com áudio AAC estéreo a 48 kHz. A tabela mostra a mediana de três execuções por versão. SSIM compara os quadros de saída com a entrada decodificada pelo FFmpeg. Um valor de 1 nessa medição indica quadros idênticos.

| Operação | Beta 2 (s) | Beta 3 (s) | Beta 2 (bytes) | Beta 3 (bytes) | SSIM Beta 2 | SSIM Beta 3 |
|---|---:|---:|---:|---:|---:|---:|
| Download de MP4 H.264/AAC por HTTP local | 0,148 | 0,120 | 216893 | 216893 | 1,000000 | 1,000000 |
| Remux de H.264/AAC de MKV para MP4 | 0,110 | 0,094 | 216922 | 216922 | 1,000000 | 1,000000 |
| Conversão de FFV1 para H.264 por CPU | 0,278 | 0,254 | 264792 | 264792 | 0,923937 | 0,923937 |
| MP4 AV1 na configuração padrão de cada versão | 0,022 | 0,219 | 179007 | 263116 | 1,000000 | 0,997241 |

A Beta 2 mantinha o vídeo AV1. Com Máxima compatibilidade, a Beta 3 converteu esse vídeo em H.264 e copiou o áudio AAC. O arquivo ficou 47% maior nesta amostra. Quem prefere conservar AV1 pode escolher **Formato original**. Para o MP4 que já continha H.264/AAC, as duas versões entregaram o mesmo tamanho e o mesmo conteúdo visual.

## Como reproduzir

Use o script `docs/turbo/bench_compat.py` da Beta 3 com `PYTHONPATH` apontando para o diretório `src` de cada versão e passe a mesma pasta de mídia como argumento. O script gera os arquivos na primeira execução. No download, a medição começa depois da análise do link. O servidor usa a interface de loopback e o downloader nativo. Nas conversões, a cópia da entrada de teste e o cálculo posterior do SSIM ficam fora do cronômetro. O encoder utilizado foi libx264.

Esta amostra curta inclui os custos de inicialização do processo e da validação. Os tempos em vídeos longos e na internet dependem da mídia, da rede e do computador. O ambiente de testes não tinha Intel Quick Sync, NVIDIA NVENC nem AMD AMF disponíveis para medir velocidade ou qualidade em GPU física. O ZIP de validação registra os testes de fallback, os testes de hardware pulados e a tentativa separada de acesso ao YouTube. A reprodução no projetor Android precisa ser confirmada no aparelho.
