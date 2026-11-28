# Comparação local da CLI com o motor da interface gráfica

Linux x64, Python 3.12, FFmpeg 8.1.3, clipe sintético de 2 s em 640×360 a 25 FPS. Mediana de três processos novos por operação. Transferência nativa por HTTP local. A coluna CPU inclui os processos filhos. A coluna MiB/s divide o tamanho final pelo tempo total de download com validação.

| Operação | Total (s) | CPU (s) | MiB/s | Bytes | SHA-256 |
|---|---:|---:|---:|---:|---|
| CLI MP4 | 0.943 | 0.931 | 0.22 | 216893 | c64c38cb60955f43fc17a36358621333d3bd35c127bab6f3a7396a5e9ef7b556 |
| Motor da GUI MP4 | 0.975 | 0.973 | 0.21 | 216893 | c64c38cb60955f43fc17a36358621333d3bd35c127bab6f3a7396a5e9ef7b556 |
| CLI AV1 → H.264 | 0.589 | 0.743 | — | 263116 | 9e309208655819a41b7b1eb34e6b0fdc52d765c6bcc2e13892913c451c809759 |
| Conversor da GUI AV1 → H.264 | 0.602 | 0.781 | — | 263116 | 9e309208655819a41b7b1eb34e6b0fdc52d765c6bcc2e13892913c451c809759 |

As linhas da GUI exercitam as mesmas funções usadas pelos trabalhadores da interface. O tempo de abertura da janela e utilização de GPU física ficam fora desta medição.
