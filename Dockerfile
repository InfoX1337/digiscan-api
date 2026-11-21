# syntax=docker/dockerfile:1.7
ARG PY_IMAGE=python:3.14.0-alpine3.22

FROM ghcr.io/astral-sh/uv:0.11.26 AS uv

FROM ${PY_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM ${PY_IMAGE} AS runtime
# tesseract (Apache-2.0) + polski model OCR; bez GPL
RUN apk add --no-cache tesseract-ocr tesseract-ocr-data-pol \
 && addgroup -S app && adduser -S -G app -H app
ENV APP_ENV=production PORT=8000 HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH" WEB_DIR=/app/web PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv ./.venv
COPY --from=build --chown=app:app /app/src ./src
COPY --chown=app:app web ./web
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD wget -qO- http://127.0.0.1:8000/api/v1/health || exit 1
CMD ["python", "-m", "formproof"]
