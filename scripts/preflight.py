#!/usr/bin/env python3
"""啟動前環境檢查,由 run.sh / run.bat 在啟動伺服器之前呼叫。

沒有這道檢查時,虛擬環境忘了啟用會一路跑到 import 才失敗,使用者只看到
數十行 ModuleNotFoundError traceback,看不出真正的原因是「這次執行用到的
不是專案環境」。這裡改成先確認直譯器,再印出它的實際路徑與缺什麼。

刻意只用 Python 3.7 就有的語法:偵測到過舊的直譯器時,這支程式本身仍要
能跑起來把錯誤講清楚。
"""

from __future__ import annotations

import importlib.util
import os
import sys

REQUIRED = (
    "fastapi",
    "uvicorn",
    "spacy",
    "presidio_analyzer",
    "presidio_anonymizer",
    "ckip_transformers",
)

MIN_PYTHON = (3, 11)


def missing_packages():
    """回傳找不到的套件名稱。

    用 find_spec 而非真的 import:前者只在 sys.path 上找檔案、不執行模組,
    確認「有沒有裝」已經足夠,而 import spacy 要花好幾秒。
    """
    missing = []
    for name in REQUIRED:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except Exception:  # 安裝殘缺(有目錄沒 metadata)時 find_spec 會拋錯
            missing.append(name)
    return missing


def main():
    problems = []
    if sys.version_info < MIN_PYTHON:
        problems.append(
            "需要 Python %d.%d 以上,目前是 %d.%d"
            % (MIN_PYTHON + sys.version_info[:2])
        )
    missing = missing_packages()
    if missing:
        problems.append("缺少相依套件:" + "、".join(missing))

    if not problems:
        return 0

    windows = os.name == "nt"
    launcher = "run.bat" if windows else "./run.sh"

    print("啟動失敗:", file=sys.stderr)
    for problem in problems:
        print("  - " + problem, file=sys.stderr)
    # 印解析後的真實路徑:呼叫端給的可能是 shim(例如 macOS 的
    # /usr/bin/python3 實際會轉到 Xcode 底下),印出來才對得上自己的環境
    print("使用的直譯器:" + sys.executable, file=sys.stderr)
    print("", file=sys.stderr)
    print("最常見原因是虛擬環境沒有啟用。請擇一:", file=sys.stderr)
    if windows:
        print("  .venv\\Scripts\\Activate.ps1 後執行 run.bat", file=sys.stderr)
        print("  conda activate <環境名稱> 後執行 run.bat", file=sys.stderr)
        print("  set PYTHON=C:\\path\\to\\python.exe 後執行 run.bat", file=sys.stderr)
    else:
        print("  source .venv/bin/activate && ./run.sh", file=sys.stderr)
        print("  conda activate <環境名稱> && ./run.sh", file=sys.stderr)
        print("  PYTHON=/path/to/python ./run.sh", file=sys.stderr)
    print("", file=sys.stderr)
    print("若尚未安裝相依套件:pip install -r requirements.txt", file=sys.stderr)
    print("(%s 會在檢查通過後才啟動伺服器)" % launcher, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
