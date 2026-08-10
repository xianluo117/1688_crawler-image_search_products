FROM python:3.12-slim AS builder

ENV POETRY_VERSION=2.4.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN python -m pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ALI1688_COOKIE_FILE=/app/runtime/ali1688.cookies.enc \
    ALI1688_UPLOAD_TEMP_DIR=/app/runtime/uploads

WORKDIR /app

RUN groupadd --system --gid 10001 ali1688 \
    && useradd --system --uid 10001 --gid ali1688 --home-dir /app --shell /usr/sbin/nologin ali1688 \
    && mkdir -p /app/runtime/uploads \
    && chown -R ali1688:ali1688 /app

COPY --from=builder --chown=ali1688:ali1688 /app/.venv /app/.venv
COPY --chown=ali1688:ali1688 config ./config
COPY --chown=ali1688:ali1688 lib ./lib
COPY --chown=ali1688:ali1688 main.py ./main.py

USER ali1688

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3).read()" || exit 1

CMD ["uvicorn", "lib.cookie_sync.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
