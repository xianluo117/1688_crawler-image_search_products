import ipaddress
import os
import socket
import tempfile
from itertools import chain
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import requests

from lib.image_api import ALLOWED_IMAGE_TYPES, ImageValidationError, detect_image_type


DOWNLOAD_CHUNK_BYTES = 64 * 1024
MAX_REDIRECTS = 3
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_READ_TIMEOUT_SECONDS = 30


class ImageDownloadError(RuntimeError):
    """远程图片下载失败。"""


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return bool(ip.is_global)


def validate_public_https_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ImageDownloadError("图片链接格式无效") from exc

    if parsed.scheme.lower() != "https":
        raise ImageDownloadError("图片链接必须使用 HTTPS")
    if not parsed.hostname:
        raise ImageDownloadError("图片链接缺少有效域名")
    if parsed.username is not None or parsed.password is not None:
        raise ImageDownloadError("图片链接不得包含用户凭据")
    if port is not None and not 1 <= port <= 65535:
        raise ImageDownloadError("图片链接端口无效")

    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                parsed.hostname,
                port or 443,
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise ImageDownloadError("图片域名解析失败") from exc

    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise ImageDownloadError("图片链接不得指向本机、内网或保留地址")


def _response_content_type(response: requests.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def download_validated_image(
    image_url: str,
    temp_dir: Path,
    max_image_bytes: int,
    session_factory: Callable[[], requests.Session] = requests.Session,
) -> Tuple[Path, str, int]:
    temp_dir.mkdir(parents=True, exist_ok=True)
    current_url = image_url
    temporary_path: Optional[Path] = None
    session = session_factory()

    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            validate_public_https_url(current_url)
            try:
                response = session.get(
                    current_url,
                    headers={
                        "Accept": "image/jpeg,image/png,image/webp",
                        "User-Agent": "1688-image-search-api/1.1",
                    },
                    stream=True,
                    allow_redirects=False,
                    timeout=(
                        DEFAULT_CONNECT_TIMEOUT_SECONDS,
                        DEFAULT_READ_TIMEOUT_SECONDS,
                    ),
                )
            except requests.RequestException as exc:
                raise ImageDownloadError("图片下载请求失败") from exc

            with response:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ImageDownloadError("图片服务器返回了无效重定向")
                    if redirect_count >= MAX_REDIRECTS:
                        raise ImageDownloadError("图片链接重定向次数过多")
                    current_url = urljoin(current_url, location)
                    continue

                try:
                    response.raise_for_status()
                except requests.RequestException as exc:
                    raise ImageDownloadError("图片服务器返回错误状态") from exc

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_image_bytes:
                            raise ImageValidationError(
                                f"图片超过大小限制：{max_image_bytes // (1024 * 1024)} MB"
                            )
                    except ValueError as exc:
                        raise ImageDownloadError("图片响应 Content-Length 无效") from exc

                chunks = response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES)
                first_chunk = next((chunk for chunk in chunks if chunk), b"")
                if not first_chunk:
                    raise ImageValidationError("远程图片为空")

                image_type = detect_image_type(first_chunk[:32])
                if not image_type:
                    raise ImageValidationError("仅支持 JPEG、PNG 或 WebP 图片")

                expected_content_type, suffix = ALLOWED_IMAGE_TYPES[image_type]
                content_type = _response_content_type(response)
                if content_type and content_type != expected_content_type:
                    raise ImageValidationError("图片内容与 Content-Type 不一致")

                total_bytes = 0
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=temp_dir,
                    prefix="ali1688-url-",
                    suffix=suffix,
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    for chunk in chain((first_chunk,), chunks):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > max_image_bytes:
                            raise ImageValidationError(
                                f"图片超过大小限制：{max_image_bytes // (1024 * 1024)} MB"
                            )
                        temporary_file.write(chunk)

                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())

                if os.name != "nt":
                    temporary_path.chmod(0o600)
                return temporary_path, image_type, total_bytes

        raise ImageDownloadError("图片链接重定向次数过多")
    except Exception:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
        raise
    finally:
        session.close()
