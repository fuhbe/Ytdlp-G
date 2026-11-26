## Ytdlp-G 1.3.0 — Estável / Stable

- **Motor atualizado:** yt-dlp 2026.11.23 incluído. O app verifica novas versões estáveis uma vez por dia antes de analisar/baixar. Use **Atualizar motor** para verificar imediatamente, sem reinstalar o aplicativo.
- **Vídeo com áudio em MP4:** escolha uma resolução disponível na fonte. O app junta as faixas separadas e entrega MP4 com som, convertendo codecs incompatíveis para H.264/AAC quando necessário.
- **Somente áudio em MP3:** mantém MP3 quando disponível; caso contrário, baixa o melhor áudio disponível e converte para MP3 a 320 kbps. Conversão não aumenta a qualidade da fonte.
- Funciona com links individuais, playlists, arquivos normais e ZIP.
- Atualizações do motor usam os pacotes oficiais do PyPI, SHA256 e scripts EJS correspondentes. A instalação é atômica e mantém um motor utilizável em caso de falha.

### Downloads

- `Ytdlp-G-Setup.exe`: instalador Windows 10/11 x64.
- `Ytdlp-G-portable.zip`: extraia tudo e abra `Ytdlp-G.exe`.
- `Ytdlp-G-validation.zip`: relatórios dos testes e dos três pacotes Windows.
- `SHA256SUMS.txt`: hashes dos arquivos publicados.

### Validation / limites

A publicação ocorre somente depois dos testes, lint, instalação/desinstalação e verificações funcionais dos executáveis Windows. Os testes verificam áudio MP3 e vídeo com áudio separado usando mídia gerada e servidor HTTP local, incluindo WebM/Vorbis → MP4 H.264/AAC e a ativação de um motor baixado dentro do executável. Os relatórios estão anexados.

O acesso ao YouTube neste ambiente de desenvolvimento foi bloqueado pelo proxy (HTTP 403); não foi possível validar um download real do YouTube. O suporte a cada site depende do yt-dlp, da rede e da disponibilidade do conteúdo. Atualizações automáticas reduzem problemas de motor antigo, mas não garantem que sites nunca mudarão. Os pacotes Windows continuam sem assinatura digital.
