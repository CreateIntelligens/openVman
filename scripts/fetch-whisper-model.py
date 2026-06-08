import os
from huggingface_hub import hf_hub_download

def main():
    repo_id = "onnx-community/whisper-base"
    local_dir = "frontend/admin/public/models/whisper-base"

    files = [
        "config.json",
        "generation_config.json",
        "preprocessor_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "added_tokens.json",
        "normalizer.json",
        "onnx/encoder_model_quantized.onnx",
        "onnx/decoder_model_merged_quantized.onnx"
    ]

    print(f"Downloading whisper-base model files to {local_dir}...")
    for f in files:
        print(f"Fetching {f}...")
        hf_hub_download(
            repo_id=repo_id,
            filename=f,
            local_dir=local_dir,
            local_dir_use_symlinks=False
        )
    print("Download completed successfully!")

if __name__ == "__main__":
    main()
