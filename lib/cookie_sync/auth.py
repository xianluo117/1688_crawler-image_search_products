import hashlib
import hmac
import re
import threading
import time
from typing import Dict, Optional


NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class AuthenticationError(RuntimeError):
    """Cookie 同步请求认证失败。"""


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_message(timestamp: str, nonce: str, body: bytes) -> bytes:
    return f"{timestamp}\n{nonce}\n{body_sha256(body)}".encode("utf-8")


def build_signature(
    shared_secret: str, timestamp: str, nonce: str, body: bytes
) -> str:
    return hmac.new(
        shared_secret.encode("utf-8"),
        canonical_message(timestamp, nonce, body),
        hashlib.sha256,
    ).hexdigest()


class NonceCache:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._entries: Dict[str, float] = {}
        self._lock = threading.Lock()

    def use_once(self, nonce: str, now: Optional[float] = None) -> None:
        current_time = time.time() if now is None else now
        cutoff = current_time - self.ttl_seconds

        with self._lock:
            self._entries = {
                key: seen_at
                for key, seen_at in self._entries.items()
                if seen_at >= cutoff
            }
            if nonce in self._entries:
                raise AuthenticationError("请求随机数已使用")
            self._entries[nonce] = current_time


def verify_request(
    *,
    shared_secret: str,
    timestamp: str,
    nonce: str,
    signature: str,
    body: bytes,
    max_clock_skew_seconds: int,
    nonce_cache: NonceCache,
    now: Optional[float] = None,
) -> None:
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("时间戳格式无效") from exc

    current_time = time.time() if now is None else now
    if abs(current_time - timestamp_value) > max_clock_skew_seconds:
        raise AuthenticationError("请求时间戳已过期")

    if not NONCE_PATTERN.fullmatch(nonce or ""):
        raise AuthenticationError("请求随机数格式无效")

    if not re.fullmatch(r"[a-f0-9]{64}", signature or ""):
        raise AuthenticationError("签名格式无效")

    expected = build_signature(shared_secret, timestamp, nonce, body)
    if not hmac.compare_digest(expected, signature):
        raise AuthenticationError("请求签名无效")

    nonce_cache.use_once(nonce, now=current_time)
