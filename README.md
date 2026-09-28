# Dirpy Local Studio

Aplicacion web local para descargar, recortar y convertir videos de YouTube. La interfaz esta construida con Streamlit, las descargas se realizan con `yt-dlp` y el procesamiento multimedia se delega a FFmpeg.

## Funcionalidades

- Descarga de video en MP4 con seleccion de calidad maxima.
- Extraccion de audio en MP3 a 128, 192 o 320 kbps.
- Recorte preciso de un intervalo antes de guardar el resultado.
- Soporte para videos normales, directos y repeticiones de transmisiones.
- Conversion a formato vertical 9:16 para TikTok en 1080p o 4K.
- Encuadre manual y seguimiento por posiciones durante la conversion vertical.
- Reduccion de ruido, enfoque y ajuste de color opcionales.
- Deteccion automatica de codificacion por GPU mediante NVENC, QSV o AMF, con `libx264` como alternativa por CPU.

Los archivos terminados se guardan en la carpeta de descargas del usuario.

## Requisitos

- Python 3.10 o superior. El proyecto se ha probado con Python 3.12.
- [FFmpeg](https://ffmpeg.org/download.html), incluidos los comandos `ffmpeg` y `ffprobe`, disponible en el `PATH`.
- Conexion a Internet.
- [Deno 2 o superior](https://docs.deno.com/runtime/getting_started/installation/) recomendado. `yt-dlp` lo utiliza para resolver desafios de JavaScript de YouTube y evitar descargas lentas o fallidas.

Comprueba los requisitos externos con:

```bash
python --version
ffmpeg -version
ffprobe -version
deno --version
```

## Instalacion

Clona el repositorio o abre una terminal en la carpeta del proyecto.

### Windows (PowerShell)

```powershell
python -m venv env
.\env\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si PowerShell impide activar el entorno, puedes ejecutar los comandos directamente con `env\Scripts\python.exe`.

### macOS y Linux

```bash
python3 -m venv env
source env/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Instala FFmpeg si todavia no esta disponible:

```bash
# macOS con Homebrew
brew install ffmpeg

# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg
```

En Windows se puede instalar FFmpeg con `winget install Gyan.FFmpeg` y Deno con `winget install DenoLand.Deno`. Abre una terminal nueva despues de instalarlos para actualizar el `PATH`.

## Ejecucion

Con el entorno virtual activado, inicia la aplicacion:

```bash
streamlit run app.py
```

Streamlit mostrara la direccion local en la terminal, normalmente `http://localhost:8501`, y tratara de abrirla en el navegador.

En Windows tambien puedes iniciar sin activar el entorno:

```powershell
.\env\Scripts\python.exe -m streamlit run app.py
```

## Uso

1. Pega una URL valida de YouTube.
2. Elige video MP4 o audio MP3 y configura la calidad.
3. Selecciona el intervalo que quieres conservar.
4. Para video vertical, activa **Modo TikTok 9:16** y ajusta el encuadre si es necesario.
5. Pulsa el boton de descarga. La aplicacion descarga el contenido a una carpeta temporal, lo procesa con FFmpeg y guarda el resultado en `Descargas`.

La descarga inicial es completa porque YouTube puede rechazar las solicitudes parciales; el intervalo elegido se recorta localmente despues de descargarlo.

## Cookies de YouTube

Si YouTube solicita iniciar sesion para confirmar que no eres un bot, exporta las cookies de `youtube.com` en formato Netscape y guarda el archivo como `cookies.txt` en la raiz del proyecto o en la carpeta `Descargas`. La aplicacion lo detecta automaticamente.

`cookies.txt` contiene credenciales de sesion y esta excluido de Git. No lo compartas ni lo subas al repositorio.

## Conversion de un archivo local

El procesador vertical tambien puede utilizarse sin la interfaz web:

```bash
python processor.py entrada.mp4 salida.mp4
python processor.py entrada.mp4 salida.mp4 --no-4k
```

## Estructura

- `app.py`: interfaz de Streamlit y flujo principal.
- `downloader.py`: consulta de metadatos y configuracion de `yt-dlp`.
- `processor.py`: recorte, conversion y filtros de FFmpeg.
- `utils.py`: rutas, validaciones, logging y deteccion de FFmpeg/GPU.
- `frame_selector/index.html`: selector interactivo del encuadre 9:16.

## Aviso

Utiliza la aplicacion solo para contenido propio o para el que tengas permiso de descarga y respeta los terminos de servicio y la legislacion aplicable.
