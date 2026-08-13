#!/usr/bin/env bash
# 一鍵啟動(macOS/Linux)。需先:pip install -r requirements.txt
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
URL="http://127.0.0.1:7860"

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
