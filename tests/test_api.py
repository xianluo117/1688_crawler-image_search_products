import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from lib.cookie_sync.api import create_app
from lib.cookie_sync.auth import build_signature
from lib.cookie_sync.settings import CookieSyncSettings
from lib.cookie_sync.storage import EncryptedCookieStore


SHARED_SECRET = "shared-secret-value-" * 3
ENCRYPTION_KEY = "encryption-key-value-" * 3


def _payload(domain: str = ".1688.com") -> bytes:
    return json.dumps(
        {
            "source": "tampermonkey-1688",
            "cookies": [
                {
                    "name": "_m_h5_tk",
                    "value": "token_4102444800000",
                    "domain": domain,
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
                {
                    "name": "_m_h5_tk_enc",
                    "value": "encrypted-token",
                    "domain": domain,
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _headers(body: bytes, nonce: str) -> dict:
    timestamp = str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Sync-Timestamp": timestamp,
        "X-Sync-Nonce": nonce,
        "X-Sync-Signature": build_signature(
            SHARED_SECRET, timestamp, nonce, body
        ),
    }


def _client(tmp_path: Path) -> tuple:
    cookie_file = tmp_path / "cookies.enc"
    settings = CookieSyncSettings(
        shared_secret=SHARED_SECRET,
        encryption_key=ENCRYPTION_KEY,
        cookie_file=cookie_file,
    )
    return TestClient(create_app(settings)), cookie_file


def test_sync_cookie_saves_encrypted_data(tmp_path: Path) -> None:
    client, cookie_file = _client(tmp_path)
    body = _payload()

    response = client.post(
        "/api/cookie-sync",
        content=body,
        headers=_headers(body, "api_success_nonce_12345"),
    )

    assert response.status_code == 200
    assert response.json()["cookie_count"] == 2
    assert "cookies" not in response.json()
    stored = EncryptedCookieStore(cookie_file, ENCRYPTION_KEY).as_requests_cookie_dict()
    assert stored["_m_h5_tk"] == "token_4102444800000"


def test_sync_cookie_rejects_replay(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = _payload()
    headers = _headers(body, "api_replayed_nonce_1234")

    assert client.post("/api/cookie-sync", content=body, headers=headers).status_code == 200
    response = client.post("/api/cookie-sync", content=body, headers=headers)

    assert response.status_code == 401


def test_sync_cookie_rejects_foreign_domain(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = _payload(".example.com")

    response = client.post(
        "/api/cookie-sync",
        content=body,
        headers=_headers(body, "api_foreign_nonce_12345"),
    )

    assert response.status_code == 422
