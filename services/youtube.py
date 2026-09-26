"""
YouTube audio extraction feature.
To remove: delete this file and remove YOUTUBE FEATURE sections from bot.py.
"""
import re
import os
import glob
import logging
from typing import Optional, Tuple

import yt_dlp

logger = logging.getLogger(__name__)

# YouTube URL patterns
YT_URL_RE = re.compile(
    r'(?:https?://)?(?:www\.|m\.)?'
    r'(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)'
    r'[\w\-]+',
    re.IGNORECASE,
)


def is_youtube_url(text: str) -> bool:
    """Check if text contains a YouTube URL."""
    return bool(YT_URL_RE.search(text))


def extract_youtube_url(text: str) -> Optional[str]:
    """Extract the first YouTube URL from text."""
    m = YT_URL_RE.search(text)
    return m.group(0) if m else None


def get_video_info(url: str, proxy: str) -> Optional[dict]:
    """Fetch YouTube video metadata (no download)."""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'ignoreerrors': True,
        'proxy': proxy,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        logger.error(f"YouTube info failed for {url}: {e}")
        return None


def download_youtube_audio(url: str, mp3_path: str, proxy: str) -> Tuple[bool, str]:
    """Download YouTube audio to mp3. Returns (success, error_message)."""
    output_dir = os.path.dirname(mp3_path) or "."
    base = os.path.splitext(os.path.basename(mp3_path))[0]

    opts = {
        'format': 'bestaudio/best',
        'proxy': proxy,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_dir, f"{base}.%(ext)s"),
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'concurrent_fragment_downloads': 8,
        'socket_timeout': 30,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        if os.path.exists(mp3_path):
            size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
            if size_mb > 50:
                return False, f"📦 فایل {size_mb:.1f} MB بزرگ‌تر از حد مجاز (۵۰ MB)"
            return True, ""

        pattern = os.path.join(output_dir, f"{base}*.mp3")
        files = sorted(glob.glob(pattern))
        if files:
            if files[0] != mp3_path:
                os.replace(files[0], mp3_path)
            return True, ""

        return False, "❌ فایل صوتی پیدا نشد."
    except Exception as e:
        logger.error(f"YouTube download failed: {e}")
        return False, f"❌ خطا: {str(e)[:100]}"
