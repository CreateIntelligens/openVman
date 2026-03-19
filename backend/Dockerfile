FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8200

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8200 ${UVICORN_RELOAD:+--reload}"]
