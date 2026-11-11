# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install --no-deps mediapipe==0.10.14

FROM python:3.12-slim AS runner

# runner 用的是基底映像自帶的 pip，builder 升級的那份不會複製過來。
RUN pip install --no-cache-dir --upgrade "pip>=26.2"

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
# The v2 producer works from the user's video. Historical conversion helpers,
# extracted templates and compatibility profiles are not production inputs.
# render_data converts existing v1 bundles; the README documents running it here.
COPY pipeline/__init__.py pipeline/bundle.py pipeline/cli.py \
     pipeline/frames.py pipeline/render_data.py pipeline/status.py \
     pipeline/video_lips.py pipeline/worker.py ./pipeline/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR=/tmp/matplotlib

CMD ["arq", "pipeline.worker.WorkerSettings"]
