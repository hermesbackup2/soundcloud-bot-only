import os
import re
import json
import logging
import requests
import yt_dlp
from typing import Optional, Tuple, List, Dict, Any

from config import PROXY_URL

logger = logging.getLogger(__name__)

SC_URL_RE = re.compile(r'https?://(?:www\.|on\.)?soundcloud\.com/[^\s]+', re.IGNORECASE)
PROXIES = {"http": PROXY_URL, "https": PROXY_URL}

YDL_BASE_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'ignoreerrors': True,
    'proxy': PROXY_URL,
}

from config import ARTIST_CACHE_FILE

# Cache for artist lookups (persisted to disk)
_artist_cache: Dict[str, str] = {}


def _load_artist_cache():
    """Load artist cache from disk."""
    global _artist_cache
    try:
        if os.path.exists(ARTIST_CACHE_FILE):
            with open(ARTIST_CACHE_FILE, "r", encoding="utf-8") as f:
                _artist_cache = json.load(f)
            logger.info(f"Loaded {len(_artist_cache)} cached artists")
    except Exception as e:
        logger.warning(f"Failed to load artist cache: {e}")
        _artist_cache = {}


def _save_artist_cache():
    """Save artist cache to disk."""
    try:
        with open(ARTIST_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_artist_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save artist cache: {e}")


# Load cache on module import
_load_artist_cache()


def is_sc_url(text: str) -> bool:
    return bool(SC_URL_RE.search(text))


def _resolve_short_url(url: str) -> str:
    try:
        r = requests.head(
            url,
            allow_redirects=True,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
            proxies=PROXIES,
        )
        return r.url
    except Exception:
        return url


def _get_real_artist(track_url: str, fallback: str = 'SoundCloud') -> str:
    """Fetch real artist name from SoundCloud page HTML."""
    if not track_url:
        return fallback
    
    # Check cache first
    if track_url in _artist_cache:
        return _artist_cache[track_url]
    
    try:
        r = requests.get(
            track_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
            proxies=PROXIES,
        )
        # Search for artist field in SoundCloud hydration data
        for pattern in [
            r'"artist"\s*:\s*"([^"]+)"',
            r'"creator"\s*:\s*"([^"]+)"',
        ]:
            match = re.search(pattern, r.text)
            if match:
                candidate = match.group(1).strip()
                if candidate and candidate.lower() != 'null':
                    _artist_cache[track_url] = candidate
                    _save_artist_cache()
                    return candidate
    except Exception as e:
        logger.debug(f"Failed to fetch artist from {track_url}: {e}")
    
    _artist_cache[track_url] = fallback
    _save_artist_cache()
    return fallback


def _extract_artist_from_title(title: str) -> str:
    """Extract artist from title as fallback."""
    match = re.match(
        r"^(.+?)\s*-\s*([A-Za-z][A-Za-z0-9\.\s&\']+?)(?:\s+[\u0600-\u06FF]|\s*\(|\s*$)",
        title.strip()
    )
    if match:
        candidate = match.group(2).strip()
        if 2 <= len(candidate) <= 50:
            return candidate
    return ""


def _extract_info(url: str) -> Optional[Dict[Any, Any]]:
    try:
        with yt_dlp.YoutubeDL(dict(YDL_BASE_OPTS)) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        logger.error(f"yt-dlp extraction failed for {url}: {e}")
        return None


def _normalize_track(entry: Any) -> Optional[Dict[str, Any]]:
    """Convert any yt-dlp SoundCloud entry into a consistent format."""
    if not entry or not isinstance(entry, dict):
        return None

    # Title - remove file extension
    title = entry.get('title') or entry.get('track') or 'Unknown'
    if not isinstance(title, str):
        title = str(title)
    title = title.strip()
    title = re.sub(r'\.(mp3|m4a|wav|flac|ogg|aac)$', '', title, flags=re.IGNORECASE)
    title = title.strip() or 'Unknown'

    # URL
    url = entry.get('webpage_url') or entry.get('url')

    # Fallback uploader
    uploader = (
        entry.get('uploader')
        or entry.get('channel')
        or ''
    )
    if not uploader:
        user = entry.get('user')
        if isinstance(user, dict):
            uploader = user.get('username', '')
        elif isinstance(user, str):
            uploader = user
    uploader = str(uploader).strip() or 'SoundCloud'

    # Try multiple methods for artist name (in order of accuracy)
    artist = ""
    
    # 1. From SoundCloud page HTML (most accurate)
    if url:
        real_artist = _get_real_artist(url, fallback="")
        if real_artist and real_artist != 'SoundCloud':
            artist = real_artist
    
    # 2. From title parsing
    if not artist:
        artist = _extract_artist_from_title(title)
    
    # 3. Fallback to uploader
    if not artist:
        artist = uploader

    # Artwork
    artwork = entry.get('thumbnail') or entry.get('artwork_url')
    if not artwork:
        user = entry.get('user')
        if isinstance(user, dict):
            artwork = user.get('avatar_url') or user.get('avatar')

    # Duration
    duration_s = entry.get('duration') or 0
    try:
        duration_ms = int(float(duration_s) * 1000)
    except (ValueError, TypeError):
        duration_ms = 0

    return {
        'id': entry.get('id'),
        'title': title,
        'duration': duration_ms,
        'url': url,
        'user': {'username': artist},
        'artwork_url': artwork,
    }


def resolve_soundcloud_url(url: str) -> Optional[Dict[str, Any]]:
    url = _resolve_short_url(url)
    info = _extract_info(url)
    if not info:
        return None

    if info.get('_type') == 'playlist' and info.get('entries'):
        entry = info['entries'][0] if info['entries'] else None
        if entry:
            normalized = _normalize_track(entry)
            if normalized:
                normalized['url'] = info.get('webpage_url') or url or normalized.get('url')
                return normalized

    return _normalize_track(info)


def get_playlist_tracks_fast(url: str, max_items: int = 20) -> Tuple[str, List[Dict[str, Any]], bool]:
    """Fast playlist extraction - only first N items."""
    url = _resolve_short_url(url)
    opts = dict(YDL_BASE_OPTS)
    opts['playlistend'] = max_items + 1
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logger.error(f"Fast playlist extraction failed: {e}")
        return "", [], False
    if not info:
        return "", [], False
    if info.get('_type') != 'playlist':
        normalized = _normalize_track(info)
        return info.get('title') or 'Unknown', ([normalized] if normalized else []), False
    title = info.get('title') or 'Unknown Playlist'
    entries = info.get('entries', []) or []
    has_more = len(entries) > max_items
    entries = entries[:max_items]
    tracks = []
    for entry in entries:
        t = _normalize_track(entry)
        if t:
            tracks.append(t)
    return title, tracks, has_more


def get_playlist_tracks(url: str) -> Tuple[str, List[Dict[str, Any]]]:
    url = _resolve_short_url(url)
    info = _extract_info(url)
    if not info:
        return "", []

    if info.get('_type') != 'playlist':
        normalized = _normalize_track(info)
        return info.get('title') or 'Unknown', ([normalized] if normalized else [])

    title = info.get('title') or 'Unknown Playlist'
    tracks = []
    for entry in info.get('entries', []):
        t = _normalize_track(entry)
        if t:
            tracks.append(t)
    return title, tracks


def search_tracks(query: str, offset: int, limit: int) -> Tuple[List[Dict[str, Any]], bool]:
    """Search with fallback to first word if full query fails. Skips DJ mixes."""
    queries = [query]
    
    words = query.split()
    if len(words) > 1:
        queries.append(words[0])
    
    seen = set()
    tracks = []
    
    for q in queries:
        search_url = f"scsearch{limit}:{q}"
        info = _extract_info(search_url)
        if not info:
            continue
        for entry in info.get('entries', []):
            t = _normalize_track(entry)
            if not t or t.get('id') in seen:
                continue
            
            # حذف نتایجی که توی title یا artist شون "dj" دارن
            title = (t.get('title') or '').lower()
            artist = (t.get('user') or {}).get('username', '').lower()
            
            if 'dj ' in title or 'dj ' in artist or 'dj-' in title or 'dj-' in artist:
                continue
            if title.startswith('dj') or artist.startswith('dj'):
                continue
            
            seen.add(t.get('id'))
            tracks.append(t)
        
        if tracks:
            break
    
    return tracks[:limit], len(tracks) >= limit

def get_track_info(track_id: Any) -> Optional[Dict[str, Any]]:
    """Deprecated — kept for backward compatibility."""
    return None


def extract_track_info(url: str) -> Dict[str, Any]:
    if not url or not isinstance(url, str):
        raise ValueError("Invalid URL provided.")
    if not is_sc_url(url):
        raise ValueError("URL does not appear to be a valid SoundCloud link.")
    info = _extract_info(url)
    if info is None:
        raise ValueError("Could not extract track info (URL might be private or deleted).")
    track_url = info.get('url')
    if not track_url:
        raise ValueError("Track is not downloadable (possibly requires authentication or DRM).")
    return {
        'title': info.get('title', 'Unknown Title'),
        'uploader': info.get('uploader', 'Unknown Artist'),
        'duration': info.get('duration', 0),
        'url': track_url,
        'thumbnail': info.get('thumbnail'),
    }
