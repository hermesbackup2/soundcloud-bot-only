import time
from typing import Dict, Optional

# Global session storage — bot.py accesses this dict directly
user_sessions: Dict[int, dict] = {}
_timestamps: Dict[int, float] = {}
_TTL = 1800  # 30 minutes


def touch_session(user_id: int):
    """Update the timestamp for a user session."""
    _timestamps[user_id] = time.time()


def cleanup_old_sessions():
    """Remove all expired sessions."""
    current_time = time.time()
    expired = [
        uid for uid, ts in _timestamps.items()
        if current_time - ts > _TTL
    ]
    for uid in expired:
        user_sessions.pop(uid, None)
        _timestamps.pop(uid, None)


class SessionManager:
    def __init__(self, ttl=1800):
        self._sessions: Dict[int, dict] = {}
        self._timestamps: Dict[int, float] = {}
        self.ttl = ttl

    def create_or_update(self, user_id: int, data: dict):
        self._sessions[user_id] = data
        self._timestamps[user_id] = time.time()
        self._cleanup_expired()

    def get(self, user_id: int) -> Optional[dict]:
        if user_id not in self._sessions:
            return None
        if time.time() - self._timestamps.get(user_id, 0) > self.ttl:
            self.delete(user_id)
            return None
        return self._sessions.get(user_id)

    def delete(self, user_id: int):
        self._sessions.pop(user_id, None)
        self._timestamps.pop(user_id, None)

    def _cleanup_expired(self):
        current_time = time.time()
        expired = [
            uid for uid, ts in self._timestamps.items()
            if current_time - ts > self.ttl
        ]
        for uid in expired:
            self.delete(uid)

    def get_all_active(self):
        self._cleanup_expired()
        return list(self._sessions.keys())
