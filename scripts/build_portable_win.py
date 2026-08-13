"""建置 Windows 綠色版(免安裝可攜資料夾)。

必須在 Windows + Python 3.13 上執行(通常由 GitHub Actions windows
runner 跑,見 .github/workflows/build-portable.yml)。產出:
dist/TW-PII-Scrubber-portable-win64.zip + SHA256SUMS.txt。

設計要點(依 2026-08 部署方案審查修正):
- Python 3.13 embeddable(3.11 官方已無 Windows binary),下載後驗 SHA-256。
- 相依以「建置機同版 Python 的 pip」裝進 site-packages(--only-binary,
  禁 sdist 臨時編譯),並驗證所有原生模組為 cp313。
- embeddable 不含 msvcp140 等 C++ 標準庫(實測確認),自 System32
  app-local 複製微軟允許散布的 VC runtime DLL。
- python313._pth 明確列出 site-packages 與應用根目錄(isolated 模式
  不吃 cwd)。
- GPL 合規:bundle 內附本專案「當前 commit」的完整原始碼壓縮檔、
  GPL 相依(ckip-transformers)的 sdist、全文授權與可攜版專屬聲明。
- 產出 build manifest(commit、pip freeze、各部尺寸、模型 hash)。

用法:
    python scripts/build_portable_win.py
前置:workspace 需已執行 scripts/download_models.py(models/ 就緒)。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

# Windows 主控台預設非 UTF-8(cp950/cp1252),印中文會 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PY_EMBED_VERSION = "3.13.11"
PY_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PY_EMBED_VERSION}/"
    f"python-{PY_EMBED_VERSION}-embed-amd64.zip"
)
PY_EMBED_SHA256 = "1ec066fb61ba5e8c73e29e048cd07c26850f74585e3a116005135b31b8004890"

# GPL 相依:sdist 隨 bundle 散布(corresponding source)
CKIP_TRANSFORMERS_VERSION = "0.3.4"

# 微軟允許隨應用程式散布的 VC runtime DLL(app-local deployment);
# torch/spacy 的原生模組需要,embeddable 只帶了 vcruntime140*
VC_RUNTIME_DLLS_REQUIRED = ["msvcp140.dll"]
VC_RUNTIME_DLLS_OPTIONAL = [
    "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
    "concrt140.dll", "vcomp140.dll", "vcruntime140.dll", "vcruntime140_1.dll",
]

# 進 bundle 的專案檔案(allowlist,不整目錄複製以免夾帶雜物)
PROJECT_ALLOWLIST = [
    "app", "static", "whitelist.txt",
    "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "SECURITY.md",
]

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "portable"
BUNDLE = BUILD / "TW-PII-Scrubber-portable-win64"
DIST = ROOT / "dist"


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[build] 錯誤:{msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_environment() -> None:
    if os.name != "nt":
        fail("本腳本必須在 Windows 上執行(embeddable 與 wheels 皆為 win_amd64)")
    if sys.version_info[:2] != (3, 13):
        fail(
            f"建置需以 Python 3.13 執行(現為 {sys.version.split()[0]}):"
            "pip 會依「執行它的直譯器」挑 wheel,版本不符會裝到錯的 ABI"
        )
    if not (ROOT / "models" / "ckiplab" / "bert-base-chinese-ner" / "config.json").exists():
        fail("models/ 未就緒,請先執行 scripts/download_models.py")


def prepare_dirs() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUNDLE.mkdir(parents=True)
    DIST.mkdir(exist_ok=True)


def fetch_embeddable() -> None:
    zip_path = BUILD / "python-embed.zip"
    log(f"下載 Python embeddable {PY_EMBED_VERSION} ...")
    urllib.request.urlretrieve(PY_EMBED_URL, zip_path)
    actual = sha256_file(zip_path)
    if actual != PY_EMBED_SHA256:
        fail(f"embeddable SHA-256 不符:{actual}")
    target = BUNDLE / "python"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)
    # _pth:isolated 模式只認這裡列出的路徑(cwd 不會自動加入)
    pth = target / "python313._pth"
    pth.write_text(
        "python313.zip\n"
        ".\n"
        "..\\site-packages\n"
        "..\n",              # 應用根目錄(import app 用)
        encoding="ascii",
    )
    log("embeddable 解壓完成,_pth 已設定")


def install_dependencies() -> None:
    site = BUNDLE / "site-packages"
    log("以 pip 安裝相依到 site-packages(--only-binary)...")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--target", str(site),
            "--only-binary", ":all:",
            "--no-compile",
            "-r", str(ROOT / "requirements.txt"),
        ],
        check=True,
    )
    # ABI 驗證:所有原生模組必須是 cp313
    bad = [
        p.name for p in site.rglob("*.pyd")
        if "cp3" in p.name and "cp313" not in p.name
    ]
    if bad:
        fail(f"發現非 cp313 的原生模組:{bad[:5]}")
    log(f"相依安裝完成,原生模組 ABI 驗證通過({len(list(site.rglob('*.pyd')))} 個 .pyd)")


def copy_vc_runtime() -> None:
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    target = BUNDLE / "python"
    copied = []
    for name in VC_RUNTIME_DLLS_REQUIRED + VC_RUNTIME_DLLS_OPTIONAL:
        src = system32 / name
        if src.exists():
            shutil.copy2(src, target / name)
            copied.append(name)
        elif name in VC_RUNTIME_DLLS_REQUIRED:
            fail(f"建置機缺少必要 VC runtime:{name}")
    log(f"VC runtime app-local 複製完成:{copied}")


def copy_project() -> None:
    for item in PROJECT_ALLOWLIST:
        src = ROOT / item
        dst = BUNDLE / item
        if not src.exists():
            fail(f"專案檔案不存在:{item}")
        if src.is_dir():
            shutil.copytree(
                src, dst,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            )
        else:
            shutil.copy2(src, dst)
    log("專案檔案複製完成(allowlist)")


def copy_models() -> dict:
    src = ROOT / "models" / "ckiplab" / "bert-base-chinese-ner"
    dst = BUNDLE / "models" / "ckiplab" / "bert-base-chinese-ner"
    dst.parent.mkdir(parents=True)
    # 只帶推論必要檔(排除 flax/msgpack/cache metadata)
    allowed = {
        "config.json", "pytorch_model.bin", "model.safetensors",
        "tokenizer_config.json", "tokenizer.json", "vocab.txt",
        "special_tokens_map.json", "added_tokens.json",
    }
    dst.mkdir()
    hashes = {}
    for f in sorted(src.iterdir()):
        if f.is_file() and f.name in allowed:
            shutil.copy2(f, dst / f.name)
            hashes[f.name] = sha256_file(f)
    if "config.json" not in hashes:
        fail("模型 config.json 不存在")
    if not ({"pytorch_model.bin", "model.safetensors"} & set(hashes)):
        fail("模型權重檔不存在")
    log(f"模型複製完成:{sorted(hashes)}")
    return hashes


def bundle_corresponding_source() -> None:
    """GPL 合規:附上與本 bundle 精確對應的原始碼。"""
    out = BUNDLE / "source"
    out.mkdir()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(
        ["git", "archive", "--format=zip",
         "-o", str(out / "tw-pii-scrubber-source.zip"), "HEAD"],
        cwd=ROOT, check=True,
    )
    log(f"專案原始碼已封存(commit {commit[:12]})")
    log("下載 ckip-transformers sdist(GPL 相依之對應原始碼)...")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "download",
            f"ckip-transformers=={CKIP_TRANSFORMERS_VERSION}",
            "--no-deps", "--no-binary", ":all:", "-d", str(out),
        ],
        check=True,
    )


def write_launcher_and_docs(model_hashes: dict) -> None:
    # 啟動.bat:無條件強制離線旗標;用 bundle 內的 python,與系統環境隔離
    launcher = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "cd /d %~dp0\r\n"
        "set URL=http://127.0.0.1:7860\r\n"
        "set HF_HUB_OFFLINE=1\r\n"
        "set TRANSFORMERS_OFFLINE=1\r\n"
        "set HF_HUB_DISABLE_TELEMETRY=1\r\n"
        "set PYTHONDONTWRITEBYTECODE=1\r\n"
        "set PYTHONPATH=\r\n"
        "echo TW-PII-Scrubber 可攜版啟動中... %URL%\r\n"
        "echo (首次啟動需載入模型與掃描檔案,可能需要一至數分鐘)\r\n"
        "start \"\" /min cmd /c \"(for /l %%i in (1,1,90) do "
        "(curl -s %URL%/api/health >nul 2>&1 && (start \"\" %URL% & exit) "
        "|| timeout /t 2 >nul)) & start \"\" %URL%\"\r\n"
        "python\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 7860\r\n"
    )
    (BUNDLE / "啟動.bat").write_bytes(launcher.encode("utf-8"))

    (BUNDLE / "可攜版說明.txt").write_text(
        "TW-PII-Scrubber 可攜版(綠色版)\n"
        "================================\n\n"
        "使用方式:解壓整個資料夾後,雙擊「啟動.bat」,瀏覽器會自動開啟\n"
        "http://127.0.0.1:7860。全程離線,資料不離開這台電腦。\n\n"
        "需求:64 位元 Windows 10/11。免安裝、免管理員權限、免網路。\n\n"
        "已知限制:\n"
        "- 若組織以 AppLocker/App Control 封鎖非白名單程式(含 exe/bat/dll),\n"
        "  本版無法執行,請洽 IT 白名單或改用 IT 派送。\n"
        "- 從網路下載的壓縮檔首次執行可能出現 SmartScreen 提示。\n"
        "- 防毒首次掃描數千個檔案可能使首次啟動較慢。\n"
        "- 連接埠 7860 被占用時無法啟動。\n\n"
        "授權:GPL-3.0-or-later。本可攜版內含 CKIP 模型權重與相依套件,\n"
        "詳見 PORTABLE_NOTICE.md 與 THIRD_PARTY_NOTICES.md;\n"
        "完整對應原始碼在 source/ 資料夾。\n",
        encoding="utf-8",
    )

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    (BUNDLE / "PORTABLE_NOTICE.md").write_text(
        "# 可攜版散布聲明 / Portable Distribution Notice\n\n"
        "本可攜版與倉庫版不同:**內含** CKIP NER 模型權重\n"
        "(ckiplab/bert-base-chinese-ner,GPL-3.0)、Python runtime 與全部\n"
        "相依套件,屬 GPL 意義下的散布(conveying)。\n\n"
        f"- 對應原始碼:`source/tw-pii-scrubber-source.zip`(commit `{commit}`)\n"
        "- GPL 相依之原始碼:`source/` 內之 ckip-transformers sdist\n"
        "- 各相依套件之授權全文:`site-packages/*/*.dist-info/` 內之\n"
        "  LICENSE/METADATA 檔案,總覽見 `THIRD_PARTY_NOTICES.md`\n"
        "- 模型檔案與其 SHA-256:見 `build_info.json`\n"
        "- Microsoft Visual C++ runtime DLL 依微軟可散布元件清單隨附\n"
        "  (app-local deployment)\n",
        encoding="utf-8",
    )
    log("啟動器與說明文件已產生")


def write_manifest(model_hashes: dict) -> None:
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--path", str(BUNDLE / "site-packages"),
         "--format", "freeze"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()

    def dir_size(path: Path) -> int:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": commit,
        "python_embed_version": PY_EMBED_VERSION,
        "python_embed_sha256": PY_EMBED_SHA256,
        "builder_python": sys.version,
        "packages": freeze,
        "model_files_sha256": model_hashes,
        "sizes_bytes": {
            "python": dir_size(BUNDLE / "python"),
            "site-packages": dir_size(BUNDLE / "site-packages"),
            "models": dir_size(BUNDLE / "models"),
            "total": dir_size(BUNDLE),
        },
    }
    (BUNDLE / "build_info.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"manifest 完成;bundle 總大小 {manifest['sizes_bytes']['total'] / 1e9:.2f} GB")


def make_zip() -> Path:
    log("壓縮 bundle(這一步較久)...")
    out = DIST / "TW-PII-Scrubber-portable-win64"
    zip_path = Path(shutil.make_archive(str(out), "zip", BUILD, BUNDLE.name))
    digest = sha256_file(zip_path)
    (DIST / "SHA256SUMS.txt").write_text(
        f"{digest}  {zip_path.name}\n", encoding="ascii"
    )
    size_gb = zip_path.stat().st_size / 1e9
    log(f"完成:{zip_path.name} = {size_gb:.2f} GB,SHA-256 {digest[:16]}...")
    if size_gb >= 1.9:
        log("警告:接近 GitHub Release 單一資產 2GiB 上限")
    return zip_path


def main() -> int:
    check_environment()
    prepare_dirs()
    fetch_embeddable()
    install_dependencies()
    copy_vc_runtime()
    copy_project()
    model_hashes = copy_models()
    bundle_corresponding_source()
    write_launcher_and_docs(model_hashes)
    write_manifest(model_hashes)
    make_zip()
    return 0


if __name__ == "__main__":
    sys.exit(main())
