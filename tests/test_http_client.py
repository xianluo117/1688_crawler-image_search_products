from pathlib import Path

import requests

from lib.ali1688.ali1688 import ALI1688_UPLOAD_TIMEOUT, Ali1688Upload
from lib.func_txy import request_get, request_post


class FakeResponse:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_request_post_returns_open_response(monkeypatch) -> None:
    response = FakeResponse()
    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(requests, "post", fake_post)

    result = request_post("https://example.com", timeout=(10, 90))

    assert result is response
    assert response.closed is False
    assert captured["timeout"] == (10, 90)


def test_request_get_returns_open_response(monkeypatch) -> None:
    response = FakeResponse()

    monkeypatch.setattr(requests, "get", lambda **kwargs: response)

    result = request_get("https://example.com")

    assert result is response
    assert response.closed is False


def test_ali1688_upload_uses_extended_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"\xff\xd8\xffimage")
    captured = {}
    response = FakeResponse()

    monkeypatch.setattr(
        "lib.ali1688.ali1688.Token.__init__",
        lambda self: None,
    )
    monkeypatch.setattr(
        Ali1688Upload,
        "get_params",
        lambda self, data, t: {"sign": "test"},
    )
    monkeypatch.setattr(
        Ali1688Upload,
        "cookie_dict",
        lambda self: {"cookie": "value"},
    )

    def fake_request_post(**kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr("lib.ali1688.ali1688.request_post", fake_request_post)

    uploader = Ali1688Upload()
    result = uploader.upload(str(image_path))

    assert result is response
    assert captured["timeout"] == ALI1688_UPLOAD_TIMEOUT == (10, 90)
