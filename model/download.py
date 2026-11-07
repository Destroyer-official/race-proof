import os
from huggingface_hub import hf_hub_download

# Define repository and the precise model file optimized for your 8GB RAM / CPU setup
REPO_ID = "mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF"
FILENAME = "Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf"

print(f"Starting download of {FILENAME}...")
print("This may take a few minutes depending on your internet connection (File size is ~2.7 GB).\n")

try:
    # Downloads the file directly into your current working directory
    downloaded_path = hf_hub_download(
        repo_id=REPO_ID,
        filename=FILENAME,
        local_dir=".",            # Saves right next to this script
        local_dir_use_symlinks=False
    )
    print("\n" + "="*50)
    print("DOWNLOAD COMPLETE!")
    print(f"Model file successfully saved to: {os.path.abspath(downloaded_path)}")
    print("="*50)

except Exception as e:
    print(f"\nAn error occurred during the download: {e}")
