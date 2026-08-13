"""手機、市話、統一編號 recognizers 測試。

測資出處:統編取自 enylin/taiwan-id-validator 公開測試套件(演算法
測試值);手機/市話為循序或重複數字構成的合成號碼(0912345678、
0900000000 等),非任何真實號碼。
"""

import pytest

from app.recognizers.tw_phone import TwLandlineRecognizer, TwMobileRecognizer
from app.recognizers.tw_ubn import TwUbnRecognizer, is_valid_ubn

# ---------- 手機 TW_MOBILE ----------

MOBILE_POSITIVE = ["0912345678", "0987654321", "0900000000", "0955123456", "0933221100"]


@pytest.fixture(scope="module")
def mobile_rec() -> TwMobileRecognizer:
    return TwMobileRecognizer()


@pytest.fixture(scope="module")
def landline_rec() -> TwLandlineRecognizer:
    return TwLandlineRecognizer()


@pytest.fixture(scope="module")
def ubn_rec() -> TwUbnRecognizer:
    return TwUbnRecognizer()


class TestMobile:
    @pytest.mark.parametrize("number", MOBILE_POSITIVE)
    def test_positive(self, mobile_rec, number: str) -> None:
        text = f"聯絡手機{number}。"
        results = mobile_rec.analyze(text, entities=["TW_MOBILE"])
        assert len(results) == 1
        assert text[results[0].start : results[0].end] == number

    @pytest.mark.parametrize(
        "text",
        [
            "091234567",      # 9 碼太短
            "09123456789",    # 11 碼太長
            "A0912345678",    # 緊貼字母,視為序號
            "訂單編號B2C4567890",
            "金額 1234567890 元",
        ],
    )
    def test_negative(self, mobile_rec, text: str) -> None:
        assert mobile_rec.analyze(text, entities=["TW_MOBILE"]) == []


# ---------- 市話 TW_PHONE ----------

LANDLINE_POSITIVE = [
    "02-27208889",
    "(02)2720-8889",
    "04-2228-9111",
    "03-5776085",
    "037-123456",
]


class TestLandline:
    @pytest.mark.parametrize("number", LANDLINE_POSITIVE)
    def test_positive(self, landline_rec, number: str) -> None:
        text = f"公司電話:{number},分機12。"
        results = landline_rec.analyze(text, entities=["TW_PHONE"])
        assert len(results) >= 1
        assert text[results[0].start : results[0].end] == number

    @pytest.mark.parametrize(
        "text",
        [
            "0912345678",        # 手機不是市話
            "2023-12345678",     # 年份開頭的編號
            "訂單1234-5678",     # 無 0 開頭區碼
            "統計值 3.1415926",
        ],
    )
    def test_negative(self, landline_rec, text: str) -> None:
        assert landline_rec.analyze(text, entities=["TW_PHONE"]) == []


# ---------- 統一編號 TW_UBN ----------

UBN_VALID = ["12345670", "12345671", "12345675", "12345676", "04595257"]
UBN_INVALID = ["12345678", "12345672", "04595253"]


class TestUbnChecksum:
    @pytest.mark.parametrize("ubn", UBN_VALID)
    def test_valid(self, ubn: str) -> None:
        assert is_valid_ubn(ubn)

    @pytest.mark.parametrize("ubn", UBN_INVALID)
    def test_invalid(self, ubn: str) -> None:
        assert not is_valid_ubn(ubn)


class TestUbnRecognizer:
    @pytest.mark.parametrize("ubn", UBN_VALID)
    def test_with_context_high_score(self, ubn_rec, ubn: str) -> None:
        text = f"買受人統一編號:{ubn},品名如附件。"
        results = ubn_rec.analyze(text, entities=["TW_UBN"])
        assert len(results) == 1
        assert text[results[0].start : results[0].end] == ubn
        assert results[0].score >= 0.9

    def test_bare_valid_number_below_threshold(self, ubn_rec) -> None:
        # 無上下文的裸 8 碼即使檢查碼合格,分數也須低於 0.5(避免誤遮金額/訂單編號)
        results = ubn_rec.analyze("合計 12345675 元", entities=["TW_UBN"])
        assert len(results) == 1
        assert results[0].score < 0.5

    def test_invalid_checksum_with_context_low_score(self, ubn_rec) -> None:
        results = ubn_rec.analyze("統編:12345678", entities=["TW_UBN"])
        assert len(results) == 1
        assert results[0].score < 0.5

    @pytest.mark.parametrize(
        "text",
        [
            "訂單金額 99999999999 元",  # 11 碼
            "電話02-27208889",          # 10 碼市話
            "1234567",                  # 7 碼
        ],
    )
    def test_no_eight_digit_candidate(self, ubn_rec, text: str) -> None:
        # 完全沒有獨立 8 碼數字 → 不產生任何 finding(低分亦不得 ≥0.5)
        results = [
            r for r in ubn_rec.analyze(text, entities=["TW_UBN"]) if r.score >= 0.5
        ]
        assert results == []
