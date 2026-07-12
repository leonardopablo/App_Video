"""
Post-procesado con FFmpeg: conversión a formato vertical 9:16 (TikTok)
con mejoras de imagen — escalado 4K, reducción de ruido, realce de
detalle y colores más vibrantes. Usa GPU (NVENC/QSV/AMF) si hay una
disponible y funcional; si no, cae a libx264 (CPU).

También es ejecutable directo sobre un archivo local:
    python processor.py entrada.mp4 [salida.mp4] [--no-4k]
"""

import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Callable

from utils import CREATE_NO_WINDOW, LOG, detect_gpu_encoder, ffprobe_info


@lru_cache(maxsize=8)
def ffmpeg_has_filter(name: str) -> bool:
    """Comprueba si el FFmpeg instalado incluye un filtro dado."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        return re.search(rf"\s{re.escape(name)}\s", result.stdout) is not None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _even(n: int) -> int:
    """Los encoders H.264 requieren dimensiones pares."""
    return n - (n % 2)


#  Duración (s) del paneo suave entre dos posiciones de encuadre
PAN_TRANSITION = 1.0


def _pos_expr(points: list[tuple[float, int]]) -> str:
    """
    Construye una expresión FFmpeg pos(t) a partir de keyframes (t, px):
    mantiene cada posición y desliza linealmente hacia la siguiente
    durante el último PAN_TRANSITION segundos antes de su keyframe.

    Forma: suma de rampas acotadas con clip():
        x(t) = x0 + Σ Δxi · clip((t - inicio_rampa_i) / duración_i, 0, 1)
    Las rampas no se solapan, así que cada término aporta 0 antes de su
    rampa y Δxi completo después.

    La suma se agrupa como ÁRBOL BALANCEADO ((a+b)+(c+d)) porque el
    evaluador de expresiones de FFmpeg procesa las cadenas a+b+c+...
    recursivamente y falla ("Failed to configure input pad") con ~100
    operaciones encadenadas; balanceado, 300 términos son ~9 niveles.
    (También se probó if() anidado: mismo límite de profundidad.)
    """
    points = sorted(points)
    values = {px for _, px in points}
    if len(values) == 1:
        return str(points[0][1])

    terms = [str(points[0][1])]
    for (t0, x0), (t1, x1) in zip(points, points[1:]):
        dx = x1 - x0
        if dx == 0:
            continue
        ramp_start = max(t1 - PAN_TRANSITION, t0)
        ramp_len = max(t1 - ramp_start, 0.05)
        terms.append(f"({dx})*clip((t-{ramp_start:.3f})/{ramp_len:.3f},0,1)")

    def balanced(ts: list[str]) -> str:
        if len(ts) == 1:
            return ts[0]
        mid = len(ts) // 2
        return f"({balanced(ts[:mid])}+{balanced(ts[mid:])})"

    return balanced(terms)


def build_tiktok_filters(
    src_w: int,
    src_h: int,
    upscale_4k: bool = True,
    denoise: bool = True,
    sharpen: bool = True,
    vibrant: bool = True,
    crop_keyframes: list[tuple[float, float, float]] | None = None,
) -> str:
    """
    Construye la cadena de filtros de video:
      1. Recorte a proporción 9:16 — centrado por defecto, o siguiendo
         las posiciones de encuadre del usuario (crop_keyframes: lista de
         (segundo_relativo_al_clip, centro_x_fraccion, centro_y_fraccion)),
         con paneo suave entre posiciones.
      2. Escalado Lanczos a 2160x3840 (4K vertical) o 1080x1920.
      3. hqdn3d      → reducción de ruido digital.
      4. unsharp     → realce de detalle fino (rostros, texturas).
      5. vibrance/eq → colores más vibrantes y contraste profesional.
    """
    filters: list[str] = []

    # ── 1. Crop a 9:16 (dimensiones calculadas con ffprobe) ──
    crop_w = _even(min(src_w, round(src_h * 9 / 16)))
    crop_h = _even(min(src_h, round(crop_w * 16 / 9)))
    if (crop_w, crop_h) != (src_w, src_h):
        if crop_keyframes:
            # Tope de keyframes: grabaciones muy largas podrían exceder el
            # límite de longitud de línea de comandos de Windows (~32k)
            if len(crop_keyframes) > 300:
                step = len(crop_keyframes) / 300
                sampled = [crop_keyframes[int(i * step)] for i in range(300)]
                sampled[-1] = crop_keyframes[-1]
                LOG.info(
                    "Keyframes de encuadre reducidos: %d → %d",
                    len(crop_keyframes), len(sampled),
                )
                crop_keyframes = sampled

            def px(frac: float, span: int, crop_span: int) -> int:
                # centro fraccional → esquina superior/izquierda en píxeles
                return max(0, min(round(frac * span - crop_span / 2), span - crop_span))

            xs = [(t, px(cx, src_w, crop_w)) for t, cx, _ in crop_keyframes]
            ys = [(t, px(cy, src_h, crop_h)) for t, _, cy in crop_keyframes]
            # Las comas dentro de if() exigen comillas en el filtergraph
            filters.append(
                f"crop={crop_w}:{crop_h}:x='{_pos_expr(xs)}':y='{_pos_expr(ys)}'"
            )
        else:
            filters.append(f"crop={crop_w}:{crop_h}")  # centrado por defecto

    # ── 2. Escalado ──
    target = "2160:3840" if upscale_4k else "1080:1920"
    filters.append(f"scale={target}:flags=lanczos")

    # ── 3. Reducción de ruido (antes del sharpening) ──
    if denoise:
        filters.append("hqdn3d=2:1.5:4:4")

    # ── 4. Realce de detalle ──
    if sharpen:
        filters.append("unsharp=5:5:0.9:5:5:0.0")

    # ── 5. Color ──
    if vibrant:
        if ffmpeg_has_filter("vibrance"):
            # vibrance realza saturación solo en tonos apagados
            # (protege los tonos de piel — look más profesional)
            filters.append("vibrance=intensity=0.25")
        filters.append("eq=contrast=1.05:saturation=1.12:gamma=0.99")

    filters.append("format=yuv420p")
    return ",".join(filters)


def _encoder_args(encoder: str | None, upscale_4k: bool) -> list[str]:
    """Argumentos de encoding según el hardware disponible."""
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                "-cq", "21", "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "21"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "quality",
                "-rc", "cqp", "-qp_i", "20", "-qp_p", "22"]
    # CPU: preset fast (a 4K, 'medium' se vuelve demasiado lento)
    preset = "fast" if upscale_4k else "medium"
    return ["-c:v", "libx264", "-preset", preset, "-crf", "20"]


def _run_ffmpeg_with_progress(
    cmd: list[str],
    total_seconds: float,
    progress_cb: Callable[[float, str], None] | None = None,
) -> tuple[bool, str]:
    """
    Ejecuta FFmpeg reportando progreso via progress_cb(fraccion, texto).
    El comando debe incluir '-progress pipe:1 -nostats'.
    Retorna (exito, mensaje_o_stderr).
    """
    proc = None
    try:
        # stderr va a un ARCHIVO temporal, no a un pipe: si FFmpeg emite
        # muchos errores, un pipe sin lector se llena y congela el proceso
        # para siempre (deadlock). Un archivo nunca se llena.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stderr_f:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=stderr_f,
                stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )

            # FFmpeg emite líneas clave=valor por -progress pipe:1.
            # out_time_ms viene en MICROsegundos (a pesar del nombre).
            # El valor puede retroceder por el intercalado audio/video del
            # muxer, así que se fuerza progreso monotónico.
            last_frac = 0.0
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_ms=") and total_seconds > 0:
                    try:
                        done_s = int(line.split("=")[1]) / 1_000_000
                        frac = max(last_frac, min(done_s / total_seconds, 1.0))
                        last_frac = frac
                        if progress_cb:
                            progress_cb(frac, f"Procesando {done_s:.0f}s / {total_seconds:.0f}s")
                    except ValueError:
                        pass
                elif line == "progress=end" and progress_cb:
                    progress_cb(1.0, "Finalizando…")

            proc.wait()
            stderr_f.seek(0)
            stderr_tail = stderr_f.read()[-800:]

        if proc.returncode != 0:
            LOG.error("FFmpeg falló (código %s): %s", proc.returncode, stderr_tail)
            return False, f"FFmpeg falló (código {proc.returncode}): {stderr_tail}"
        return True, ""

    except FileNotFoundError:
        return False, "FFmpeg no está instalado o no está en el PATH."
    except Exception as e:
        # Las excepciones de control de Streamlit (rerun/stop, lanzadas
        # dentro de progress_cb) deben propagarse, no tratarse como fallo
        if e.__class__.__module__.startswith("streamlit"):
            raise
        LOG.error("Error ejecutando FFmpeg: %s", e, exc_info=True)
        return False, str(e)
    finally:
        # Si el script de Streamlit se interrumpe (rerun del usuario) u
        # ocurre cualquier error, NO dejar un FFmpeg huérfano corriendo.
        if proc is not None and proc.poll() is None:
            LOG.warning("Interrumpido: terminando proceso FFmpeg huérfano")
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


def trim_media(
    input_path: str,
    output_path: str,
    start_sec: int,
    end_sec: int,
    to_mp3: bool = False,
    audio_bitrate: str = "320",
    progress_cb: Callable[[float, str], None] | None = None,
) -> tuple[bool, str]:
    """
    Recorta un archivo local con precisión (re-encodeando, con GPU si hay).
    El -ss va ANTES del -i: seek rápido a keyframe + decodificación exacta
    hasta el punto pedido — corte preciso sin procesar todo el archivo.
    """
    fragment = end_sec - start_sec

    if to_mp3:
        codec_args = ["-vn", "-c:a", "libmp3lame", "-b:a", f"{audio_bitrate}k"]
    else:
        encoder = detect_gpu_encoder()
        codec_args = [
            *_encoder_args(encoder, upscale_4k=False),
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
        ]

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_sec),
        "-i", str(input_path),
        "-t", str(fragment),
        *codec_args,
        "-progress", "pipe:1", "-nostats",
        str(output_path),
    ]

    LOG.info(
        "trim_media → %s [%ds-%ds] mp3=%s", Path(input_path).name,
        start_sec, end_sec, to_mp3,
    )
    ok, err = _run_ffmpeg_with_progress(cmd, fragment, progress_cb)
    if ok:
        LOG.info("Recorte completado → %s", output_path)
        return True, str(output_path)
    return False, err


def process_to_tiktok(
    input_path: str,
    output_path: str,
    upscale_4k: bool = True,
    denoise: bool = True,
    sharpen: bool = True,
    vibrant: bool = True,
    progress_cb: Callable[[float, str], None] | None = None,
    start_sec: int | None = None,
    end_sec: int | None = None,
    crop_keyframes: list[tuple[float, float, float]] | None = None,
) -> tuple[bool, str]:
    """
    Convierte un video local a vertical 9:16 con mejoras de imagen.
    Si se pasan start_sec/end_sec, recorta en la misma pasada (evita
    re-encodear dos veces). crop_keyframes posiciona el encuadre en el
    tiempo (segundos RELATIVOS al inicio del clip: con -ss de input,
    los timestamps del filtro empiezan en 0).

    progress_cb recibe (fraccion_0_a_1, texto_estado) durante el proceso.
    Retorna (exito, mensaje).
    """
    info = ffprobe_info(input_path)
    src_w, src_h, duration = info["width"], info["height"], info["duration"]

    if not src_w or not src_h:
        return False, "No se pudieron leer las dimensiones del video de entrada."

    seek_args: list[str] = []
    if start_sec is not None and end_sec is not None:
        seek_args = ["-ss", str(start_sec)]
        duration = end_sec - start_sec

    vf = build_tiktok_filters(
        src_w, src_h, upscale_4k, denoise, sharpen, vibrant,
        crop_keyframes=crop_keyframes,
    )
    encoder = detect_gpu_encoder()
    enc_args = _encoder_args(encoder, upscale_4k)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *seek_args,
        "-i", str(input_path),
        *(["-t", str(duration)] if seek_args else []),
        "-vf", vf,
        *enc_args,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(output_path),
    ]

    LOG.info(
        "TikTok 9:16 → %s (%dx%d, %.1fs) | encoder=%s | vf=%s",
        Path(input_path).name, src_w, src_h, duration,
        encoder or "libx264", vf,
    )

    ok, err = _run_ffmpeg_with_progress(cmd, duration, progress_cb)
    if ok:
        LOG.info("TikTok 9:16 completado → %s", output_path)
        return True, str(output_path)
    return False, err


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convierte un video local a vertical 9:16 (TikTok) con mejoras."
    )
    parser.add_argument("input", help="Video de entrada")
    parser.add_argument("output", nargs="?", help="Video de salida (opcional)")
    parser.add_argument("--no-4k", action="store_true", help="Salida 1080x1920 en vez de 4K")
    args = parser.parse_args()

    out = args.output or str(Path(args.input).with_stem(Path(args.input).stem + "_TikTok"))

    def _cli_progress(frac: float, msg: str) -> None:
        print(f"\r  {frac * 100:5.1f}%  {msg}", end="", flush=True)

    ok, result = process_to_tiktok(
        args.input, out, upscale_4k=not args.no_4k, progress_cb=_cli_progress,
    )
    print()
    print(f"✅ Guardado: {result}" if ok else f"❌ Error: {result}")
