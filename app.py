"""
╔══════════════════════════════════════════════════════════╗
║         DIRPY LOCAL  —  YouTube Downloader Studio         ║
║         Streamlit + yt-dlp + FFmpeg                       ║
╚══════════════════════════════════════════════════════════╝

Dependencias:
    pip install streamlit yt-dlp

Requisito del sistema:
    FFmpeg instalado y disponible en el PATH del sistema.

Ejecutar con:
    streamlit run app.py
"""

import shutil
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
import yt_dlp

from utils import (
    LOG,
    check_ffmpeg,
    detect_gpu_encoder,
    extract_video_id,
    get_downloads_folder,
    is_valid_youtube_url,
    sanitize_filename,
    seconds_to_hms,
)
from downloader import build_ydl_opts, fetch_video_info, storyboard_frame_at
from processor import process_to_tiktok, trim_media

# ─────────────────────────────────────────────
#  CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Dirpy Local Studio",
    page_icon="✂️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
#  ESTILOS — rediseño moderno
# ─────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Inter:wght@300;400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp {
        background:
            radial-gradient(ellipse 80% 50% at 50% -10%, rgba(0, 230, 138, 0.08), transparent),
            #0a0e13;
        color: #e6edf3;
    }

    [data-testid="stSidebar"] {
        background: #0d1117;
        border-right: 1px solid #1f2937;
    }

    [data-testid="stSidebar"] .stMarkdown h2 {
        font-size: 1.05rem !important;
    }

    h1, h2, h3 {
        font-family: 'Space Grotesk', sans-serif !important;
        color: #e6edf3 !important;
        letter-spacing: -0.5px;
    }

    h1 { font-size: 2.1rem !important; }

    .hero-badge {
        display: inline-block;
        background: rgba(0, 230, 138, 0.12);
        color: #00e68a;
        border: 1px solid rgba(0, 230, 138, 0.35);
        border-radius: 999px;
        padding: 3px 14px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        margin-bottom: 8px;
    }

    .card {
        background: #12181f;
        border: 1px solid #1f2937;
        border-radius: 14px;
        padding: 18px 22px;
        margin: 10px 0;
    }

    .card-accent { border-left: 3px solid #00e68a; }

    .meta-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.1rem;
        font-weight: 600;
        color: #ffffff;
        margin-bottom: 8px;
        line-height: 1.35;
    }

    .badge {
        display: inline-block;
        background: rgba(0, 230, 138, 0.08);
        color: #00e68a;
        border: 1px solid rgba(0, 230, 138, 0.30);
        border-radius: 999px;
        padding: 3px 12px;
        font-size: 0.76rem;
        font-weight: 500;
        margin: 3px 6px 3px 0;
    }

    .badge-red {
        background: rgba(255, 68, 68, 0.10);
        color: #ff6b6b;
        border-color: rgba(255, 68, 68, 0.40);
    }

    .badge-neutral {
        background: rgba(139, 148, 158, 0.10);
        color: #8b949e;
        border-color: #2d3742;
    }

    .log-console {
        background: #0a0e13;
        border: 1px solid #1f2937;
        border-radius: 10px;
        padding: 12px 16px;
        font-family: 'Space Grotesk', monospace;
        font-size: 0.72rem;
        color: #00cc7a;
        max-height: 200px;
        overflow-y: auto;
        line-height: 1.7;
        white-space: pre-wrap;
        word-break: break-all;
    }

    hr { border-color: #1f2937 !important; }

    .stDownloadButton > button, .stButton > button {
        background: linear-gradient(135deg, #00e68a, #00b86e) !important;
        color: #06110c !important;
        font-family: 'Space Grotesk', sans-serif !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.65rem 1.8rem !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.4px !important;
        transition: all 0.18s !important;
        box-shadow: 0 4px 18px rgba(0, 230, 138, 0.22) !important;
    }

    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 24px rgba(0, 230, 138, 0.35) !important;
    }

    .stTextInput > div > div > input,
    .stNumberInput > div > div > input {
        background: #12181f !important;
        border: 1px solid #2d3742 !important;
        color: #e6edf3 !important;
        border-radius: 10px !important;
    }

    .stTextInput > div > div > input:focus {
        border-color: #00e68a !important;
        box-shadow: 0 0 0 1px #00e68a !important;
    }

    .stProgress > div > div { background: #00e68a !important; }

    .stSlider [data-baseweb="slider"] [role="slider"] {
        background: #00e68a !important;
        border-color: #00e68a !important;
    }

    .stAlert { border-radius: 10px !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
#  CACHÉ DE METADATOS
# ─────────────────────────────────────────────

# Componente propio: reproductor de YouTube con recuadro 9:16 arrastrable
# sobre el video en reproducción (ver frame_selector/index.html)
_frame_selector = components.declare_component(
    "frame_selector",
    path=str(Path(__file__).parent / "frame_selector"),
)


@st.cache_data(show_spinner=False)
def fetch_info_cached(url: str) -> dict | None:
    return fetch_video_info(url)


@st.cache_data(show_spinner=False, ttl=3600, max_entries=300)
def get_preview_frame(url: str, t: int):
    """
    Fotograma del video en el segundo t (imagen PIL), obtenido del
    storyboard de YouTube sin descargar el video. None si no hay.
    """
    try:
        info = fetch_info_cached(url)
    except Exception:
        return None
    sb = (info or {}).get("storyboard")
    if not sb:
        return None
    try:
        return storyboard_frame_at(sb, t)
    except Exception as e:
        LOG.warning("No se pudo obtener fotograma del storyboard: %s", e)
        return None


# ─────────────────────────────────────────────
#  PROGRESS HOOK CON LOGGING DUAL
# ─────────────────────────────────────────────

def make_progress_hook(progress_bar, ui_status_placeholder, ui_log_lines: list):
    """
    Hook de progreso que actualiza a la vez la barra de Streamlit,
    el mini-terminal de la UI y el logger de consola.
    """

    def hook(d: dict) -> None:
        status = d.get("status", "")

        if status == "downloading":
            pct_str = (
                d.get("_percent_str", "0%").strip().replace("%", "")
                .replace("\x1b[0;94m", "").replace("\x1b[0m", "")
            )
            speed_str = d.get("_speed_str", "–").strip()
            eta_str = d.get("_eta_str", "–").strip()
            downloaded = d.get("_downloaded_bytes_str", "–").strip()
            total = d.get("_total_bytes_str") or d.get("_total_bytes_estimate_str", "–")
            if total:
                total = str(total).strip()
            filename = Path(d.get("filename", "")).name

            try:
                pct = float(pct_str) / 100
            except (ValueError, TypeError):
                pct = 0.0

            LOG.debug(
                "DESCARGANDO → %s%% | velocidad=%s | eta=%s | descargado=%s/%s | archivo=%s",
                pct_str, speed_str, eta_str, downloaded, total, filename,
            )
            progress_bar.progress(
                min(pct, 1.0),
                text=f"⬇️ {pct_str}% · {speed_str} · ETA {eta_str}",
            )
            _update_ui_log(
                ui_log_lines,
                f"[DL] {pct_str}% | {speed_str} | ETA {eta_str} | {downloaded}/{total}",
                ui_status_placeholder,
            )

        elif status == "finished":
            filename = Path(d.get("filename", "archivo")).name
            LOG.info("Descarga completada → procesando con FFmpeg: %s", filename)
            progress_bar.progress(1.0, text="🔧 Procesando con FFmpeg...")
            _update_ui_log(
                ui_log_lines,
                f"[OK] Descarga completada → FFmpeg procesando: {filename}",
                ui_status_placeholder,
            )

        elif status == "error":
            LOG.error("Error en hook de progreso: %s", d)
            _update_ui_log(
                ui_log_lines,
                f"[ERR] Error durante descarga: {d.get('error', 'desconocido')}",
                ui_status_placeholder,
            )

    return hook


def _update_ui_log(log_lines: list, new_line: str, placeholder) -> None:
    """Mini-terminal en la UI: ventana deslizante de 10 líneas."""
    log_lines.append(new_line)
    if len(log_lines) > 10:
        log_lines.pop(0)
    placeholder.markdown(
        f'<div class="log-console">{chr(10).join(log_lines)}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
#  SIDEBAR — AJUSTES
# ─────────────────────────────────────────────

QUALITY_MAP = {
    "Máxima disponible": None,
    "2160p (4K)": 2160,
    "1440p (2K)": 1440,
    "1080p (Full HD)": 1080,
    "720p (HD)": 720,
    "480p": 480,
}


def render_sidebar() -> dict:
    with st.sidebar:
        st.markdown("## ⚙️ Ajustes")

        fmt = st.radio("🎚️ Formato", ["Video (MP4)", "Audio (MP3)"])

        if fmt == "Video (MP4)":
            quality_label = st.selectbox(
                "📺 Calidad máxima", list(QUALITY_MAP.keys()), index=0,
            )
            max_height = QUALITY_MAP[quality_label]
            audio_bitrate = "320"
        else:
            max_height = None
            audio_bitrate = st.selectbox(
                "🎧 Bitrate MP3", ["320", "192", "128"], index=0,
                format_func=lambda b: f"{b} kbps",
            )

        st.markdown("---")

        tiktok_mode = False
        tk_opts = {}
        if fmt == "Video (MP4)":
            tiktok_mode = st.toggle(
                "📱 Modo TikTok 9:16",
                help="Convierte el fragmento a formato vertical con mejoras de imagen.",
            )
            if tiktok_mode:
                tk_opts["upscale_4k"] = st.checkbox("⬆️ Escalar a 4K (2160×3840)", value=True)
                tk_opts["denoise"] = st.checkbox("🧹 Reducción de ruido digital", value=True)
                tk_opts["sharpen"] = st.checkbox("👤 Realce de detalle (rostros)", value=True)
                tk_opts["vibrant"] = st.checkbox("🎨 Colores vibrantes", value=True)
                st.caption(
                    "Podrás elegir el encuadre arrastrando un recuadro sobre "
                    "el video, en la sección 📐 Encuadre (abajo). Sin posiciones "
                    "fijadas, el recorte es centrado."
                )

                with st.spinner("Detectando GPU..."):
                    enc = detect_gpu_encoder()
                if enc:
                    st.success(f"🚀 GPU: `{enc}`", icon="✅")
                else:
                    st.info("🐢 Sin GPU → se usará CPU (libx264)")

        st.markdown("---")
        st.caption(f"📁 Destino: `{get_downloads_folder()}`")
        st.caption("Dirpy Local · yt-dlp + FFmpeg · Uso personal")

    return {
        "fmt": fmt,
        "max_height": max_height,
        "audio_bitrate": audio_bitrate,
        "tiktok_mode": tiktok_mode,
        "tk_opts": tk_opts,
    }


# ─────────────────────────────────────────────
#  INTERFAZ PRINCIPAL
# ─────────────────────────────────────────────

def main():
    LOG.info("=== Dirpy Local Studio iniciado ===")

    # ── Cabecera ──
    st.markdown(
        """
        <div class="hero-badge">100% local</div>
        <h1>✂️ Dirpy Local <span style="color:#00e68a;">Studio</span></h1>
        <p style="color:#8b949e; font-size:0.95rem; margin-top:-6px;">
            Descarga, recorta y convierte videos de YouTube — con modo vertical para TikTok
        </p>
        """,
        unsafe_allow_html=True,
    )

    # ── Verificar FFmpeg ──
    if not check_ffmpeg():
        LOG.error("FFmpeg no encontrado en PATH")
        st.error(
            "⚠️ **FFmpeg no encontrado.** Instálalo y asegúrate de que esté en el PATH.\n\n"
            "- **Windows**: https://ffmpeg.org/download.html\n"
            "- **macOS**: `brew install ffmpeg`\n"
            "- **Linux**: `sudo apt install ffmpeg`"
        )
        st.stop()

    settings = render_sidebar()
    fmt = settings["fmt"]

    # ── Input de URL ──
    url = st.text_input(
        "🔗 URL del video",
        placeholder="https://www.youtube.com/watch?v=...",
    )

    if "video_info" not in st.session_state:
        st.session_state.video_info = None
    if "last_url" not in st.session_state:
        st.session_state.last_url = ""

    if "fetch_error" not in st.session_state:
        st.session_state.fetch_error = ""

    if url and url != st.session_state.last_url:
        if not is_valid_youtube_url(url):
            LOG.warning("URL inválida: %s", url)
            st.warning("⚠️ La URL no parece ser un enlace válido de YouTube.")
            st.session_state.video_info = None
        else:
            with st.spinner("⏳ Obteniendo información del video..."):
                try:
                    st.session_state.video_info = fetch_info_cached(url)
                    st.session_state.fetch_error = ""
                except Exception as e:
                    st.session_state.video_info = None
                    st.session_state.fetch_error = str(e)
                st.session_state.last_url = url
                # Las posiciones de encuadre pertenecen al video anterior
                st.session_state.tk_keyframes = []

    if st.session_state.video_info is None and st.session_state.fetch_error:
        err = st.session_state.fetch_error
        if "Sign in to confirm" in err:
            st.error(
                "🤖 **YouTube está bloqueando esta red** (pide iniciar sesión para "
                "confirmar que no eres un bot). No es culpa del video ni de la app.\n\n"
                "**Soluciones:**\n"
                "1. Si estás usando VPN o cambiaste de red, vuelve a la red anterior.\n"
                "2. O exporta tus cookies de YouTube: instala la extensión "
                "*Get cookies.txt LOCALLY* en tu navegador (con sesión iniciada en "
                "YouTube), exporta las cookies de `youtube.com` y guarda el archivo "
                "como `cookies.txt` en la carpeta de la app "
                "(`Desktop\\App_Video`). La app lo usará automáticamente."
            )
        else:
            st.error(f"❌ No se pudo obtener información del video:\n\n`{err}`")

    info = st.session_state.video_info
    if not info:
        if not url:
            st.info("👆 Pega una URL de YouTube para comenzar.")
        return

    duration = info["duration"]
    stream_type = info.get("stream_type", "normal")

    # ── Metadatos ──
    upload_date = info.get("upload_date", "")
    if upload_date and len(upload_date) == 8:
        upload_date = f"{upload_date[6:8]}/{upload_date[4:6]}/{upload_date[:4]}"
    views = info.get("view_count", 0)
    views_fmt = f"{views:,}".replace(",", ".") if views else "–"

    stream_badge = ""
    if stream_type == "live_vod":
        stream_badge = '<span class="badge badge-red">🔴 VOD de directo</span>'
    elif stream_type == "live":
        stream_badge = '<span class="badge badge-red">🔴 En directo</span>'

    st.markdown(
        f"""
        <div class="card card-accent">
            <div class="meta-title">🎬 {info['title']}</div>
            <span class="badge">⏱ {seconds_to_hms(duration)}</span>
            <span class="badge badge-neutral">👤 {info['uploader']}</span>
            <span class="badge badge-neutral">👁 {views_fmt} vistas</span>
            <span class="badge badge-neutral">📅 {upload_date or '–'}</span>
            {stream_badge}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if stream_type in ("live_vod", "live"):
        st.info(
            "🔴 **VOD de transmisión en vivo detectado.** YouTube no permite "
            "descargar solo un rango de estos streams, así que se descargará el "
            "video completo y el recorte se hará localmente. En VODs largos la "
            "descarga puede tardar varios minutos (elige una calidad menor para "
            "acelerarla). La calidad máxima de un VOD reciente suele ser 720p."
        )

    if duration <= 0:
        st.warning(
            "⚠️ Este contenido no reporta duración (probablemente un directo activo). "
            "El recorte por rango no está disponible."
        )
        return

    # ── Recorte + vista previa ──
    col_preview, col_trim = st.columns([5, 4], gap="large")

    with col_trim:
        st.markdown("### ✂️ Recorte")
        st.caption("Solo se descarga el fragmento seleccionado (ahorra ancho de banda).")

        fine_mode = st.toggle("🎯 Ajuste fino (min/seg)")

        if fine_mode:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**⏩ Inicio**")
                start_min = st.number_input(
                    "Min (inicio)", min_value=0, max_value=duration // 60,
                    value=0, step=1, key="start_min",
                )
                start_sec = st.number_input(
                    "Seg (inicio)", min_value=0, max_value=59,
                    value=0, step=1, key="start_sec",
                )
                start_total = start_min * 60 + start_sec
            with c2:
                st.markdown("**⏭️ Fin**")
                end_min = st.number_input(
                    "Min (fin)", min_value=0, max_value=duration // 60,
                    value=duration // 60, step=1, key="end_min",
                )
                end_sec = st.number_input(
                    "Seg (fin)", min_value=0, max_value=59,
                    value=duration % 60, step=1, key="end_sec",
                )
                end_total = end_min * 60 + end_sec
        else:
            start_total, end_total = st.slider(
                "Fragmento (segundos)",
                min_value=0, max_value=duration,
                value=(0, duration), step=1,
                label_visibility="collapsed",
            )

        end_total = min(end_total, duration)
        if start_total >= end_total:
            st.error("⛔ El tiempo de inicio debe ser menor al tiempo de fin.")
            return

        fragment_seconds = end_total - start_total
        st.markdown(
            f"""
            <div class="card">
                <span class="badge">▶ {seconds_to_hms(start_total)}</span>
                <span class="badge">⏹ {seconds_to_hms(end_total)}</span>
                <span class="badge badge-neutral">📐 {seconds_to_hms(fragment_seconds)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        progress_pct = fragment_seconds / duration if duration > 0 else 0
        st.caption(f"Seleccionaste el {progress_pct * 100:.1f}% del video total")
        st.progress(progress_pct)

    with col_preview:
        st.markdown("### 👁️ Vista previa")
        try:
            st.video(url, start_time=start_total)
        except Exception:
            if info.get("thumbnail"):
                st.image(info["thumbnail"], width="stretch")
        st.caption("La vista previa arranca en el punto de inicio seleccionado.")

    # ── Encuadre vertical 9:16 (modo TikTok) ──
    if settings["tiktok_mode"] and fmt == "Video (MP4)":
        st.markdown("---")
        st.markdown("### 📐 Encuadre vertical 9:16")
        if "tk_keyframes" not in st.session_state:
            st.session_state.tk_keyframes = []

        video_id = extract_video_id(url)
        classic = st.toggle(
            "🖼️ Modo clásico (fotogramas)",
            value=False,
            help="Úsalo si el video no permite reproducirse embebido.",
        )

        if not classic and video_id:
            # ── Modo en vivo: arrastra el recuadro sobre el video en reproducción ──
            st.caption(
                "Reproduce el video, arrastra el recuadro sobre lo que te interesa "
                "y pulsa 📌 para fijar la posición en ese momento — o activa "
                "🔴 Grabar seguimiento y mueve el recuadro mientras corre: cada "
                "movimiento tuyo queda registrado en el instante en que lo haces "
                "(con compensación automática de tu tiempo de reacción). El "
                "encuadre final hace un paneo suave entre posiciones. Sin "
                "posiciones, recorte centrado."
            )
            kfs = _frame_selector(
                video_id=video_id,
                start=int(start_total),
                end=int(end_total),
                initial=st.session_state.tk_keyframes,
                key=f"fs_{video_id}",
                default=None,
            )
            if kfs is not None:
                st.session_state.tk_keyframes = [
                    {
                        "t": float(k["t"]),
                        "cx": float(k["cx"]),
                        "cy": float(k.get("cy", 0.5)),
                    }
                    for k in kfs
                ]
        else:
            # ── Modo clásico: fotogramas del storyboard + cropper ──
            st.caption(
                "Arrastra el recuadro sobre la parte de la imagen que te interesa y "
                "fija posiciones en distintos momentos del fragmento. El encuadre se "
                "mantiene en cada posición y hace un paneo suave hacia la siguiente. "
                "Si no fijas ninguna, el recorte es centrado."
            )

            col_frame, col_kfs = st.columns([3, 2], gap="large")

            with col_frame:
                if end_total - start_total > 1:
                    t_pos = st.slider(
                        "Momento dentro del fragmento",
                        min_value=start_total, max_value=end_total,
                        value=start_total, step=1, format="%d s",
                    )
                else:
                    t_pos = start_total

                frame = get_preview_frame(url, int(t_pos))
                if frame is None:
                    st.info(
                        "Este video no ofrece miniaturas de línea de tiempo; "
                        "se usará el encuadre centrado."
                    )
                else:
                    try:
                        from streamlit_cropper import st_cropper

                        box = st_cropper(
                            frame, aspect_ratio=(9, 16), return_type="box",
                            realtime_update=True, box_color="#00e68a",
                            key="tk_cropper",
                        )
                        cx = min(max((box["left"] + box["width"] / 2) / frame.width, 0.0), 1.0)
                        cy = min(max((box["top"] + box["height"] / 2) / frame.height, 0.0), 1.0)
                        st.caption(
                            f"🕐 {seconds_to_hms(int(t_pos))} · centro del recuadro "
                            f"al {cx * 100:.0f}% del ancho"
                        )
                        if st.button("➕ Fijar posición en este momento", use_container_width=True):
                            kfs = [
                                k for k in st.session_state.tk_keyframes
                                if k["t"] != int(t_pos)
                            ]
                            kfs.append({"t": int(t_pos), "cx": cx, "cy": cy})
                            st.session_state.tk_keyframes = sorted(kfs, key=lambda k: k["t"])
                            st.rerun()
                    except Exception as e:
                        LOG.warning("Cropper no disponible: %s", e)
                        st.warning(
                            "No se pudo cargar el recuadro arrastrable; "
                            "se usará el encuadre centrado."
                        )

            with col_kfs:
                st.markdown("**Posiciones fijadas**")
                if not st.session_state.tk_keyframes:
                    st.caption("Ninguna todavía → recorte centrado automático.")
                for i, k in enumerate(st.session_state.tk_keyframes):
                    c1, c2 = st.columns([4, 1])
                    c1.markdown(
                        f'<span class="badge">🕐 {seconds_to_hms(int(k["t"]))}</span> '
                        f'<span class="badge badge-neutral">↔ {k["cx"] * 100:.0f}% del ancho</span>',
                        unsafe_allow_html=True,
                    )
                    if c2.button("🗑", key=f"del_kf_{i}", help="Eliminar esta posición"):
                        st.session_state.tk_keyframes.pop(i)
                        st.rerun()

        # Posiciones → segundos relativos al inicio del clip (los tiempos
        # del filtro de FFmpeg empiezan en 0 por el -ss de input)
        kfs_rel = [
            (float(k["t"] - start_total), k["cx"], k["cy"])
            for k in st.session_state.tk_keyframes
            if start_total <= k["t"] <= end_total
        ]
        dropped = [
            k for k in st.session_state.tk_keyframes
            if not (start_total <= k["t"] <= end_total)
        ]
        if dropped:
            fuera = ", ".join(seconds_to_hms(int(k["t"])) for k in dropped)
            msg = (
                f"⚠️ {len(dropped)} posición(es) fijada(s) quedan FUERA del rango "
                f"recortado ({seconds_to_hms(start_total)}–{seconds_to_hms(end_total)}) "
                f"y no se aplicarán: {fuera}."
            )
            if not kfs_rel:
                msg += " No queda ninguna dentro del rango → el recorte será CENTRADO."
            st.warning(msg)
        settings["tk_opts"]["crop_keyframes"] = kfs_rel or None

    st.markdown("---")

    # ── Descarga ──
    label = "⬇️ DESCARGAR FRAGMENTO"
    if settings["tiktok_mode"]:
        label = "⬇️ DESCARGAR + CONVERTIR A TIKTOK 9:16"

    if st.button(label, use_container_width=True):
        run_download(url, info, settings, start_total, end_total)


def run_download(url, info, settings, start_total, end_total):
    """
    Flujo en dos fases:
      1. Descargar el video COMPLETO a una carpeta temporal con el
         downloader nativo de yt-dlp (YouTube rechaza la descarga por
         rangos vía FFmpeg, tanto en VODs normales como de directos).
      2. Recortar/convertir localmente con FFmpeg (preciso, con GPU).
    """
    fmt = settings["fmt"]
    stream_type = info.get("stream_type", "normal")
    downloads_folder = get_downloads_folder()

    ext = "mp3" if "Audio" in fmt else "mp4"
    safe_title = sanitize_filename(info["title"])[:80]
    # ':' no es válido en nombres de archivo en Windows (yt-dlp lo
    # sustituiría por '#' y la ruta esperada dejaría de coincidir)
    start_tag = seconds_to_hms(start_total).replace(":", ".")
    end_tag = seconds_to_hms(end_total).replace(":", ".")
    filename = f"{safe_title}_[{start_tag}-{end_tag}].{ext}"
    output_path = str(downloads_folder / filename)

    LOG.info(
        "Iniciando descarga → archivo=%s | stream_type=%s | fmt=%s | max_height=%s",
        filename, stream_type, fmt, settings["max_height"],
    )

    tmpdir = Path(tempfile.mkdtemp(prefix="dirpy_"))
    ydl_opts = build_ydl_opts(
        fmt=fmt,
        output_path=str(tmpdir / "source.%(ext)s"),
        stream_type=stream_type,
        max_height=settings["max_height"],
        audio_bitrate=settings["audio_bitrate"],
    )

    progress_bar = st.progress(0, text="Iniciando descarga...")
    st.markdown("**🖥️ Log de descarga** *(detalles técnicos completos en la terminal)*")
    ui_log_placeholder = st.empty()
    ui_log_lines: list[str] = []
    status_text = st.empty()

    ydl_opts["progress_hooks"] = [
        make_progress_hook(progress_bar, ui_log_placeholder, ui_log_lines)
    ]

    try:
        _update_ui_log(ui_log_lines, "[INIT] Conectando con YouTube...", ui_log_placeholder)
        progress_bar.progress(0.02, text="🔍 Resolviendo formatos disponibles...")

        if stream_type in ("live_vod", "live"):
            _update_ui_log(
                ui_log_lines,
                "[INFO] VOD de directo: se descarga completo (fragmentos en paralelo) y se recorta localmente",
                ui_log_placeholder,
            )

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            error_code = ydl.download([url])

        if error_code != 0:
            LOG.error("yt-dlp retornó código de error: %s", error_code)
            status_text.error(f"❌ yt-dlp retornó código de error: {error_code}")
            return

        progress_bar.progress(1.0, text="✅ Descarga completa")

        # ── Fase 2: recorte / conversión local ──
        source_file = next(tmpdir.glob("source.*"), None)
        if source_file is None:
            status_text.error("❌ No se encontró el archivo descargado.")
            return

        tk_direct = settings["tiktok_mode"] and ext == "mp4"
        if not tk_direct:
            st.markdown("**✂️ Recorte local del fragmento**")
            cut_bar = st.progress(0, text="Recortando con FFmpeg...")

            def cut_progress(frac: float, msg: str) -> None:
                cut_bar.progress(min(frac, 1.0), text=f"✂️ {msg}")

            ok, result = trim_media(
                str(source_file), output_path, start_total, end_total,
                to_mp3=(ext == "mp3"),
                audio_bitrate=settings["audio_bitrate"],
                progress_cb=cut_progress,
            )
            if not ok:
                cut_bar.empty()
                status_text.error(f"❌ Falló el recorte local: {result}")
                return
            cut_bar.progress(1.0, text="✅ Recorte completo")

        final_path = output_path
        _update_ui_log(ui_log_lines, f"[DONE] Fragmento listo: {filename}", ui_log_placeholder)

        # ── Modo TikTok 9:16 ──
        # El recorte se hace en la misma pasada que la conversión
        # (una sola re-codificación desde el archivo fuente completo)
        if tk_direct:
            st.markdown("**📱 Conversión a TikTok 9:16**")
            tk_bar = st.progress(0, text="Preparando conversión vertical...")
            tk_out = output_path.replace(".mp4", "_TikTok_9x16.mp4")

            def tk_progress(frac: float, msg: str) -> None:
                tk_bar.progress(min(frac, 1.0), text=f"📱 {msg}")

            _update_ui_log(
                ui_log_lines,
                "[TIKTOK] Recorte 9:16 + mejoras de imagen (esto puede tardar)...",
                ui_log_placeholder,
            )
            ok, result = process_to_tiktok(
                str(source_file), tk_out,
                progress_cb=tk_progress,
                start_sec=start_total, end_sec=end_total,
                **settings["tk_opts"],
            )
            if ok:
                tk_bar.progress(1.0, text="✅ Conversión completa")
                _update_ui_log(
                    ui_log_lines,
                    f"[TIKTOK] Guardado: {Path(tk_out).name}",
                    ui_log_placeholder,
                )
                final_path = tk_out
            else:
                tk_bar.empty()
                st.error(f"❌ Falló la conversión a TikTok: {result}")
                return

        status_text.success(f"✅ **Archivo guardado en:**\n`{final_path}`")
        st.balloons()

    except yt_dlp.utils.DownloadError as e:
        LOG.error("DownloadError: %s", e, exc_info=True)
        progress_bar.empty()
        _update_ui_log(ui_log_lines, f"[ERR] DownloadError: {e}", ui_log_placeholder)
        st.error(f"❌ Error de descarga: {e}")

    except Exception as e:
        LOG.error("Error inesperado: %s", e, exc_info=True)
        progress_bar.empty()
        _update_ui_log(ui_log_lines, f"[ERR] Error inesperado: {e}", ui_log_placeholder)
        st.error(f"❌ Error inesperado: {e}")

    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
