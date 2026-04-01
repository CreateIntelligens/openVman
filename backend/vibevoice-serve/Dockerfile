# Use NVIDIA's optimized PyTorch image
FROM nvcr.io/nvidia/pytorch:24.07-py3

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Clone a community maintained fork or a specific version
# This step might fail if the repository is not available at this URL,
# but it follows Microsoft's reference structure.
# In a real setup, we might copy local code.
RUN git clone https://github.com/microsoft/VibeVoice.git . || true

# Install dependencies (might need specific versions as per search)
RUN pip install --no-cache-dir fastapi uvicorn pydantic

# Install the VibeVoice package if cloned successfully
RUN if [ -f "setup.py" ]; then pip install -e .; fi

# Copy our custom API server
COPY app /app/app

EXPOSE 3000

# Start the FastAPI server
CMD ["python", "app/api_server.py"]
