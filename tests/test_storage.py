from pathlib import Path

import pytest

from lib.cookie_sync.storage import CookieStorageError, EncryptedCookieStore


VALID_COOKIES = [
    {
        "name": "_m_h5_tk",
        "value": "token_4102444800000",
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


def test_encrypted_cookie_store_round_trip(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.enc"
    store = EncryptedCookieStore(cookie_file, "encryption-key-a" * 4)

    store.save(VALID_COOKIES)

    assert store.as_requests_cookie_dict() == {
        "_m_h5_tk": "token_4102444800000",
        "_m_h5_tk_enc": "encrypted-token",
    }
    assert b"token_4102444800000" not in cookie_file.read_bytes()


def test_store_rejects_missing_required_cookie(tmp_path: Path) -> None:
    store = EncryptedCookieStore(tmp_path / "cookies.enc", "encryption-key-a" * 4)

    with pytest.raises(CookieStorageError, match="_m_h5_tk_enc"):
        store.save(VALID_COOKIES[:1])


def test_store_rejects_wrong_encryption_key(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.enc"
    EncryptedCookieStore(cookie_file, "encryption-key-a" * 4).save(VALID_COOKIES)

    with pytest.raises(CookieStorageError, match="无法解密"):
        EncryptedCookieStore(
            cookie_file, "different-encryption-key-b" * 4
        ).load()
