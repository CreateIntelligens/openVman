FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

WORKDIR /app

# Python 3.11 + 系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip python3.11-dev \
    build-essential \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 依賴（CUDA 12.1 PyTorch）
COPY requirements.txt .
RUN pip install --no-cache-dir "torch>=2.6" --index-url https://download.pytorch.org/whl/cu124 \
    && pip install --no-cache-dir overrides \
    && pip install --no-cache-dir -r requirements.txt

# Create non-root user so volume mounts work with user: UID:GID
RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -m appuser \
    && mkdir -p /home/appuser/.cache/huggingface /home/appuser/.openclaw/lancedb \
    && chown -R 1000:1000 /home/appuser

ENV PYTHONPATH=/app

EXPOSE 8100

CMD ["python", "main.py"]
