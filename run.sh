#!/usr/bin/env bash
# 一鍵啟動(macOS/Linux)。需先:pip install -r requirements.txt
set -euo pipefail
cd "$(dirname "$0")"

# 直譯器優先序:PYTHON 環境變數 > 專案內 .venv > PATH 上的 python3。
# 自動採用 .venv 是為了讓忘記 activate 的使用者也能直接啟動(與 run.bat 一致)。
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

URL="http://127.0.0.1:7860"

# 啟動前檢查。沒有這段的話,虛擬環境忘了啟用時 PATH 上仍有可用的
# python3,會一路跑到 import 才失敗,使用者只看到數十行 traceback。
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "找不到 Python 直譯器:${PYTHON}" >&2
  echo "請安裝 Python 3.11+,或用 PYTHON=/path/to/python ./run.sh 指定。" >&2
  exit 1
fi

if ! "$PYTHON" scripts/preflight.py; then
  exit 1
fi

echo "TW-PII-Scrubber 啟動中... ${URL}"
# 等健康檢查通過(模型載入完成)再開瀏覽器,避免開到尚未就緒的頁面
(
  for _ in $(seq 1 60); do
    if curl -s "${URL}/api/health" >/dev/null 2>&1; then
      if command -v open >/dev/null 2>&1; then open "$URL";
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
      exit 0
    fi
    sleep 2
  done
) &

exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 7860
