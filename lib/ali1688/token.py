import time
from typing import Dict

from requests.cookies import RequestsCookieJar, cookiejar_from_dict

from config.setting import ali1688_api_key
from lib.cookie_sync.settings import CookieStorageSettings
from lib.cookie_sync.storage import CookieStorageError, EncryptedCookieStore
from lib.func_txy import calculate_md5_hash


class Token:
    def __init__(self) -> None:
        settings = CookieStorageSettings.from_env()
        store = EncryptedCookieStore(settings.cookie_file, settings.encryption_key)
        try:
            cookie_dict = store.as_requests_cookie_dict()
        except CookieStorageError as exc:
            raise RuntimeError(str(exc)) from exc

        self.cookies: RequestsCookieJar = cookiejar_from_dict(cookie_dict)

    @property
    def t(self) -> int:
        return int(time.time() * 1000)

    def get_sign(self, data: str, t: int, token: str) -> str:
        text = f"{token}&{t}&{ali1688_api_key}&{data}"
        return calculate_md5_hash(text)

    @property
    def token(self) -> str:
        token_cookie = self.cookies.get("_m_h5_tk", "")
        if not token_cookie:
            raise RuntimeError(
                "同步 Cookie 中不存在 _m_h5_tk，请在 PC 浏览器重新同步"
            )

        token_parts = token_cookie.split("_", 1)
        if len(token_parts) != 2 or not token_parts[0]:
            raise RuntimeError("同步 Cookie 中的 _m_h5_tk 格式无效")

        try:
            expires_at_ms = int(token_parts[1])
        except ValueError as exc:
            raise RuntimeError("同步 Cookie 中的 _m_h5_tk 过期时间无效") from exc

        if expires_at_ms <= int(time.time() * 1000):
            raise RuntimeError("同步 Cookie 中的 _m_h5_tk 已过期，请重新同步")
        return token_parts[0]

    def cookie_dict(self) -> Dict[str, str]:
        return self.cookies.get_dict()
