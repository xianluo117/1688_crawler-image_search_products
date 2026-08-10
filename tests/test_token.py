import time
from pathlib import Path

import pytest

from lib.ali1688.token import Token
from lib.cookie_sync.storage import EncryptedCookieStore


def _save_cookie_file(path: Path, expires_at_ms: int) -> None:
    EncryptedCookieStore(path, "token-test-encryption-key-" * 3).save(
        [
            {
                "name": "_m_h5_tk",
                "value": f"sign-token_{expires_at_ms}",
                "domain": ".1688.com",
                "path": "/",
            },
            {
                "name": "_m_h5_tk_enc",
                "value": "encrypted-token",
                "domain": ".1688.com",
                "path": "/",
            },
        ]
    )


def test_token_loads_synced_cookie(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.enc"
    encryption_key = "token-test-encryption-key-" * 3
    _save_cookie_file(cookie_file, int(time.time() * 1000) + 3_600_000)
    monkeypatch.setenv("COOKIE_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("ALI1688_COOKIE_FILE", str(cookie_file))

    token = Token()

    assert token.token == "sign-token"
    assert token.cookie_dict()["_m_h5_tk_enc"] == "encrypted-token"


def test_token_rejects_expired_cookie(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cookie_file = tmp_path / "cookies.enc"
    encryption_key = "token-test-encryption-key-" * 3
    _save_cookie_file(cookie_file, int(time.time() * 1000) - 1_000)
    monkeypatch.setenv("COOKIE_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("ALI1688_COOKIE_FILE", str(cookie_file))

    token = Token()

    with pytest.raises(RuntimeError, match="已过期"):
        _ = token.token
