import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(RuntimeError):
    """运行环境配置错误。"""


def _required_secret(name: str, minimum_length: int) -> str:
    value = os.getenv(name, "").strip()
    if len(value) < minimum_length:
        raise ConfigurationError(
            f"环境变量 {name} 未配置或长度不足，至少需要 {minimum_length} 个字符"
        )
    return value


@dataclass(frozen=True)
class CookieSyncSettings:
    shared_secret: str
    encryption_key: str
    cookie_file: Path
    api_key: str = "test-api-key-value-at-least-32-characters"
    max_clock_skew_seconds: int = 300
    max_body_bytes: int = 64 * 1024
    max_image_bytes: int = 10 * 1024 * 1024
    upload_temp_dir: Path = Path("runtime/uploads")

    @classmethod
    def from_env(cls) -> "CookieSyncSettings":
        cookie_file = Path(
            os.getenv("ALI1688_COOKIE_FILE", "runtime/ali1688.cookies.enc")
        )
        max_clock_skew = int(os.getenv("COOKIE_SYNC_MAX_CLOCK_SKEW", "300"))
        if max_clock_skew < 30 or max_clock_skew > 900:
            raise ConfigurationError(
                "COOKIE_SYNC_MAX_CLOCK_SKEW 必须在 30 到 900 秒之间"
            )

        max_image_mb = int(os.getenv("ALI1688_MAX_IMAGE_MB", "10"))
        if max_image_mb < 1 or max_image_mb > 50:
            raise ConfigurationError("ALI1688_MAX_IMAGE_MB 必须在 1 到 50 之间")

        return cls(
            shared_secret=_required_secret("COOKIE_SYNC_SHARED_SECRET", 32),
            encryption_key=_required_secret("COOKIE_ENCRYPTION_KEY", 32),
            cookie_file=cookie_file,
            api_key=_required_secret("ALI1688_API_KEY", 32),
            max_clock_skew_seconds=max_clock_skew,
            max_image_bytes=max_image_mb * 1024 * 1024,
            upload_temp_dir=Path(
                os.getenv("ALI1688_UPLOAD_TEMP_DIR", "runtime/uploads")
            ),
        )


@dataclass(frozen=True)
class CookieStorageSettings:
    encryption_key: str
    cookie_file: Path

    @classmethod
    def from_env(cls) -> "CookieStorageSettings":
        return cls(
            encryption_key=_required_secret("COOKIE_ENCRYPTION_KEY", 32),
            cookie_file=Path(
                os.getenv("ALI1688_COOKIE_FILE", "runtime/ali1688.cookies.enc")
            ),
        )
