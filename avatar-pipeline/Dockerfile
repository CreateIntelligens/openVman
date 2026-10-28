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
COPY pipeline ./pipeline
COPY assets ./assets

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR=/tmp/matplotlib

CMD ["arq", "pipeline.worker.WorkerSettings"]
