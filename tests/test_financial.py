"""生日/保單號碼/信用卡/客服代號/存款帳號 recognizers 測試(含跨行)。"""

from pathlib import Path

import pytest

from app.engine import ScrubEngine
from app.recognizers.financial import luhn_ok

NO_WHITELIST = Path("/nonexistent-whitelist.txt")


@pytest.fixture(scope="module")
def eng() -> ScrubEngine:
    return ScrubEngine(use_ckip=False, whitelist_path=NO_WHITELIST)


class TestBirthday:
    @pytest.mark.parametrize("value,masked", [
        ("1000101", "100****"),   # 民國100年1月1日(7碼)
        ("990101", "99****"),     # 民國99年(6碼)
        ("1150813", "115****"),
    ])
    def test_with_context_masked(self, eng, value, masked) -> None:
        res = eng.scrub(f"客戶生日{value},已核對。", "mask")
        assert res["stats"] == {"BIRTHDAY": 1}
        assert masked in res["scrubbed_text"]

    def test_bare_not_masked(self, eng) -> None:
        # 6-7 碼數字太常見(訂單/金額),無上下文不遮
        text = "編號1000101已出貨"
        assert eng.scrub(text, "mask")["scrubbed_text"] == text

    @pytest.mark.parametrize("value", [
        "991301",    # 月 13
        "990132",    # 日 32
        "990100",    # 日 00
        "1300101",   # 年 130 超出範圍
    ])
    def test_invalid_date_not_matched(self, eng, value) -> None:
        text = f"客戶生日{value}核對"
        assert eng.scrub(text, "mask")["scrubbed_text"] == text

    def test_crossline(self, eng) -> None:
        res = eng.scrub("出生日期100\n0101", "mask")
        assert res["stats"] == {"BIRTHDAY": 1}
        assert "100\n****" in res["scrubbed_text"]


class TestPolicyNo:
    @pytest.mark.parametrize("value", [
        "1234567890", "AB12345678", "ABC1234567", "ABCD123456", "ABCDE12345",
    ])
    def test_all_forms_with_context(self, eng, value) -> None:
        res = eng.scrub(f"您的保單號碼{value}已生效。", "mask")
        assert res["stats"] == {"TW_POLICY_NO": 1}
        assert value not in res["scrubbed_text"]

    def test_letter_form_bare_masked(self, eng) -> None:
        res = eng.scrub(f"這筆AB12345678資料", "mask")
        assert res["stats"] == {"TW_POLICY_NO": 1}
        assert "AB******78" in res["scrubbed_text"]

    def test_digit_form_bare_not_masked(self, eng) -> None:
        # 純數字 10 碼會撞金額/電話,裸值不遮
        text = "統計值1234567890筆"
        assert eng.scrub(text, "mask")["scrubbed_text"] == text

    def test_mobile_wins_without_context(self, eng) -> None:
        res = eng.scrub("手機0912345678", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}

    def test_policy_wins_with_context(self, eng) -> None:
        res = eng.scrub("保單號碼0912345678", "mask")
        assert res["stats"] == {"TW_POLICY_NO": 1}


class TestCreditCard:
    def test_luhn(self) -> None:
        assert luhn_ok("4111111111111111")
        assert luhn_ok("5105105105105100")
        assert not luhn_ok("4111111111111112")

    def test_plain_16_digits_masked(self, eng) -> None:
        res = eng.scrub("卡號4111111111111111請確認", "mask")
        assert res["stats"] == {"CREDIT_CARD": 1}
        assert "************1111" in res["scrubbed_text"]

    def test_hyphen_variant(self, eng) -> None:
        res = eng.scrub("卡號4111-1111-1111-1111", "mask")
        assert res["stats"] == {"CREDIT_CARD": 1}
        assert "****-****-****-1111" in res["scrubbed_text"]

    def test_space_grouped_via_shadow(self, eng) -> None:
        # 4-4-4-4 空格分組:影子映射把單一空白接回 → 命中,分隔原位保留
        res = eng.scrub("卡號4111 1111 1111 1111", "mask")
        assert res["stats"] == {"CREDIT_CARD": 1}
        assert "**** **** **** 1111" in res["scrubbed_text"]

    def test_luhn_invalid_not_masked(self, eng) -> None:
        text = "卡號4111111111111112請確認"
        assert eng.scrub(text, "mask")["scrubbed_text"] == text

    def test_crossline(self, eng) -> None:
        res = eng.scrub("卡號41111111\n11111111", "mask")
        assert res["stats"] == {"CREDIT_CARD": 1}


class TestAgentCode:
    @pytest.mark.parametrize("value,masked", [
        ("代號11", "代號**"),
        ("代號111", "代號***"),
        ("代號:23", "代號:**"),
    ])
    def test_masked(self, eng, value, masked) -> None:
        res = eng.scrub(f"由{value}為您服務", "mask")
        assert res["stats"] == {"AGENT_CODE": 1}
        assert masked in res["scrubbed_text"]

    @pytest.mark.parametrize("text", ["代號1號機", "代號1234行員"])
    def test_wrong_digit_count_not_matched(self, eng, text) -> None:
        assert eng.scrub(text, "mask")["scrubbed_text"] == text


class TestBankAccount:
    def test_bank_13_digits_bare_masked(self, eng) -> None:
        # 13-14 碼長串在客服語境幾乎必是帳號 → 裸值也遮
        res = eng.scrub("這串0123456789012請保存", "mask")
        assert res["stats"] == {"TW_BANK_ACCOUNT": 1}
        assert "*********9012" in res["scrubbed_text"]

    def test_post_14_digits_with_context(self, eng) -> None:
        res = eng.scrub("郵局帳號00212345678901,已登記。", "mask")
        assert res["stats"] == {"TW_BANK_ACCOUNT": 1}
        assert "**********8901" in res["scrubbed_text"]

    def test_15_digits_not_matched(self, eng) -> None:
        text = "序號012345678901234核對"
        res = eng.scrub(text, "mask")
        assert "TW_BANK_ACCOUNT" not in res["stats"]

    def test_crossline(self, eng) -> None:
        res = eng.scrub("匯款帳號0123456\n789012", "mask")
        assert res["stats"] == {"TW_BANK_ACCOUNT": 1}


class TestPlaceholderTags:
    def test_new_tags(self, eng) -> None:
        res = eng.scrub(
            "生日1000101,卡號4111111111111111,由代號11服務,匯款帳號0123456789012,保單AB12345678",
            "placeholder",
        )
        s = res["scrubbed_text"]
        for tag in ("<BIRTHDAY_1>", "<CARD_1>", "<AGENT_1>", "<ACCOUNT_1>", "<POLICY_1>"):
            assert tag in s, f"{tag} 不在 {s}"
        assert res["mapping"]["<CARD_1>"] == "4111111111111111"
