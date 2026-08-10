from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from lib.cookie_sync.api import create_app
from lib.cookie_sync.settings import CookieSyncSettings


API_KEY = "remote-api-key-value-" * 3


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": {"imageId": "fake-image-id"}}


class FakeUploader:
    uploaded_path: Path

    def upload(self, filename: str) -> FakeResponse:
        self.uploaded_path = Path(filename)
        assert self.uploaded_path.exists()
        return FakeResponse()

    def image_search_url(self, image_id: str) -> str:
        return f"https://s.1688.com/youyuan/index.htm?imageId={image_id}"


class FailingUploader(FakeUploader):
    def upload(self, filename: str) -> FakeResponse:
        self.uploaded_path = Path(filename)
        raise requests.ConnectionError("upstream unavailable")


def _settings(tmp_path: Path, max_image_bytes: int = 1024) -> CookieSyncSettings:
    return CookieSyncSettings(
        shared_secret="shared-secret-value-" * 3,
        encryption_key="encryption-key-value-" * 3,
        cookie_file=tmp_path / "cookies.enc",
        api_key=API_KEY,
        max_image_bytes=max_image_bytes,
        upload_temp_dir=tmp_path / "uploads",
    )


def _jpeg(size: int = 32) -> bytes:
    return b"\xff\xd8\xff" + b"\x00" * max(size - 3, 0)


def test_image_search_requires_api_key(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path), FakeUploader))

    response = client.post(
        "/api/v1/image-search",
        files={"image": ("image.jpg", _jpeg(), "image/jpeg")},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_image_search_rejects_invalid_api_key(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path), FakeUploader))

    response = client.post(
        "/api/v1/image-search",
        headers={"Authorization": "Bearer wrong-key"},
        files={"image": ("image.jpg", _jpeg(), "image/jpeg")},
    )

    assert response.status_code == 401


def test_image_search_returns_result_and_cleans_temp_file(tmp_path: Path) -> None:
    uploader = FakeUploader()
    client = TestClient(create_app(_settings(tmp_path), lambda: uploader))

    response = client.post(
        "/api/v1/image-search",
        headers={"Authorization": f"Bearer {API_KEY}"},
        files={"image": ("ignored-name.jpg", _jpeg(128), "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "image_id": "fake-image-id",
        "search_url": "https://s.1688.com/youyuan/index.htm?imageId=fake-image-id",
        "image_type": "jpeg",
        "image_bytes": 128,
    }
    assert not uploader.uploaded_path.exists()


def test_image_search_rejects_unsupported_file(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path), FakeUploader))

    response = client.post(
        "/api/v1/image-search",
        headers={"Authorization": f"Bearer {API_KEY}"},
        files={"image": ("payload.txt", b"not-an-image", "text/plain")},
    )

    assert response.status_code == 422
    assert list((tmp_path / "uploads").glob("*")) == []


def test_image_search_rejects_oversized_file(tmp_path: Path) -> None:
    client = TestClient(
        create_app(_settings(tmp_path, max_image_bytes=16), FakeUploader)
    )

    response = client.post(
        "/api/v1/image-search",
        headers={"Authorization": f"Bearer {API_KEY}"},
        files={"image": ("image.jpg", _jpeg(64), "image/jpeg")},
    )

    assert response.status_code == 422
    assert list((tmp_path / "uploads").glob("*")) == []


def test_image_search_cleans_temp_file_on_upstream_error(tmp_path: Path) -> None:
    uploader = FailingUploader()
    client = TestClient(create_app(_settings(tmp_path), lambda: uploader))

    response = client.post(
        "/api/v1/image-search",
        headers={"Authorization": f"Bearer {API_KEY}"},
        files={"image": ("image.jpg", _jpeg(), "image/jpeg")},
    )

    assert response.status_code == 502
    assert not uploader.uploaded_path.exists()
