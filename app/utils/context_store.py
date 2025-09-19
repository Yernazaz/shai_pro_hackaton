from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Tuple

from app.config.settings import get_settings
from app.utils.logging_config import get_logger
from app.utils.redis_client import redis_client

logger = get_logger(__name__)

_settings = get_settings()


class PendingContextStore:
    def __init__(self) -> None:
        self.enabled = _settings.enable_context_memory
        self.ttl = _settings.context_ttl_seconds
        self._fallback: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._pending_users: set[str] = set()

    def _redis_key(self, session_id: str) -> str:
        return f"nqlcrm:pending:{session_id}"

    def save(self, session_id: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        if not payload or not payload.get("next_query_hint"):
            return
        serialized = json.dumps(payload, ensure_ascii=False)
        if redis_client.available:
            ok = redis_client.set(self._redis_key(session_id), serialized, ex=self.ttl)
            if ok:
                self._pending_users.add(session_id)
                return
        expiry = time.time() + self.ttl
        self._fallback[session_id] = (expiry, payload)
        self._pending_users.add(session_id)

    def clear(self, session_id: str) -> None:
        if not self.enabled:
            return
        if redis_client.available:
            redis_client.delete(self._redis_key(session_id))
        self._fallback.pop(session_id, None)
        self._pending_users.discard(session_id)

    def load(self, session_id: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        if not self.enabled:
            return None, False
        if redis_client.available:
            raw = redis_client.get(self._redis_key(session_id))
            if raw is not None:
                self._pending_users.add(session_id)
                try:
                    return json.loads(raw), False
                except Exception:
                    logger.exception("[ContextStore] Failed to decode redis payload")
                    return None, False
            else:
                expired = session_id in self._pending_users
                self._pending_users.discard(session_id)
                return None, expired
        entry = self._fallback.get(session_id)
        if not entry:
            expired = session_id in self._pending_users
            self._pending_users.discard(session_id)
            return None, expired
        expiry, payload = entry
        if expiry < time.time():
            self._fallback.pop(session_id, None)
            expired = session_id in self._pending_users
            self._pending_users.discard(session_id)
            return None, expired
        self._pending_users.add(session_id)
        return payload, False


context_store = PendingContextStore()


__all__ = ["context_store"]
