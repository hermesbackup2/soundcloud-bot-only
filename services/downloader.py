import logging
import os
import glob
import yt_dlp

from config import PROXY_URL, MAX_FILE_SIZE_MB

logger = logging.getLogger(__name__)



def classify_error(exc: Exception) -> str:
    """Convert yt-dlp exceptions into user-friendly messages."""
    msg = str(exc).lower()
    if "drm" in msg or "protected" in msg:
        return "🔐 DRM protected"
    if "private" in msg or "unavailable" in msg:
        return "🔒 این ترک private یا حذف شده است."
    if "geo" in msg or "country" in msg or "region" in msg:
        return "🌍 این ترک در منطقه سرور قابل دسترس نیست."
    if "copyright" in msg or "removed" in msg:
        return "⚖️ این ترک به دلیل کپی‌رایت حذف شده است."
    if "timeout" in msg or "timed out" in msg:
        return "⏱️ timeout در اتصال. لطفاً دوباره تلاش کنید."
    if "connection" in msg or "network" in msg or "reset" in msg:
        return "🌐 خطای شبکه. لطفاً دوباره تلاش کنید."
    if "404" in msg or "not found" in msg:
        return "❓ ترک پیدا نشد."
    if "too large" in msg or "entity too large" in msg:
        return "📦 فایل بزرگ‌تر از حد مجاز تلگرام (۵۰ MB) است."
    if "permission" in msg or "forbidden" in msg:
        return "⛔ دسترسی به این ترک مجاز نیست."
    if "429" in msg or "rate limit" in msg:
        return "🐢 محدودیت نرخ SoundCloud. چند دقیقه بعد تلاش کنید."
    # Default
    return f"❌ خطا: {str(exc)[:120]}"


def download_track_audio(track_data: dict, mp3_path: str) -> tuple:
    """Returns (success: bool, error_message: str)."""
    """Download a SoundCloud track to mp3_path. Returns True on success."""
    url = track_data.get('url')
    if not url:
        logger.error("No URL in track_data")
        return False, "❌ لینک ترک نامعتبر است."

    output_dir = os.path.dirname(mp3_path) or "."
    base = os.path.splitext(os.path.basename(mp3_path))[0]

    ydl_opts = {
        'format': 'bestaudio/best',
        'proxy': PROXY_URL,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_dir, f"{base}.%(ext)s"),
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'concurrent_fragment_downloads': 16,
        'http_chunk_size': 10485760,
        'retries': 5,
        'fragment_retries': 5,
        'socket_timeout': 30,
        'nocheckcertificate': True,
        'postprocessor_args': {
            'extractaudio': ['-map_metadata', '-1'],
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(mp3_path):
            size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                logger.error(f"File too large for Telegram: {size_mb:.1f} MB")
                return False, f"📦 فایل {size_mb:.1f} MB بزرگ‌تر از حد مجاز (۵۰ MB) است."
            return True, ""

        pattern = os.path.join(output_dir, f"{base}*.mp3")
        files = sorted(glob.glob(pattern))
        if files:
            if files[0] != mp3_path:
                os.replace(files[0], mp3_path)
            return True, ""

        logger.error("Download completed but output file not found")
        return False, "❌ فایل دانلود شده پیدا نشد."

    except Exception as e:
        logger.error(f"Download failed: {e}")
        return False, classify_error(e)
