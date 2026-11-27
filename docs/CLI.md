# Ytdlp-G CLI 0.1.0 Beta 1

No Windows x64, abra Ytdlp-G-CLI.exe para usar o menu numerado. A versão portátil inclui ytdlp-g.exe e os componentes já extraídos. Extraia o ZIP inteiro. No PowerShell, abra a pasta e execute:

```powershell
.\ytdlp-g --version
.\ytdlp-g download "LINK" --mp4 --compatible --quality 1080
.\ytdlp-g download "PLAYLIST" --playlist --mp3 --zip
.\ytdlp-g download --input-file links.txt --best
Get-Content links.txt | .\ytdlp-g download --input-file - --json
.\ytdlp-g convert "D:\VIDEOS" --compatible --recursive
.\ytdlp-g config --language pt-BR --destination "D:\VIDEOS" --downloads 2 --conversions 1
.\ytdlp-g queue list
.\ytdlp-g queue retry
.\ytdlp-g history
.\ytdlp-g doctor
.\ytdlp-g update
```

O executável avulso contém as mesmas ferramentas e as extrai ao iniciar. A versão portátil inicia mais rapidamente. O menu aceita números seguidos de Enter. A saída JSON usa stdout. Mensagens de progresso usam stderr no modo textual. Use --help em cada comando. O limite de resolução vale para cada vídeo. Use --original para manter codecs como AV1 ou --legacy para limitar a 720p30. A reprodução depende do aparelho. O modo MP3 preserva a faixa MP3 disponível ou converte a melhor faixa para 320 kbps. O conversor grava em Convertidos e preserva os originais.

A fila guarda pedidos localmente no perfil do usuário. Use queue pause, resume, cancel ou retry com um número para selecionar o pedido. Use queue run após fechar inesperadamente. Downloads de uma playlist podem ocorrer em paralelo. A fila processa links avulsos em ordem. O controlador observa pedidos de pausa e cancelamento nos eventos de progresso. Uma operação de rede bloqueada pode demorar a emitir o próximo evento. Mantenha a pasta de destino para reaproveitar itens concluídos após falhas. O histórico mostra resultados sanitizados. Use clear-cache para limpar o cache de análise.

O motor, os perfis de compatibilidade, a publicação atômica de arquivos e o conversor vêm da edição gráfica Beta 3. O terminal usa argparse e SQLite da biblioteca padrão. O pacote de terminal exclui Qt. As ferramentas externas conservam suas próprias licenças. Os avisos e as origens estão na pasta de licenças incluída nos pacotes.
