"""
Simple SQLite-based download history and stats.
"""
import logging
import sqlite3
import os
from datetime import datetime, timedelta, timezone, timezone
from typing import List, Dict, Any, Optional

from config import DOWNLOAD_HISTORY_DB

logger = logging.getLogger(__name__)

# Thread-safe: use a lock for writes
import threading
_db_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """Open a connection to the history DB."""
    os.makedirs(os.path.dirname(DOWNLOAD_HISTORY_DB), exist_ok=True)
    conn = sqlite3.connect(DOWNLOAD_HISTORY_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if not exist."""
    with _db_lock:
        conn = _get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    track_id TEXT,
                    title TEXT,
                    artist TEXT,
                    url TEXT,
                    duration_ms INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_created
                    ON downloads(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_artist
                    ON downloads(artist);
            """)
            conn.commit()
            logger.info("History DB initialized")
        except Exception:
            logger.exception("Failed to init history DB")
        finally:
            conn.close()


def add_download(
    user_id: int,
    track_id: Optional[str],
    title: str,
    artist: str,
    url: str,
    duration_ms: int,
):
    """Record a successful download."""
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT INTO downloads
                   (user_id, track_id, title, artist, url, duration_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    str(track_id) if track_id is not None else None,
                    title,
                    artist,
                    url,
                    int(duration_ms or 0),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to add download history")
        finally:
            conn.close()


def get_user_history(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Return last N downloads for a user."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM downloads
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_stats(user_id: int) -> Dict[str, Any]:
    """Return stats for a user."""
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        total = conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]

        today_count = conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE user_id = ? AND created_at >= ?",
            (user_id, today.isoformat()),
        ).fetchone()[0]

        week_count = conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE user_id = ? AND created_at >= ?",
            (user_id, week_ago.isoformat()),
        ).fetchone()[0]

        month_count = conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE user_id = ? AND created_at >= ?",
            (user_id, month_ago.isoformat()),
        ).fetchone()[0]

        top_artists = conn.execute(
            """SELECT artist, COUNT(*) as cnt
               FROM downloads
               WHERE user_id = ?
               GROUP BY artist
               ORDER BY cnt DESC
               LIMIT 5""",
            (user_id,),
        ).fetchall()

        return {
            "total": total,
            "today": today_count,
            "week": week_count,
            "month": month_count,
            "top_artists": [dict(r) for r in top_artists],
        }
    finally:
        conn.close()


def get_global_top(limit: int = 10) -> List[Dict[str, Any]]:
    """Return globally most downloaded tracks."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT title, artist, url, COUNT(*) as cnt
               FROM downloads
               GROUP BY title, artist
               ORDER BY cnt DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# Auto-init on import
init_db()
