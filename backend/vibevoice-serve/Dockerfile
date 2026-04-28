FROM nvcr.io/nvidia/pytorch:25.01-py3

WORKDIR /app

ENV TZ=Asia/Taipei
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    tzdata \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    git+https://github.com/pengzhiliang/transformers.git \
    diffusers \
    accelerate \
    sentencepiece \
    fastapi \
    uvicorn \
    pydantic

EXPOSE 3000

CMD ["python", "api_server.py"]
