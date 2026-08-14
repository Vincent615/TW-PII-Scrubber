"""公開文件的連結檢查。

起因:README 曾把「下載全部(ZIP)」寫成 `[下載全部(ZIP)](內含…json)`
——中括號後面緊接半形括號會被 Markdown 當成連結語法,GitHub 頁面上因此
出現一個指向不存在檔案的超連結。純文字的括號註解很容易誤觸這個規則,
所以用測試釘住:相對連結的目標必須真的存在。
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")
EXTERNAL = ("http://", "https://", "#", "mailto:")


def tracked_markdown() -> list[Path]:
    """只檢查納入版控的文件——它們才是使用者在 GitHub 上看得到的。"""
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.md"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):  # 非 git 環境(如 tarball)
        pytest.skip("需要 git 才能列出納入版控的文件")
    return [REPO_ROOT / name for name in result.stdout.split()]


def test_finds_documents() -> None:
    """守住檢查本身:清單抓不到檔案時,底下的測試會空轉而假性通過。"""
    names = {path.name for path in tracked_markdown()}
    assert "README.md" in names


def test_relative_links_resolve() -> None:
    broken = []
    for path in tracked_markdown():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for text, target in LINK.findall(line):
                if target.startswith(EXTERNAL):
                    continue
                # 相對連結以該文件所在目錄為基準(GitHub 的解析方式)
                resolved = path.parent / target.split("#")[0]
                if not resolved.exists():
                    broken.append(f"{path.name}:{lineno} [{text}]({target})")

    assert not broken, "連結目標不存在(可能是括號誤觸連結語法):\n" + "\n".join(
        broken
    )
