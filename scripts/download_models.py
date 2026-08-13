"""離線模型下載腳本。

在「有網路」的機器執行本腳本,把 CKIP NER 模型下載到 ./models/,
之後把整個專案目錄(含 models/)複製到無外網的環境即可運作。

用法:
    python scripts/download_models.py
"""

import sys

# Windows 主控台預設非 UTF-8(cp950/cp1252),印中文會 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
from pathlib import Path

from huggingface_hub import snapshot_download

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_NAME = "ckiplab/bert-base-chinese-ner"
# 鎖定 revision:確保任何時間點下載到的模型一致(供應鏈可重現)
MODEL_REVISION = "50c5afc0a0131e8ab93f54d9ebf9575af04c22d5"
# 只下載 PyTorch 推論所需檔案(略過 Flax 權重,體積省一半)
ALLOW_PATTERNS = [
    "config.json",
    "pytorch_model.bin",
    "model.safetensors",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.txt",
    "special_tokens_map.json",
    "added_tokens.json",
]
TARGET_DIR = PROJECT_ROOT / "models" / MODEL_NAME


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    print(f"下載 {MODEL_NAME}(revision {MODEL_REVISION[:12]})到 {TARGET_DIR} ...")
    snapshot_download(
        repo_id=MODEL_NAME,
        revision=MODEL_REVISION,
        local_dir=str(TARGET_DIR),
        allow_patterns=ALLOW_PATTERNS,
    )
    print("完成。之後程式將以本地路徑載入模型,完全離線。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
