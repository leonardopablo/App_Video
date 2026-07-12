"""
Lógica de descarga con yt-dlp: metadatos, detección de tipo de stream
y construcción de opciones optimizadas según el contenido.
"""

from io import BytesIO
from urllib.request import Request, urlopen

import yt_dlp

from utils import LOG, get_cookies_file, get_js_runtimes


class _YtdlpConsoleLogger:
    """Redirige el logging interno de yt-dlp a la consola."""

    def debug(self, msg: str) -> None:
        # yt-dlp prefija los mensajes de debug reales con "[debug] "
        if msg.startswith("[debug] "):
            LOG.debug("[yt-dlp] %s", msg)
        else:
            LOG.info("[yt-dlp] %s", msg)

    def warning(self, msg: str) -> None:
        LOG.warning("[yt-dlp] %s", msg)

    def error(self, msg: str) -> None:
        LOG.error("[yt-dlp] %s", msg)


def detect_stream_type(info: dict) -> str:
    """
    Detecta si el video es un VOD normal, un live activo,
    o un VOD grabado desde un live stream (replay).
    Retorna: 'normal' | 'live' | 'live_vod'
    """
    is_live = info.get("is_live", False)
    was_live = info.get("was_live", False)
    live_status = info.get("live_status", "")

    LOG.debug(
        "Stream type detection → is_live=%s | was_live=%s | live_status=%s",
        is_live, was_live, live_status,
    )

    if is_live or live_status == "is_live":
        return "live"
    if was_live or live_status in ("was_live", "post_live"):
        return "live_vod"
    return "normal"


def fetch_video_info(url: str) -> dict | None:
    """
    Obtiene metadatos del video usando yt-dlp (sin descargar).
    Lanza la excepción original si la extracción falla, para que la UI
    pueda distinguir errores (ej. bloqueo anti-bot de la red).
    """
    LOG.info("fetch_video_info → url=%s", url)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,
        "no_playlist": True,
        "logger": _YtdlpConsoleLogger(),
        "js_runtimes": get_js_runtimes(),
    }
    cookies = get_cookies_file()
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        duration = int(info.get("duration", 0)) if info.get("duration") else 0
        result = {
            "title": info.get("title", "Sin título"),
            "duration": duration,
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", "Desconocido"),
            "view_count": info.get("view_count", 0),
            "upload_date": info.get("upload_date", ""),
            "stream_type": detect_stream_type(info),
            "storyboard": _extract_storyboard(info),
        }
        LOG.info(
            "Metadata OK → title=%r | duration=%ds | stream_type=%s",
            result["title"], result["duration"], result["stream_type"],
        )
        return result

    except Exception as e:
        LOG.error("fetch_video_info failed: %s", e, exc_info=True)
        raise


def _extract_storyboard(info: dict) -> dict | None:
    """
    Extrae la pista de storyboard de mayor resolución (las miniaturas que
    YouTube muestra al pasar el mouse por la barra de progreso). Cada
    fragmento es una hoja-mosaico JPEG con rows×columns fotogramas.
    """
    best = None
    for f in info.get("formats", []):
        fid = str(f.get("format_id", ""))
        if fid.startswith("sb") and f.get("fragments"):
            if best is None or (f.get("height") or 0) > (best.get("height") or 0):
                best = f
    if not best:
        return None
    return {
        "rows": int(best.get("rows") or 5),
        "columns": int(best.get("columns") or 5),
        "fragments": [
            {"url": fr.get("url", ""), "duration": float(fr.get("duration") or 0)}
            for fr in best["fragments"]
        ],
    }


def storyboard_frame_at(storyboard: dict, t: float):
    """
    Devuelve el fotograma (PIL.Image) más cercano al segundo `t` del video,
    recortándolo de la hoja-mosaico correspondiente del storyboard.
    Retorna None si no se puede obtener.
    """
    from PIL import Image  # Pillow ya viene con Streamlit

    frags = storyboard.get("fragments") or []
    if not frags:
        return None

    rows = storyboard["rows"]
    cols = storyboard["columns"]
    tiles = max(rows * cols, 1)

    # Localizar la hoja que contiene el tiempo t
    acc = 0.0
    frag, offset = frags[-1], 0.0
    for fr in frags:
        d = fr["duration"] or 0
        if t < acc + d:
            frag, offset = fr, t - acc
            break
        acc += d
    else:
        frag = frags[-1]
        offset = max((frag["duration"] or 1) - 0.001, 0)

    tile_dur = (frag["duration"] / tiles) if frag["duration"] else 1.0
    idx = min(int(offset / tile_dur), tiles - 1)

    req = Request(frag["url"], headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as resp:
        sheet = Image.open(BytesIO(resp.read()))
        sheet.load()

    tile_w, tile_h = sheet.width // cols, sheet.height // rows
    if not tile_w or not tile_h:
        return None
    r, c = idx // cols, idx % cols
    tile = sheet.crop((c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h))

    # Las miniaturas son pequeñas (~160px): ampliar para poder arrastrar
    # el recuadro con precisión en la UI
    scale = max(1, round(640 / tile.width))
    if scale > 1:
        tile = tile.resize((tile.width * scale, tile.height * scale), Image.LANCZOS)
    return tile.convert("RGB")


def build_ydl_opts(
    fmt: str,
    output_path: str,
    stream_type: str = "normal",
    max_height: int | None = None,
    audio_bitrate: str = "320",
) -> dict:
    """
    Construye las opciones de yt-dlp para descarga COMPLETA con el
    downloader nativo. El recorte/conversión se hace después, localmente,
    con FFmpeg (processor.trim_media / process_to_tiktok).

    Por qué no se usa download_ranges: YouTube rechaza (HTTP 400 / I/O
    error) las peticiones que hace FFmpeg como descargador de secciones,
    tanto en VODs normales como en VODs de directos. Verificado 2026-07.

    Para VODs de directos recientes (post_live), los formatos planos
    apuntan a URLs de broadcast sin fragmentos resolubles ("Total
    fragments: 0"); las variantes del manifiesto MPD (id "NNN-dash") sí
    funcionan con el downloader nativo, por eso se prefieren.

    max_height limita la resolución de video (ej. 1080 → máx 1080p).
    None = mejor calidad disponible.
    """
    LOG.info(
        "build_ydl_opts → fmt=%s | stream_type=%s | max_height=%s",
        fmt, stream_type, max_height,
    )

    common = {
        "no_warnings": True,
        "outtmpl": output_path,
        "noplaylist": True,
        "logger": _YtdlpConsoleLogger(),
        "verbose": False,
        "quiet": False,  # necesario para que los progress_hooks reciban eventos
        "js_runtimes": get_js_runtimes(),
        # Descarga de fragmentos en paralelo: clave para VODs de directos,
        # que vienen en ~cientos de segmentos pequeños
        "concurrent_fragment_downloads": 8,
    }
    cookies = get_cookies_file()
    if cookies:
        common["cookiefile"] = cookies

    # Filtro de altura máxima para los selectores de formato
    h = f"[height<={max_height}]" if max_height else ""

    if stream_type in ("live_vod", "live"):
        LOG.info("⚡ Modo directo/VOD → preferir variantes del manifiesto MPD (-dash)")
        if fmt == "Audio (MP3)":
            common.update({
                "format": (
                    "bestaudio[format_id*=-dash][ext=m4a]"
                    "/bestaudio[ext=m4a]/bestaudio"
                ),
            })
        else:
            common.update({
                "format": (
                    f"bestvideo{h}[format_id*=-dash][ext=mp4]+bestaudio[format_id*=-dash][ext=m4a]"
                    f"/bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]"
                    f"/bestvideo{h}+bestaudio"
                    f"/best{h}/best"
                ),
                "merge_output_format": "mp4",
            })
    else:
        if fmt == "Audio (MP3)":
            common.update({
                "format": "bestaudio[ext=m4a]/bestaudio",
            })
        else:
            common.update({
                "format": (
                    f"bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]"
                    f"/bestvideo{h}+bestaudio"
                    f"/best{h}/best"
                ),
                "merge_output_format": "mp4",
            })

    return common
