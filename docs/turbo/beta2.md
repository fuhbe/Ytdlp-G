# Ytdlp-G 1.4.0 Beta 2 — Simplicidade e Confiabilidade

Pré-release para avaliação no Windows 10/11 x64. O instalador usa a pasta e o atalho **Ytdlp-G Beta**. Para usar a edição portátil, extraia todo o ZIP e abra **Ytdlp-G.exe**. Os dois pacotes incluem yt-dlp, EJS, QuickJS, FFmpeg, FFprobe e aria2c. O motor continua verificando atualizações em segundo plano. A versão estável é a 1.3.0.

## Como testar

1. Cole o link de um vídeo que você tem autorização para baixar. Escolha **Vídeo MP4**, **Melhor qualidade disponível**, a pasta e **Baixar**. Você pode clicar em **Analisar** para selecionar uma combinação de resolução e FPS que o extrator encontrou.
2. Para conferir 60 FPS, use uma fonte conhecida de 60 ou 59,94 FPS. Abra o MP4 no VLC e consulte **Ferramentas → Informações sobre o codec**. Confira resolução, taxa de quadros e faixa de áudio. Uma fonte de 24 FPS deve continuar a 24 FPS.
3. Experimente uma playlist com resoluções diferentes. Em **Melhor qualidade disponível**, cada item recebe sua própria seleção. Após análise, **Até 1080p por vídeo** permite limitar a altura. **Ver detalhes** identifica os itens entregues abaixo do limite. Se todas as opções disponíveis excederem o limite, o item é informado como falha.
4. Teste **Somente áudio MP3** e as duas opções de saída, arquivos normais e ZIP. Faixas MP3 podem manter seu bitrate original. As outras são convertidas para MP3 a 320 kbps. Compare a quantidade, os prefixos de ordem e o conteúdo do ZIP.
5. Para retomar, use **Tentar novamente** ou repita o link, a qualidade, a pasta e a saída. A fila confere os arquivos já registrados. Quando o ZIP falha, as mídias ficam na subpasta de trabalho indicada em **Ver detalhes**. Uma nova tentativa de ZIP pode funcionar offline.
6. Em caso de erro, abra **Ver detalhes** e copie ou exporte o diagnóstico. Ele inclui etapas, posições na playlist, classes de erro e códigos HTTP reconhecidos. Os logs ficam em **Desempenho → Abrir logs**. Para o modo clássico, inicie o executável com `--classic`.

## O que foi corrigido

| Evidência na Beta 1 | Mudança na Beta 2 |
|---|---|
| A chave do catálogo continha apenas a altura. A lista comum copiava as características do primeiro item. O preenchimento por FFprobe não trazia FPS. | As opções individuais distinguem altura, FPS e faixa dinâmica informada. Taxas fracionárias e desconhecidas são tratadas separadamente. A playlist oferece melhor qualidade por item e limites de altura. |
| A interface só habilitava Baixar depois da análise completa. | A seleção padrão já está disponível ao colar o link. A fila consome a listagem com antecipação limitada enquanto baixa e processa os primeiros itens. |
| Exceções fora de três tipos atravessavam o resultado da tarefa e encerravam a playlist. Qualquer ValueError encerrava a recuperação mesmo quando causado pelo cache. | Falhas são registradas por item, com uma recuperação limitada e reextração convencional quando apropriado. Os resultados distinguem sucesso, sucesso parcial, falha, ZIP pendente e cancelamento. |
| O identificador do diretório temporário era truncado a 40 caracteres. Itens como 10 e 100 da mesma operação podiam compartilhar esse diretório. | A identidade curta inclui item, seleção e tentativa. Arquivos concluídos são registrados individualmente para retomada. |
| Uma exceção na limpeza podia ocorrer depois da publicação. A falha do ZIP deixava arquivos em staging sem ação de recuperação na interface. | Problemas de limpeza ficam no diagnóstico. O ZIP usa armazenamento sem recompressão, ZIP64 e verificação de integridade. Uma nova tentativa pode usar as mídias preservadas. |

Esses defeitos foram identificados no código e exercitados com mídias controladas. A causa específica do erro observado no computador do usuário depende do link e do diagnóstico dessa execução.

## Qualidade e compatibilidade

O modo simples preserva vídeo H.264, HEVC, VP9, AV1 e MPEG-4 compatível com MP4. Áudio incompatível com a política do aplicativo é convertido para AAC. Em formatos de vídeo que exigem conversão, o FFmpeg tenta encoders aprovados pelo teste funcional e tem recuperação por CPU. Uma conversão com perdas pode alterar a qualidade. Quando o HDR não puder ser preservado com segurança, o aplicativo informa o erro do item. O suporte a HEVC, AV1 e VP9 no player do Windows depende dos codecs instalados. O VLC é uma opção para verificar esses arquivos.

A janela simplificada aceita um link de vídeo ou playlist por operação. O modo clássico continua disponível para filas. O pacote de validação inclui o relatório de testes, verificações do executável empacotado, do instalador e da versão portátil, além da tentativa de acesso público ao YouTube. Os tempos medidos e as limitações estão no arquivo de benchmarks da pré-release.
