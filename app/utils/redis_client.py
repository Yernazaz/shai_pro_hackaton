from __future__ import annotations

import socket
from typing import Any, Optional

from app.config.settings import get_settings
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class RedisClient:
    """Minimal RESP client for a small subset of Redis commands."""

    def __init__(self, host: str, port: int, db: int = 0, timeout: float = 1.0) -> None:
        self.host = host
        self.port = port
        self.db = db
        self.timeout = timeout
        self._available = None

    def _connect(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        return sock

    def _send_command(self, *parts: Any) -> Any:
        try:
            with self._connect() as sock:
                payload = self._encode(parts)
                sock.sendall(payload)
                return self._parse_response(sock)
        except Exception as exc:
            logger.debug("[RedisClient] command failed: %s", exc)
            self._available = False
            raise

    @staticmethod
    def _encode(parts: Any) -> bytes:
        encoded = bytearray()
        encoded.extend(f"*{len(parts)}\r\n".encode("utf-8"))
        for part in parts:
            if isinstance(part, bytes):
                data = part
            else:
                data = str(part).encode("utf-8")
            encoded.extend(f"${len(data)}\r\n".encode("utf-8"))
            encoded.extend(data)
            encoded.extend(b"\r\n")
        return bytes(encoded)

    @staticmethod
    def _readline(sock: socket.socket) -> bytes:
        chunks = []
        while True:
            chunk = sock.recv(1)
            if not chunk:
                break
            if chunk == b"\n" and chunks and chunks[-1] == b"\r":
                chunks.pop()
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def _parse_response(self, sock: socket.socket) -> Any:
        prefix = sock.recv(1)
        if not prefix:
            raise ConnectionError("Empty response from Redis")
        if prefix == b"+":
            return self._readline(sock).decode("utf-8")
        if prefix == b"-":
            message = self._readline(sock).decode("utf-8")
            raise RuntimeError(message)
        if prefix == b":":
            return int(self._readline(sock).decode("utf-8"))
        if prefix == b"$":
            length = int(self._readline(sock).decode("utf-8"))
            if length == -1:
                return None
            data = sock.recv(length)
            sock.recv(2)  # trailing CRLF
            return data.decode("utf-8")
        if prefix == b"*":
            length = int(self._readline(sock).decode("utf-8"))
            return [self._parse_response(sock) for _ in range(length)]
        raise RuntimeError(f"Unsupported Redis response prefix: {prefix}")

    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        parts = ["SET", key, value]
        if ex is not None:
            parts.extend(["EX", ex])
        try:
            response = self._send_command(*parts)
            self._available = True
            return response == "OK"
        except Exception:
            return False

    def get(self, key: str) -> Optional[str]:
        try:
            response = self._send_command("GET", key)
            self._available = True
            return response
        except Exception:
            return None

    def delete(self, key: str) -> None:
        try:
            self._send_command("DEL", key)
            self._available = True
        except Exception:
            pass

    def ttl(self, key: str) -> Optional[int]:
        try:
            ttl_value = self._send_command("TTL", key)
            self._available = True
            return int(ttl_value)
        except Exception:
            return None

    @property
    def available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            self._send_command("PING")
            self._available = True
        except Exception:
            self._available = False
        return self._available


_settings = get_settings()
redis_client = RedisClient(_settings.redis_host, _settings.redis_port, _settings.redis_db)


__all__ = ["redis_client", "RedisClient"]
