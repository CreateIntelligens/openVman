FROM python:3.11-slim

ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
ENV CUDA_LAUNCH_BLOCKING=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ffmpeg \
    libsndfile1 \
    libsm6 \
    libxext6 \
    redis-server \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade \
    pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY docker /app/docker

RUN sed -i 's/\r$//' /app/docker/start-backend-container.sh \
    && chmod +x /app/docker/start-backend-container.sh

EXPOSE 8200

ENTRYPOINT ["/app/docker/start-backend-container.sh"]
