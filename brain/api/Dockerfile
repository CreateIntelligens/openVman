FROM python:3.11-slim

WORKDIR /app

# 系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user so volume mounts work with user: UID:GID
RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -m appuser

ENV PYTHONPATH=/app

EXPOSE 8100

CMD ["python", "main.py"]
