# Stage 1: Builder
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Heavy packages pinned separately so requirements.txt changes don't bust this cache layer
RUN pip install --no-cache-dir \
    "docling>=2.0.0" \
    "markitdown[all]>=0.1,<1"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runner
FROM python:3.11-slim

ENV TZ=Asia/Taipei
ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
ENV CUDA_LAUNCH_BLOCKING=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libsndfile1 \
    libsm6 \
    libxext6 \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    tzdata \
    wget \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

COPY docker /app/docker

RUN sed -i 's/\r$//' /app/docker/start-backend-container.sh \
    && chmod +x /app/docker/start-backend-container.sh

EXPOSE 8200

ENTRYPOINT ["/app/docker/start-backend-container.sh"]
