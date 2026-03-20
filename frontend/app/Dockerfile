FROM node:20-alpine

WORKDIR /app

# Install curl for model download
RUN apk add --no-cache curl

COPY package*.json ./
RUN npm install

# Create models directory
RUN mkdir -p /app/public/models

# Download Wav2Lip ONNX model during build
# This avoids runtime download and allows offline deployment
RUN curl -L -o /app/public/models/wav2lip.onnx \
    "https://huggingface.co/bluefoxcreation/Wav2lip-Onnx/resolve/main/wav2lip.onnx" \
    || echo "Model download failed - will use fallback at runtime"

EXPOSE 5173

CMD ["sh", "-c", "npx vite --host"]
