FROM nvcr.io/nvidia/pytorch:25.01-py3

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install the transformers fork that supports VibeVoice model classes
RUN pip install --no-cache-dir \
    git+https://github.com/pengzhiliang/transformers.git \
    diffusers \
    soundfile \
    accelerate \
    sentencepiece \
    protobuf \
    fastapi \
    uvicorn \
    pydantic

EXPOSE 3000

CMD ["python", "api_server.py"]
