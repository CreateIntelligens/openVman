# syntax=docker/dockerfile:1.7
# --- Stage 1: Builder ---
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-dev python3.11-venv python3.11-distutils python3-pip \
    build-essential curl ca-certificates git && \
    rm -rf /var/lib/apt/lists/*

# venv for clean copy into runner stage
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv

# uv for 10x+ faster installs
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip uv

# Layer 1 (rarely changes): PyTorch — isolated so requirements.txt edits don't bust this cache
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install "torch>=2.6" --index-url https://download.pytorch.org/whl/cu124

# Layer 2 (rarely changes): small standalone pin
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install overrides

# Layer 3 (changes often): project deps
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -r requirements.txt

# --- Stage 2: Runner ---
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS runner

WORKDIR /app

ENV TZ=Asia/Taipei
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3.11 python3.11-distutils libpython3.11 \
    libstdc++6 libgomp1 zlib1g tzdata && \
    ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -m appuser \
    && mkdir -p /home/appuser/.cache/huggingface \
    && mkdir -p /home/appuser/.opf \
    && chown -R 1000:1000 /home/appuser

EXPOSE 8100

CMD ["python", "main.py"]
