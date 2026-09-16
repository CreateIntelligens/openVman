# syntax=docker/dockerfile:1.7
#
# Three stages, two publishable images:
#
#   builder → base   published as openvman-backend-base (CI: --target base).
#                    Toolchain + parser stack (docling / firecrawl / pdf-inspector,
#                    a Rust extension with no wheel) + runtime apt packages. Slow,
#                    rarely changes.
#   runner           published as openvman-backend. FROM ${BASE_IMAGE}, which is
#                    the Hub base by default so a routine build only installs
#                    requirements.txt and copies app/. Pass
#                    --build-arg BASE_IMAGE=base to build everything locally.
#
# runner is deliberately a single layer on top of base: installing requirements
# straight into base's venv adds only the delta, whereas copying /opt/venv from
# a builder would re-emit the whole multi-GB venv on every build.
ARG BASE_IMAGE=tbdavid2019/openvman-backend-base:latest

# ---------------------------------------------------------------- builder
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH="/opt/venv/bin:/usr/local/cargo/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv

RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.88.0 \
    && rustc --version \
    && cargo --version

RUN pip install --no-cache-dir --upgrade pip setuptools wheel uv

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/usr/local/cargo/registry \
    uv pip install \
    "docling>=2.0.0" \
    "firecrawl-anydoc==0.1.7" \
    "pdf-inspector @ git+https://github.com/firecrawl/pdf-inspector.git@8b63ceb084f75dfd4425129d1d90d5bca45054e4"

# ---------------------------------------------------------------- base
FROM python:3.11-slim AS base

ENV TZ=Asia/Taipei
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
ENV CUDA_LAUNCH_BLOCKING=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    ghostscript \
    libsndfile1 \
    libsm6 \
    libxext6 \
    mupdf-tools \
    qpdf \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    tzdata \
    wget \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# ---------------------------------------------------------------- runner
FROM ${BASE_IMAGE} AS runner

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -r requirements.txt

COPY app /app/app

COPY docker /app/docker

RUN sed -i 's/\r$//' /app/docker/start-backend-container.sh \
    && chmod +x /app/docker/start-backend-container.sh

EXPOSE 8200

ENTRYPOINT ["/app/docker/start-backend-container.sh"]
