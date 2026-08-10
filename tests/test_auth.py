import time

import pytest

from lib.cookie_sync.auth import (
    AuthenticationError,
    NonceCache,
    build_signature,
    verify_request,
)


def test_verify_request_accepts_valid_signature() -> None:
    body = b'{"source":"tampermonkey-1688"}'
    timestamp = str(int(time.time()))
    nonce = "valid_nonce_1234567890"
    secret = "s" * 32

    verify_request(
        shared_secret=secret,
        timestamp=timestamp,
        nonce=nonce,
        signature=build_signature(secret, timestamp, nonce, body),
        body=body,
        max_clock_skew_seconds=300,
        nonce_cache=NonceCache(600),
    )


def test_verify_request_rejects_replayed_nonce() -> None:
    now = 1_700_000_000.0
    body = b"{}"
    timestamp = str(int(now))
    nonce = "replayed_nonce_123456"
    secret = "s" * 32
    cache = NonceCache(600)
    signature = build_signature(secret, timestamp, nonce, body)

    verify_request(
        shared_secret=secret,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
        body=body,
        max_clock_skew_seconds=300,
        nonce_cache=cache,
        now=now,
    )

    with pytest.raises(AuthenticationError, match="已使用"):
        verify_request(
            shared_secret=secret,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
            body=body,
            max_clock_skew_seconds=300,
            nonce_cache=cache,
            now=now,
        )


def test_verify_request_rejects_expired_timestamp() -> None:
    body = b"{}"
    timestamp = "1699999000"
    nonce = "expired_nonce_1234567"
    secret = "s" * 32

    with pytest.raises(AuthenticationError, match="已过期"):
        verify_request(
            shared_secret=secret,
            timestamp=timestamp,
            nonce=nonce,
            signature=build_signature(secret, timestamp, nonce, body),
            body=body,
            max_clock_skew_seconds=300,
            nonce_cache=NonceCache(600),
            now=1_700_000_000.0,
        )


def test_verify_request_rejects_modified_body() -> None:
    timestamp = str(int(time.time()))
    nonce = "modified_body_1234567"
    secret = "s" * 32
    signature = build_signature(secret, timestamp, nonce, b'{"a":1}')

    with pytest.raises(AuthenticationError, match="签名无效"):
        verify_request(
            shared_secret=secret,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
            body=b'{"a":2}',
            max_clock_skew_seconds=300,
            nonce_cache=NonceCache(600),
        )
