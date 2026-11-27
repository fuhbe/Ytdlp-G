# Ytdlp-G 1.4.0 Beta 3 — Compatibility Update

Pré-release para Windows 10/11 x64. Inclui o conversor offline e os componentes necessários. O instalador usa o atalho **Ytdlp-G Beta**. Na versão portátil, extraia a pasta inteira e abra **Ytdlp-G.exe**.

| Perfil de vídeo | Resultado |
|---|---|
| Máxima compatibilidade (padrão) | MP4 com vídeo H.264 de 8 bits em 4:2:0 e áudio AAC-LC estéreo a 44,1 ou 48 kHz. Preserva a resolução e a cadência da fonte. Converte HDR sinalizado para SDR BT.709 quando o FFmpeg consegue realizar o mapeamento de tons. |
| Formato original (mais rápido) | Preserva codecs aceitos pelo MP4, inclusive AV1, VP9 e HEVC. Conserva HDR quando possível. Alguns projetores precisam de outro perfil. |
| Aparelhos antigos | Até 1280×720 e 30 FPS, SDR, H.264 Baseline até nível 3.1 e áudio AAC-LC. A conversão pode reduzir a resolução e descartar quadros. |

A disponibilidade de 4K, 60 FPS e HDR depende da fonte. A reprodução depende do decodificador, do perfil, do nível H.264 e da vazão aceita pelo aparelho. A conversão para H.264 pode levar mais tempo, gerar um arquivo maior e introduzir perda de qualidade. O aplicativo copia faixas que já atendem ao perfil. Falhas de encoder podem ser recuperadas usando os mesmos arquivos locais.

## Teste no projetor

1. Abra **Converter vídeos existentes** e selecione um dos MP4 AV1 da sua pasta de vídeos. Mantenha **Máxima compatibilidade** e clique em **Converter**.
2. Copie o novo MP4 da pasta **Convertidos** para o projetor. Confira imagem, som, duração e sincronismo. O vídeo de referência 1920×1080 a 25 FPS deve continuar com essas características.
3. Se o aparelho ainda recusar o arquivo, repita o teste com **Aparelhos antigos**. Para converter o restante, selecione a pasta, marque subpastas se necessário e escolha a pasta de saída. Arquivos já compatíveis podem ser ignorados ou copiados.
4. Para novos downloads, cole o link, escolha **Vídeo MP4**, a qualidade, o perfil e a pasta. A seleção de áudio MP3 mantém o fluxo anterior.

## Validação e dependências

As verificações automatizadas usam FFprobe e decodificação real com FFmpeg. O projetor físico e a Intel Iris Xe do usuário precisam de teste pessoal. O ZIP de validação inclui os relatórios Windows e Linux, as verificações de instalação e modo portátil e o resultado da tentativa de acesso público ao YouTube.

Esta beta utiliza as mesmas dependências, versões fixadas e licenças da Beta 2. A distribuição inclui avisos de Python, Qt, FFmpeg GPL, aria2 e QuickJS. A revisão das novas rotas verificou argumentos FFmpeg sem shell, restrição de protocolos no processamento local, separação entre entrada e saída e publicação sem sobrescrita dos arquivos do usuário. O manifesto com as origens dos binários acompanha o pacote.
