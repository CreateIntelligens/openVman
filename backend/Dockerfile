FROM vllm/vllm-openai:v0.9.0

ENV PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
ENV CUDA_LAUNCH_BLOCKING=1
ENV TORCH_CUDA_ARCH_LIST="8.9"
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
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY index-tts-vllm/requirements.txt /app/index-tts-vllm/requirements.txt

RUN pip install --no-cache-dir --break-system-packages --upgrade \
    torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 \
    && pip install --no-cache-dir --break-system-packages -r /app/requirements.txt \
    && pip install --no-cache-dir --break-system-packages -r /app/index-tts-vllm/requirements.txt \
    && pip install --no-cache-dir --break-system-packages "modelscope>=1.22,<2"

COPY app /app/app
COPY index-tts-vllm /app/index-tts-vllm
COPY docker /app/docker

RUN sed -i 's/\r$//' \
    /app/docker/start-backend-container.sh \
    /app/index-tts-vllm/entrypoint.sh \
    /app/index-tts-vllm/convert_hf_format.sh \
    && chmod +x \
    /app/docker/start-backend-container.sh \
    /app/index-tts-vllm/entrypoint.sh \
    /app/index-tts-vllm/convert_hf_format.sh

EXPOSE 8200 8011

ENTRYPOINT ["/app/docker/start-backend-container.sh"]
