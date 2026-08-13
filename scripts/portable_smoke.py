"""可攜版煙霧測試:以 bundle 內的 Python 執行,驗證「最終解壓產物」。

用法(必須用 bundle 內的 python.exe 執行):
    <bundle>/python/python.exe scripts/portable_smoke.py <bundle 根目錄>

驗證項目:
1. torch/transformers 等 import 皆解析到 bundle 內(隔離性)。
2. 以 bundle Python 啟動伺服器(離線旗標),健康檢查通過。
3. /api/scrub 實測:身分證/手機/姓名確實被遮罩(不只看 200)。
4. txt 與 xlsx 檔案上傳流程各跑一次。
失敗即非零退出;結束時必定回收伺服器程序。
"""

import json
import subprocess
import sys

# Windows 主控台預設非 UTF-8(cp950/cp1252),印中文會 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
import time
import urllib.request
import uuid
from io import BytesIO
from pathlib import Path

BASE = "http://127.0.0.1:7860"


def fail(msg: str) -> None:
    print(f"[smoke] 失敗:{msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"[smoke] ✓ {msg}", flush=True)


def post_json(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, json.dumps(payload).encode(),
        {"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=120))


def post_file(path: str, filename: str, data: bytes, fields: dict) -> dict:
    boundary = uuid.uuid4().hex
    body = b""
    for key, value in fields.items():
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="{key}"\r\n\r\n{value}\r\n'
        ).encode()
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + path, body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return json.load(urllib.request.urlopen(req, timeout=300))


def main() -> int:
    if len(sys.argv) != 2:
        fail("用法:python portable_smoke.py <bundle 根目錄>")
    bundle = Path(sys.argv[1]).resolve()
    if not (bundle / "python").is_dir():
        fail(f"{bundle} 不是 bundle 根目錄")

    # 1. 隔離性:核心套件必須來自 bundle
    import torch  # noqa: E402
    import transformers  # noqa: E402
    for mod in (torch, transformers):
        mod_path = Path(mod.__file__).resolve()
        if bundle not in mod_path.parents:
            fail(f"{mod.__name__} 解析到 bundle 之外:{mod_path}")
    ok(f"import 隔離性(torch/transformers 皆位於 bundle 內)")

    # 2. 以 bundle Python 啟動伺服器
    env = {
        "SystemRoot": __import__("os").environ.get("SystemRoot", ""),
        "PATH": str(bundle / "python"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    server = subprocess.Popen(
        [
            str(bundle / "python" / "python.exe"),
            "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", "7860",
        ],
        cwd=str(bundle),
        env=env,
    )
    try:
        for _ in range(120):
            try:
                health = json.load(
                    urllib.request.urlopen(BASE + "/api/health", timeout=5)
                )
                if health.get("model_loaded"):
                    break
            except Exception:
                pass
            if server.poll() is not None:
                fail(f"伺服器提前結束,exit={server.returncode}")
            time.sleep(2)
        else:
            fail("健康檢查逾時(240 秒)")
        ok("伺服器啟動且模型載入完成")

        # 3. 實測脫敏(不只看 200)
        res = post_json(
            "/api/scrub",
            {"text": "本人王小明(A123456789,手機0912345678)申請理賠。", "mode": "mask"},
        )
        s = res["scrubbed_text"]
        for secret in ("A123456789", "0912345678"):
            if secret in s:
                fail(f"原值未被遮罩:{secret} / 輸出:{s}")
        for expected in ("A1******89", "091****678"):
            if expected not in s:
                fail(f"遮罩格式不符,缺 {expected} / 輸出:{s}")
        if res["stats"].get("PERSON", 0) < 1:
            fail(f"CKIP 未偵測到人名:{res['stats']}")
        ok(f"文字脫敏:{res['stats']}")

        # 4a. txt 檔案流程
        res = post_file(
            "/api/scrub-file", "smoke.txt",
            "客戶王小明,身分證A123456789。".encode("utf-8"),
            {"mode": "mask", "entities": "null", "column_strategies": "{}"},
        )
        if res["report"]["stats"].get("TW_NATIONAL_ID", 0) != 1:
            fail(f"txt 流程 stats 異常:{res['report']['stats']}")
        ok("txt 檔案流程")

        # 4b. xlsx 檔案流程
        from openpyxl import Workbook  # bundle site-packages

        wb = Workbook()
        ws = wb.active
        ws.append(["姓名", "備註"])
        ws.append(["王小明", "手機0912345678"])
        buf = BytesIO()
        wb.save(buf)
        res = post_file(
            "/api/scrub-file", "smoke.xlsx", buf.getvalue(),
            {
                "mode": "mask", "entities": "null",
                "column_strategies": json.dumps(
                    {"姓名": "mask_all", "備註": "ner"}, ensure_ascii=False
                ),
            },
        )
        stats = res["report"]["stats"]
        if stats.get("COLUMN_MASK", 0) != 1 or stats.get("TW_MOBILE", 0) != 1:
            fail(f"xlsx 流程 stats 異常:{stats}")
        ok(f"xlsx 檔案流程:{stats}")

        print("[smoke] 全部通過")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
