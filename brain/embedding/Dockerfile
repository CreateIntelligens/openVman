# syntax=docker/dockerfile:1.7

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -r requirements.txt

# --- Stage 2: Runner ---
FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/appuser/.cache/huggingface \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Asia/Taipei

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 appuser \
    && useradd -m -u 1000 -g appuser appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY identity.py /app/identity.py
COPY registry.py /app/registry.py
COPY app.py /app/app.py
COPY tests /app/tests

RUN mkdir -p /home/appuser/.cache/huggingface \
    && chown -R appuser:appuser /app /home/appuser/.cache

USER appuser

EXPOSE 8009

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8009"]
