# Ytdlp-G

Una aplicación compacta para Windows 10/11 x64, con un aspecto inspirado en
Windows 7 Aero. Descarga vídeos, audio y listas de reproducción como archivos
normales o en un solo ZIP. No necesitas instalar Python.

[Descargar instalador](https://github.com/fuhbe/Ytdlp-G/releases/latest/download/Ytdlp-G-Setup.exe)
· [ZIP portátil](https://github.com/fuhbe/Ytdlp-G/releases/latest/download/Ytdlp-G-portable.zip)
· [Notas de versión y hashes](https://github.com/fuhbe/Ytdlp-G/releases/latest)

1. Pega un enlace y pulsa **Analizar**.
2. Elige el contenido, una calidad disponible y archivos normales o ZIP.
3. Elige la carpeta y pulsa **Descargar**.

Para MP3, selecciona solo audio y la opción MP3 de alta calidad. La aplicación
descarga el mejor audio disponible y lo convierte a MP3 a 320 kbps. Las fuentes
que ya son MP3 se conservan sin otra conversión. Convertir no mejora la calidad
original. Las listas muestran calidades nativas comunes a los elementos accesibles.

Extrae todo el ZIP portátil y abre `Ytdlp-G.exe`, conservando las carpetas y
archivos que lo acompañan. Los paquetes no están firmados y SmartScreen puede
mostrar una advertencia. Windows 7 no es compatible; solo inspira el diseño.

La versión 1.2.0 superó 78 pruebas en Windows y 19 comprobaciones funcionales en
cada paquete, ZIP extraído y aplicación instalada. Consulta el [informe](docs/VALIDATION.md).
La compatibilidad con sitios depende de yt-dlp y de la disponibilidad de la fuente.

[Guía completa en inglés](README.md) · [Informar de un problema](https://github.com/fuhbe/Ytdlp-G/issues/new/choose).
Código propio: [MIT](LICENSE); [licencias de dependencias](THIRD_PARTY_NOTICES.md).
