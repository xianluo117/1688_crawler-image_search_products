import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from lib.ali1688.ali1688 import Ali1688Upload

from lib.cookie_sync.auth import (
    AuthenticationError,
    NonceCache,
    verify_request,
)
from lib.cookie_sync.settings import CookieSyncSettings
from lib.cookie_sync.storage import (
    CookieStorageError,
    EncryptedCookieStore,
    cookie_expiry_summary,
)
from lib.image_api import (
    ApiAuthenticationError,
    ImageValidationError,
    save_validated_upload,
    verify_bearer_token,
)
from lib.image_download import ImageDownloadError, download_validated_image


class BrowserCookie(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=8192)
    domain: str = Field(default="", max_length=512)
    path: str = Field(default="/", max_length=2048)
    secure: bool = False
    httpOnly: bool = False
    expirationDate: Optional[float] = None
    sameSite: Optional[str] = Field(default=None, max_length=32)


class CookieSyncPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=r"^tampermonkey-1688$", max_length=64)
    cookies: List[BrowserCookie] = Field(min_length=1, max_length=300)


class CookieSyncResponse(BaseModel):
    status: str
    cookie_count: int
    earliest_expiry: Optional[str]


class ImageUrlSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_url: str = Field(min_length=1, max_length=4096)


class ImageSearchResponse(BaseModel):
    image_id: str
    search_url: str
    image_type: str
    image_bytes: int


def _validate_cookie_domains(cookies: List[BrowserCookie]) -> None:
    for cookie in cookies:
        domain = cookie.domain.lstrip(".").lower()
        if domain and domain != "1688.com" and not domain.endswith(".1688.com"):
            raise CookieStorageError("请求中包含非 1688 域名的 Cookie")


def create_app(
    settings: Optional[CookieSyncSettings] = None,
    uploader_factory: Callable[[], Ali1688Upload] = Ali1688Upload,
    image_downloader: Callable[
        [str, Path, int], Tuple[Path, str, int]
    ] = download_validated_image,
) -> FastAPI:
    runtime_settings = settings or CookieSyncSettings.from_env()
    store = EncryptedCookieStore(
        runtime_settings.cookie_file,
        runtime_settings.encryption_key,
    )
    nonce_cache = NonceCache(
        ttl_seconds=runtime_settings.max_clock_skew_seconds * 2
    )

    app = FastAPI(
        title="1688 Image Search API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    async def healthcheck() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/api/cookie-sync",
        response_model=CookieSyncResponse,
        status_code=status.HTTP_200_OK,
    )
    async def sync_cookie(
        request: Request,
        x_sync_timestamp: str = Header(...),
        x_sync_nonce: str = Header(...),
        x_sync_signature: str = Header(...),
    ) -> CookieSyncResponse:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > runtime_settings.max_body_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="请求体过大",
                    )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Content-Length 无效",
                ) from exc

        body = await request.body()
        if len(body) > runtime_settings.max_body_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="请求体过大",
            )

        try:
            verify_request(
                shared_secret=runtime_settings.shared_secret,
                timestamp=x_sync_timestamp,
                nonce=x_sync_nonce,
                signature=x_sync_signature,
                body=body,
                max_clock_skew_seconds=runtime_settings.max_clock_skew_seconds,
                nonce_cache=nonce_cache,
            )
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

        try:
            raw_payload: Any = json.loads(body.decode("utf-8"))
            payload = CookieSyncPayload.model_validate(raw_payload)
            _validate_cookie_domains(payload.cookies)
            cookies = [cookie.model_dump() for cookie in payload.cookies]
            store.save(cookies)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Cookie 数据格式无效",
            ) from exc
        except CookieStorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        return CookieSyncResponse(
            status="saved",
            cookie_count=len(cookies),
            earliest_expiry=cookie_expiry_summary(cookies),
        )

    async def perform_image_search(
        temporary_path: Path,
        image_type: str,
        image_bytes: int,
    ) -> ImageSearchResponse:
        uploader = uploader_factory()
        upstream_response = await run_in_threadpool(
            uploader.upload, str(temporary_path)
        )
        upstream_response.raise_for_status()
        payload = upstream_response.json()
        image_id = payload.get("data", {}).get("imageId", "")
        if not image_id:
            raise RuntimeError("1688 响应中不存在 imageId")

        return ImageSearchResponse(
            image_id=image_id,
            search_url=uploader.image_search_url(image_id=image_id),
            image_type=image_type,
            image_bytes=image_bytes,
        )

    def authenticate_api(authorization: Optional[str]) -> None:
        try:
            verify_bearer_token(authorization, runtime_settings.api_key)
        except ApiAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    @app.post(
        "/api/v1/image-search",
        response_model=ImageSearchResponse,
        status_code=status.HTTP_200_OK,
    )
    async def image_search(
        request: Request,
        image: UploadFile = File(...),
        authorization: Optional[str] = Header(default=None),
    ) -> ImageSearchResponse:
        authenticate_api(authorization)

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                multipart_overhead_bytes = 1024 * 1024
                if int(content_length) > (
                    runtime_settings.max_image_bytes + multipart_overhead_bytes
                ):
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="请求体超过允许大小",
                    )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Content-Length 无效",
                ) from exc

        temporary_path: Optional[Path] = None
        try:
            temporary_path, image_type, image_bytes = await save_validated_upload(
                image,
                runtime_settings.upload_temp_dir,
                runtime_settings.max_image_bytes,
            )
            return await perform_image_search(
                temporary_path,
                image_type,
                image_bytes,
            )
        except ImageValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="1688 上游请求失败或当前 Cookie 已失效",
            ) from exc
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

    @app.post(
        "/api/v1/image-search/url",
        response_model=ImageSearchResponse,
        status_code=status.HTTP_200_OK,
    )
    async def image_search_by_url(
        payload: ImageUrlSearchRequest,
        authorization: Optional[str] = Header(default=None),
    ) -> ImageSearchResponse:
        authenticate_api(authorization)

        temporary_path: Optional[Path] = None
        try:
            temporary_path, image_type, image_bytes = await run_in_threadpool(
                image_downloader,
                payload.image_url,
                runtime_settings.upload_temp_dir,
                runtime_settings.max_image_bytes,
            )
            return await perform_image_search(
                temporary_path,
                image_type,
                image_bytes,
            )
        except (ImageValidationError, ImageDownloadError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="1688 上游请求失败或当前 Cookie 已失效",
            ) from exc
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

    return app
