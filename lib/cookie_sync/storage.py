import base64
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken


REQUIRED_COOKIE_NAMES = {"_m_h5_tk", "_m_h5_tk_enc"}


class CookieStorageError(RuntimeError):
    """Cookie 存储或读取失败。"""


def _build_fernet(encryption_key: str) -> Fernet:
    digest = hashlib.sha256(encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def validate_cookies(cookies: List[Dict[str, Any]]) -> None:
    if not cookies:
        raise CookieStorageError("Cookie 列表为空")

    names = {
        str(cookie.get("name", ""))
        for cookie in cookies
        if cookie.get("name") and cookie.get("value")
    }
    missing = REQUIRED_COOKIE_NAMES - names
    if missing:
        raise CookieStorageError(
            "缺少 1688 必需 Cookie：" + ", ".join(sorted(missing))
        )


def cookie_expiry_summary(cookies: List[Dict[str, Any]]) -> Optional[str]:
    expirations = []
    for cookie in cookies:
        expiration = cookie.get("expirationDate")
        if isinstance(expiration, (int, float)) and expiration > 0:
            expirations.append(float(expiration))

    if not expirations:
        return None

    return datetime.fromtimestamp(min(expirations), tz=timezone.utc).isoformat()


class EncryptedCookieStore:
    def __init__(self, path: Path, encryption_key: str):
        self.path = path
        self.fernet = _build_fernet(encryption_key)

    def save(self, cookies: List[Dict[str, Any]]) -> None:
        validate_cookies(cookies)
        payload = {
            "version": 1,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "cookies": cookies,
        }
        plaintext = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        encrypted = self.fernet.encrypt(plaintext)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as temporary_file:
                temporary_file.write(encrypted)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)

            if os.name != "nt":
                temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            raise CookieStorageError(
                f"Cookie 文件不存在：{self.path}，请先通过油猴脚本同步"
            )

        try:
            decrypted = self.fernet.decrypt(self.path.read_bytes())
            payload = json.loads(decrypted.decode("utf-8"))
        except (InvalidToken, ValueError, OSError, json.JSONDecodeError) as exc:
            raise CookieStorageError(
                "Cookie 文件无法解密或内容已损坏，请重新同步 Cookie"
            ) from exc

        cookies = payload.get("cookies")
        if not isinstance(cookies, list):
            raise CookieStorageError("Cookie 文件格式无效")
        validate_cookies(cookies)
        return payload

    def as_requests_cookie_dict(self) -> Dict[str, str]:
        payload = self.load()
        return {
            str(cookie["name"]): str(cookie["value"])
            for cookie in payload["cookies"]
            if cookie.get("name") and cookie.get("value")
        }
