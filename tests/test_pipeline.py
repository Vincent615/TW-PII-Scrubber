"""F3/F4:端到端脫敏管線測試(SPEC §11 情境 1-4、7、8)。

engine fixture 使用真 CKIP 模型;regex_engine 只用規則型 recognizers。
"""

from pathlib import Path

import pytest

from app.engine import ScrubEngine, TextTooLongError, mask_value

NO_WHITELIST = Path("/nonexistent-whitelist.txt")

HAPPY = "本人王小明(A123456789,手機0912345678,email: test@example.com)任職於台新人壽"


@pytest.fixture(scope="module")
def engine() -> ScrubEngine:
    eng = ScrubEngine(use_ckip=True, whitelist_path=NO_WHITELIST)
    eng.warmup()
    return eng


@pytest.fixture(scope="module")
def regex_engine() -> ScrubEngine:
    return ScrubEngine(use_ckip=False, whitelist_path=NO_WHITELIST)


class TestHappyPath:
    def test_mask_mode(self, engine) -> None:
        res = engine.scrub(HAPPY, mode="mask")
        s = res["scrubbed_text"]
        assert "A123456789" not in s and "A1******89" in s
        assert "0912345678" not in s and "091****678" in s
        assert "test@example.com" not in s and "t***@example.com" in s
        assert "王小明" not in s and "王○○" in s
        assert "台新人壽" not in s  # CKIP ORG

        types = {f["entity_type"] for f in res["findings"]}
        assert {"PERSON", "TW_NATIONAL_ID", "TW_MOBILE", "EMAIL_ADDRESS"} <= types
        # stats 與 findings 一致
        assert sum(res["stats"].values()) == len(res["findings"])
        # mask 模式不得回傳 mapping
        assert "mapping" not in res

    def test_placeholder_mode(self, engine) -> None:
        res = engine.scrub(HAPPY, mode="placeholder")
        s = res["scrubbed_text"]
        for placeholder in ("<PERSON_1>", "<TW_ID_1>", "<MOBILE_1>", "<EMAIL_1>"):
            assert placeholder in s
        assert res["mapping"]["<TW_ID_1>"] == "A123456789"
        assert res["mapping"]["<PERSON_1>"] == "王小明"
        assert "A123456789" not in s and "王小明" not in s
        # findings 的 replacement 是佔位符,但 original_masked 仍為遮罩版(報告安全)
        id_finding = next(f for f in res["findings"] if f["entity_type"] == "TW_NATIONAL_ID")
        assert id_finding["replacement"] == "<TW_ID_1>"
        assert id_finding["original_masked"] == "A1******89"


class TestChecksumGate:
    def test_invalid_checksum_not_scrubbed(self, regex_engine) -> None:
        # SPEC §11-2/4:A123456780 檢查碼錯誤、B2C4567890 訂單編號 → 原文不動
        text = "編號A123456780與B2C4567890為訂單資料"
        res = regex_engine.scrub(text, mode="mask")
        assert res["scrubbed_text"] == text
        assert res["findings"] == []


class TestPlaceholderConsistency:
    def test_same_name_same_number(self, engine) -> None:
        # SPEC §11-3:同名 → 同編號
        text = "王小明申請理賠,經審核後王小明獲得給付。"
        res = engine.scrub(text, mode="placeholder")
        assert res["scrubbed_text"].count("<PERSON_1>") == 2
        assert "<PERSON_2>" not in res["scrubbed_text"]
        assert res["mapping"] == {"<PERSON_1>": "王小明"}


class TestAlignment:
    def test_fullwidth_and_newline_spans(self, engine) -> None:
        # SPEC §11-7:全形逗號、換行,座標正確
        text = "聯絡人:王小明,\n身分證:A123456789。\n電話:0912345678"
        res = engine.scrub(text, mode="mask")
        found = {text[f["start"] : f["end"]] for f in res["findings"]}
        assert {"王小明", "A123456789", "0912345678"} <= found
        for f in res["findings"]:
            original = text[f["start"] : f["end"]]
            assert mask_value(f["entity_type"], original) == f["original_masked"]
            # 額外欄位:脫敏文字側座標切出 replacement
            assert (
                res["scrubbed_text"][f["scrubbed_start"] : f["scrubbed_end"]]
                == f["replacement"]
            )


class TestWhitelist:
    def test_whitelisted_org_not_masked(self, engine, tmp_path) -> None:
        # SPEC §11-8(F9):白名單命中即剔除
        wl = tmp_path / "whitelist.txt"
        wl.write_text("台新人壽\n# 註解行\n", encoding="utf-8")
        original_path = engine.whitelist_path
        engine.whitelist_path = wl
        try:
            res = engine.scrub("王小明任職於台新人壽。", mode="mask")
        finally:
            engine.whitelist_path = original_path
        assert "台新人壽" in res["scrubbed_text"]
        assert "王小明" not in res["scrubbed_text"]


class TestUbnPipeline:
    def test_ubn_with_context_masked(self, regex_engine) -> None:
        res = regex_engine.scrub("賣方統一編號:04595257", mode="mask")
        assert "04595257" not in res["scrubbed_text"]
        assert "04****57" in res["scrubbed_text"]

    def test_bare_eight_digits_not_masked(self, regex_engine) -> None:
        res = regex_engine.scrub("合計 12345675 元", mode="mask")
        assert "12345675" in res["scrubbed_text"]


class TestScrubBatch:
    def test_shared_placeholder_numbering_across_texts(self, regex_engine) -> None:
        # F7:跨儲存格同值同編號、不同值遞增編號
        texts = [
            "身分證A123456789,手機0912345678",
            "A123456789再次出現",
            "另一位F131104093",
        ]
        res = regex_engine.scrub_batch(texts, mode="placeholder")
        assert "<TW_ID_1>" in res["results"][0]["scrubbed_text"]
        assert "<TW_ID_1>" in res["results"][1]["scrubbed_text"]
        assert "<TW_ID_2>" in res["results"][2]["scrubbed_text"]
        assert res["mapping"]["<TW_ID_1>"] == "A123456789"
        assert res["mapping"]["<TW_ID_2>"] == "F131104093"
        assert res["stats"]["TW_NATIONAL_ID"] == 3

    def test_batch_mask_mode(self, regex_engine) -> None:
        res = regex_engine.scrub_batch(["A123456789", "無個資"], mode="mask")
        assert res["results"][0]["scrubbed_text"] == "A1******89"
        assert res["results"][1]["scrubbed_text"] == "無個資"
        assert "mapping" not in res

    def test_batch_time_budget(self, regex_engine) -> None:
        from app.engine import BatchTimeoutError

        # 用負數預算(明確已過期):Windows + Python 3.11 的 monotonic()
        # 解析度僅 ~15.6ms,0.0 預算在同一 tick 內不觸發(CI 實證)
        with pytest.raises(BatchTimeoutError):
            regex_engine.scrub_batch(
                ["A123456789"] * 3, mode="mask", time_budget_seconds=-1.0
            )

    def test_empty_batch(self, regex_engine) -> None:
        res = regex_engine.scrub_batch([], mode="placeholder")
        assert res["results"] == [] and res["mapping"] == {}


class TestValidation:
    def test_too_long_raises(self, regex_engine) -> None:
        with pytest.raises(TextTooLongError):
            regex_engine.scrub("字" * 50_001, mode="mask")

    def test_unknown_mode_raises(self, regex_engine) -> None:
        with pytest.raises(ValueError):
            regex_engine.scrub("測試", mode="delete")

    def test_entity_selection_respected(self, regex_engine) -> None:
        text = "身分證A123456789,手機0912345678"
        res = regex_engine.scrub(text, mode="mask", entities=["TW_MOBILE"])
        assert "A123456789" in res["scrubbed_text"]
        assert "0912345678" not in res["scrubbed_text"]

    def test_empty_text(self, regex_engine) -> None:
        res = regex_engine.scrub("", mode="mask")
        assert res["scrubbed_text"] == ""
        assert res["findings"] == []
