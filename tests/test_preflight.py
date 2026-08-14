"""啟動前環境檢查(scripts/preflight.py)的行為測試。

CI 的四平台矩陣會跑到這裡,Windows 上的訊息分支與主控台編碼因而有真實
環境覆蓋。啟動腳本本身(run.sh / run.bat)仍未在 CI 中執行——它們對
preflight 的呼叫只有一行,刻意把未測面積壓到最小。
"""

import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = REPO_ROOT / "scripts" / "preflight.py"


def _load_preflight():
    """以路徑載入 scripts/preflight.py(該目錄不是套件)。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("preflight", PREFLIGHT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(python: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [python, str(PREFLIGHT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


@pytest.fixture(scope="module")
def bare_python(tmp_path_factory) -> str:
    """一個沒有任何專案相依的虛擬環境,用來重現「忘了啟用環境」。"""
    venv_dir = tmp_path_factory.mktemp("bare") / "venv"
    venv.create(venv_dir, with_pip=False)
    sub = "Scripts" if os.name == "nt" else "bin"
    exe = venv_dir / sub / ("python.exe" if os.name == "nt" else "python")
    assert exe.exists(), f"venv 未建立成功:{exe}"
    return str(exe)


class TestPassPath:
    """相依齊備時必須放行,且完全安靜。"""

    def test_current_env_passes(self) -> None:
        result = _run(sys.executable)
        assert result.returncode == 0, result.stderr

    def test_silent_on_success(self) -> None:
        """通過時不得有輸出,否則每次正常啟動都多出雜訊。"""
        result = _run(sys.executable)
        assert result.stdout == ""
        assert result.stderr == ""


class TestFailPath:
    """缺相依時要講清楚原因,而不是丟 traceback。"""

    def test_exits_nonzero(self, bare_python: str) -> None:
        assert _run(bare_python).returncode == 1

    def test_names_missing_packages(self, bare_python: str) -> None:
        stderr = _run(bare_python).stderr
        assert "缺少相依套件" in stderr
        assert "fastapi" in stderr

    def test_reports_actual_interpreter(self, bare_python: str) -> None:
        """必須印出實際跑起來的直譯器,使用者才對得上自己的環境。"""
        assert bare_python in _run(bare_python).stderr

    def test_no_traceback(self, bare_python: str) -> None:
        """使用者該看到的是指示,不是堆疊。"""
        assert "Traceback" not in _run(bare_python).stderr


class TestConsoleEncoding:
    """主控台編碼容不下中文時不得崩潰(非 zh-TW 的 Windows)。

    目前靠 stderr 預設的 backslashreplace 達成;若日後有人把訊息改印到
    stdout(預設 strict),就會變成 UnicodeEncodeError,由這裡擋下。
    """

    def test_survives_legacy_encoding(self, bare_python: str) -> None:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp1252"
        env.pop("PYTHONUTF8", None)  # CI 全域設了 1,這裡要測沒有它的情況
        result = _run(bare_python, env=env)
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert "UnicodeEncodeError" not in result.stderr


class TestPlatformHints:
    """兩個平台的建議都要能照抄;在任一平台上都驗得到。"""

    def test_posix_hints(self) -> None:
        hints = _load_preflight().activation_hints(windows=False)
        assert any("source .venv/bin/activate" in h for h in hints)
        assert all("\\" not in h for h in hints)

    def test_windows_hints(self) -> None:
        hints = _load_preflight().activation_hints(windows=True)
        assert any("Activate.ps1" in h for h in hints)
        assert all("run.bat" in h for h in hints)
        assert all("source " not in h for h in hints)

    def test_required_matches_runtime_imports(self) -> None:
        """清單漏了套件,檢查就形同虛設。"""
        required = set(_load_preflight().REQUIRED)
        assert {"fastapi", "uvicorn", "spacy", "ckip_transformers"} <= required
