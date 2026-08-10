import hmac
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from fastapi import UploadFile


ALLOWED_IMAGE_TYPES = {
    "jpeg": ("image/jpeg", ".jpg"),
    "png": ("image/png", ".png"),
    "webp": ("image/webp", ".webp"),
}


class ApiAuthenticationError(RuntimeError):
    """远程 API 密钥认证失败。"""


class ImageValidationError(RuntimeError):
    """上传图片格式或大小不符合要求。"""


def verify_bearer_token(authorization: Optional[str], expected_api_key: str) -> None:
    if not authorization:
        raise ApiAuthenticationError("缺少 Authorization 请求头")

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise ApiAuthenticationError("Authorization 格式必须为 Bearer <API_KEY>")

    if not hmac.compare_digest(token, expected_api_key):
        raise ApiAuthenticationError("API 密钥无效")


def detect_image_type(header: bytes) -> Optional[str]:
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


async def save_validated_upload(
    upload: UploadFile,
    temp_dir: Path,
    max_image_bytes: int,
) -> Tuple[Path, str, int]:
    temp_dir.mkdir(parents=True, exist_ok=True)
    first_chunk = await upload.read(64 * 1024)
    image_type = detect_image_type(first_chunk[:32])
    if not image_type:
        raise ImageValidationError("仅支持 JPEG、PNG 或 WebP 图片")

    expected_content_type, suffix = ALLOWED_IMAGE_TYPES[image_type]
    if upload.content_type and upload.content_type.lower() != expected_content_type:
        raise ImageValidationError("图片内容与 Content-Type 不一致")

    temporary_path: Optional[Path] = None
    total_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=temp_dir,
            prefix="ali1688-upload-",
            suffix=suffix,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

            chunk = first_chunk
            while chunk:
                total_bytes += len(chunk)
                if total_bytes > max_image_bytes:
                    raise ImageValidationError(
                        f"图片超过大小限制：{max_image_bytes // (1024 * 1024)} MB"
                    )
                temporary_file.write(chunk)
                chunk = await upload.read(64 * 1024)

            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        if total_bytes == 0:
            raise ImageValidationError("上传图片为空")
        if os.name != "nt":
            temporary_path.chmod(0o600)
        return temporary_path, image_type, total_bytes
    except Exception:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
        raise
    finally:
        await upload.close()
