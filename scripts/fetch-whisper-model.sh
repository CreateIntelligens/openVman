#!/bin/bash
# Wrapper to fetch local quantized whisper-base model assets using Python

set -e

echo "Starting download of quantized whisper-base model assets using Python..."
python scripts/fetch-whisper-model.py
echo "Whisper model assets successfully downloaded!"
