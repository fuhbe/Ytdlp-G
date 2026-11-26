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

Los vídeos se entregan en **MP4 con audio**, con resolución seleccionable entre las disponibles. Se unen pistas separadas y se convierten códecs incompatibles a H.264/AAC cuando hace falta.

El modo de audio entrega **solo MP3**: conserva MP3 si existe; de lo contrario, descarga el mejor audio y lo convierte a MP3 a 320 kbps. Convertir no mejora la fuente.

Se incluye yt-dlp 2026.11.23 y se buscan actualizaciones estables una vez al día antes de analizar/descargar. **Actualizar motor** permite buscar inmediatamente sin reinstalar la aplicación. Se verifican hashes SHA256 y scripts EJS correspondientes; los fallos conservan un motor utilizable.

Extrae todo el ZIP portátil y abre `Ytdlp-G.exe`, conservando las carpetas y
archivos que lo acompañan. Los paquetes no están firmados y SmartScreen puede
mostrar una advertencia. Windows 7 no es compatible; solo inspira el diseño.

La versión 1.3.0 se publica tras superar pruebas y verificaciones funcionales de los paquetes Windows. Consulta el [informe](docs/VALIDATION.md) y `Ytdlp-G-validation.zip` en el release. Las pruebas usan medios generados y servidor local; el proxy del entorno de desarrollo bloqueó la comprobación de YouTube (HTTP 403), por lo que no se validó una descarga real de YouTube. La compatibilidad depende de yt-dlp, la red y la fuente.

[Guía completa en inglés](README.md) · [Informar de un problema](https://github.com/fuhbe/Ytdlp-G/issues/new/choose).
Código propio: [MIT](LICENSE); [licencias de dependencias](THIRD_PARTY_NOTICES.md).
