# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EDGE_HOST=0.0.0.0 \
    EDGE_PORT=8000

WORKDIR /app

RUN groupadd --system edge \
    && useradd --system --gid edge --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin edge

COPY pyproject.toml README.md ./
COPY edge ./edge

RUN python -m pip install --no-cache-dir . \
    && mkdir -p /app/data \
    && chown edge:edge /app/data

USER edge:edge

EXPOSE 8000

CMD ["python", "-m", "edge"]
