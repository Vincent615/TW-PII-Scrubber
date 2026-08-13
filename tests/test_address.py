"""台灣地址 recognizer 測試(entity=LOC,補 CKIP 只標行政區的缺口)。"""

from pathlib import Path

import pytest

from app.engine import ScrubEngine

NO_WHITELIST = Path("/nonexistent-whitelist.txt")


@pytest.fixture(scope="module")
def eng() -> ScrubEngine:
    return ScrubEngine(use_ckip=False, whitelist_path=NO_WHITELIST)


class TestTwAddress:
    @pytest.mark.parametrize("address", [
        "台北市大安區信義路四段1號5樓",
        "高雄市左營區博愛二路100巷5弄3號",
        "新竹縣竹北市光明六路10號",
        "中山路5號",                      # 無縣市前綴
        "台中市西屯區台灣大道三段99號12樓之3",
    ])
    def test_full_address_masked(self, eng, address) -> None:
        text = f"收件地址:{address},請確認。"
        res = eng.scrub(text, "mask")
        assert res["stats"].get("LOC", 0) >= 1
        # 地址核心(路名之後)不得殘留
        core = address[address.index("路") if "路" in address else address.index("道"):]
        assert core not in res["scrubbed_text"]

    @pytest.mark.parametrize("text", [
        "道路施工3號出口請改道",   # 路與號之間有敘述文字,不是地址
        "台北市大安區歡迎您",       # 只有行政區,無路號(交給 CKIP)
        "網頁第3號按鈕",
    ])
    def test_non_address_not_matched(self, eng, text) -> None:
        res = eng.scrub(text, "mask")
        assert "LOC" not in res["stats"]

    def test_placeholder_mode(self, eng) -> None:
        res = eng.scrub("寄到台北市中正區重慶南路一段122號。", "placeholder")
        assert "<LOC_1>" in res["scrubbed_text"]
        assert "重慶南路" not in res["scrubbed_text"]
