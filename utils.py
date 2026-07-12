"""
Utilidades compartidas: logging, rutas, tiempo y detección de FFmpeg/GPU.
"""

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

# En Windows, evitar que cada subprocess de FFmpeg abra una ventana de consola
CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0


# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

def setup_console_logger() -> logging.Logger:
    """Logger a stderr con formato detallado (visible en la terminal)."""
    logger = logging.getLogger("dirpy_local")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s · %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


LOG = setup_console_logger()


# ─────────────────────────────────────────────
#  TIEMPO
# ─────────────────────────────────────────────

def seconds_to_hms(total_seconds: int) -> str:
    td = timedelta(seconds=total_seconds)
    hours, remainder = divmod(int(td.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def seconds_to_ffmpeg_ts(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ─────────────────────────────────────────────
#  RUTAS Y ARCHIVOS
# ─────────────────────────────────────────────

def get_downloads_folder() -> Path:
    system = platform.system()
    if system == "Windows":
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ) as key:
                downloads = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
                return Path(downloads)
        except Exception:
            return Path.home() / "Downloads"
    if system == "Darwin":
        return Path.home() / "Downloads"
    xdg = os.environ.get("XDG_DOWNLOAD_DIR")
    return Path(xdg) if xdg else Path.home() / "Downloads"


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def is_valid_youtube_url(url: str) -> bool:
    patterns = [
        r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)",
        r"(https?://)?(www\.)?youtube\.com/embed/",
    ]
    return any(re.search(p, url) for p in patterns)


def extract_video_id(url: str) -> str | None:
    """Extrae el ID de 11 caracteres de una URL de YouTube."""
    patterns = [
        r"youtube\.com/watch\?(?:[^#]*&)?v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


# ─────────────────────────────────────────────
#  RUNTIME DE JAVASCRIPT PARA YT-DLP
# ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_js_runtimes() -> dict:
    """
    Localiza un runtime de JavaScript para yt-dlp. Sin uno, yt-dlp no puede
    resolver el desafío anti-bot de YouTube (parámetro "n") y las descargas
    quedan estranguladas a velocidad de goteo.

    Prioriza deno (el recomendado por yt-dlp, requiere ≥2.0). Busca también
    en las rutas de instalación de winget por si el PATH del proceso actual
    aún no lo incluye (winget modifica el PATH solo para shells nuevos).
    """
    candidates: list = [shutil.which("deno")]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(Path(local) / "Microsoft" / "WinGet" / "Links" / "deno.exe")
        pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if pkgs.is_dir():
            candidates.extend(pkgs.glob("DenoLand.Deno*/deno.exe"))

    for c in candidates:
        if c and Path(c).exists():
            LOG.info("Runtime JS para yt-dlp: deno → %s", c)
            return {"deno": {"path": str(c)}}

    LOG.warning(
        "No se encontró deno: yt-dlp usará su detección por defecto "
        "(las descargas pueden ir lentas sin runtime JS)"
    )
    return {"deno": {}}


def get_cookies_file() -> str | None:
    """
    Busca un cookies.txt exportado por el usuario (formato Netscape).
    Necesario cuando YouTube bloquea la red con "Sign in to confirm
    you're not a bot". Se busca junto a la app y en Descargas.
    """
    candidates = [
        Path(__file__).parent / "cookies.txt",
        get_downloads_folder() / "cookies.txt",
    ]
    for c in candidates:
        if c.exists():
            LOG.info("Usando cookies de: %s", c)
            return str(c)
    return None


# ─────────────────────────────────────────────
#  FFMPEG / HARDWARE
# ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=1)
def detect_gpu_encoder() -> str | None:
    """
    Detecta un encoder H.264 por hardware realmente funcional
    (no basta con que esté compilado en FFmpeg: se prueba codificando
    un frame de prueba). Orden de preferencia: NVENC → QSV → AMF.
    Retorna el nombre del encoder o None si solo hay CPU.
    """
    candidates = ["h264_nvenc", "h264_qsv", "h264_amf"]
    for enc in candidates:
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=black:size=256x256:duration=0.1",
                    "-frames:v", "1", "-c:v", enc, "-f", "null", "-",
                ],
                capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                LOG.info("Encoder GPU detectado y funcional: %s", enc)
                return enc
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
    LOG.info("Sin encoder GPU funcional → se usará libx264 (CPU)")
    return None


def ffprobe_info(video_path: str) -> dict:
    """
    Obtiene metadatos del video local: ancho, alto, duración, fps.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json", str(video_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
        creationflags=CREATE_NO_WINDOW,
    )
    data = json.loads(result.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]

    # La duración puede venir en el stream o en el format
    duration = stream.get("duration") or data.get("format", {}).get("duration") or 0
    fps = 30.0
    rate = stream.get("avg_frame_rate", "30/1")
    try:
        num, den = rate.split("/")
        if float(den) > 0:
            fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        pass

    return {
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "duration": float(duration),
        "fps": fps,
    }
