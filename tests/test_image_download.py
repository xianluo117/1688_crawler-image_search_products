from pathlib import Path

import pytest
import requests

from lib.image_api import ImageValidationError
from lib.image_download import (
    ImageDownloadError,
    download_validated_image,
    validate_public_https_url,
)


class FakeResponse:
    def __init__(
        self,
        body: bytes = b"",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.is_redirect = status_code in {301, 302, 303, 307, 308}
        self.is_permanent_redirect = status_code in {301, 308}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []
        self.closed = False

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.requested_urls.append(url)
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def _jpeg(size: int = 128) -> bytes:
    return b"\xff\xd8\xff" + b"\x00" * max(size - 3, 0)


def test_validate_public_https_url_rejects_http() -> None:
    with pytest.raises(ImageDownloadError, match="HTTPS"):
        validate_public_https_url("http://images.example.com/product.jpg")


def test_validate_public_https_url_rejects_private_address() -> None:
    with pytest.raises(ImageDownloadError, match="本机、内网或保留地址"):
        validate_public_https_url("https://127.0.0.1/product.jpg")


def test_download_validated_image_saves_public_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lib.image_download.validate_public_https_url",
        lambda url: None,
    )
    session = FakeSession(
        [
            FakeResponse(
                _jpeg(128),
                headers={"content-type": "image/jpeg", "content-length": "128"},
            )
        ]
    )

    path, image_type, image_bytes = download_validated_image(
        "https://images.example.com/product.jpg",
        tmp_path,
        1024,
        session_factory=lambda: session,
    )

    assert image_type == "jpeg"
    assert image_bytes == 128
    assert path.read_bytes() == _jpeg(128)
    assert session.closed is True
    path.unlink()


def test_download_validated_image_rejects_mime_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lib.image_download.validate_public_https_url",
        lambda url: None,
    )
    session = FakeSession(
        [FakeResponse(_jpeg(), headers={"content-type": "image/png"})]
    )

    with pytest.raises(ImageValidationError, match="Content-Type"):
        download_validated_image(
            "https://images.example.com/product.jpg",
            tmp_path,
            1024,
            session_factory=lambda: session,
        )

    assert list(tmp_path.glob("*")) == []


def test_download_validated_image_rejects_oversized_content_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lib.image_download.validate_public_https_url",
        lambda url: None,
    )
    session = FakeSession(
        [
            FakeResponse(
                _jpeg(),
                headers={"content-type": "image/jpeg", "content-length": "2048"},
            )
        ]
    )

    with pytest.raises(ImageValidationError, match="大小限制"):
        download_validated_image(
            "https://images.example.com/product.jpg",
            tmp_path,
            1024,
            session_factory=lambda: session,
        )


def test_download_validated_image_validates_redirect_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated_urls: list[str] = []

    def validate(url: str) -> None:
        validated_urls.append(url)
        if url.startswith("https://127.0.0.1"):
            raise ImageDownloadError("图片链接不得指向本机、内网或保留地址")

    monkeypatch.setattr("lib.image_download.validate_public_https_url", validate)
    session = FakeSession(
        [FakeResponse(status_code=302, headers={"location": "https://127.0.0.1/a"})]
    )

    with pytest.raises(ImageDownloadError, match="内网"):
        download_validated_image(
            "https://images.example.com/product.jpg",
            tmp_path,
            1024,
            session_factory=lambda: session,
        )

    assert validated_urls == [
        "https://images.example.com/product.jpg",
        "https://127.0.0.1/a",
    ]
