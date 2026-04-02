FROM nvcr.io/nvidia/pytorch:25.01-py3

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "transformers>=5.3.0" \
    diffusers \
    fastapi \
    uvicorn \
    pydantic

EXPOSE 3000

CMD ["python", "api_server.py"]
