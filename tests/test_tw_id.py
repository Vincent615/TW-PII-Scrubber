"""台灣身分證 recognizer 測試。

測資出處:全部取自 enylin/taiwan-id-validator 公開測試套件
(https://github.com/enylin/taiwan-id-validator/blob/main/src/id-card-number.test.ts),
為檢查碼演算法的公開測試值,非任何真實個資。
涵蓋身分證與新式居留證(第二碼 8/9)。
"""

import pytest

from app.recognizers.tw_national_id import (
    INVALID_CHECKSUM_SCORE,
    TwNationalIdRecognizer,
    VALID_SCORE,
    is_valid_national_id,
)

# 合法:7 筆身分證 + 3 筆新式居留證(共 10 筆,滿足驗收條件)
VALID_IDS = [
    "A123456789",
    "F131104093",
    "O158238845",
    "N116247806",
    "L122544270",
    "C180661564",
    "Y123456788",
    "A800000014",
    "A900207177",
    "B801300667",
]

# 檢查碼錯誤:10 筆(格式正確但檢查碼不合)
INVALID_CHECKSUM_IDS = [
    "A123456788",
    "A123456780",
    "F131104091",
    "O158238842",
    "A123456781",
    "Y123456780",
    "L122544271",
    "A800000000",
    "F931104091",
    "O958238842",
]

# 一般英數字串:不得命中 regex(完全不產生 finding)
NON_MATCHING = [
    "B2C4567890",   # 訂單編號,第 3 碼是字母
    "1234567890",   # 純數字
    "a123456789",   # 小寫開頭
    "A323456789",   # 第二碼 3 不在 [1289]
    "ABCDE12345",
    "A12345 6789",  # 含空格(v1 已知限制,明確不支援)
]


@pytest.fixture(scope="module")
def recognizer() -> TwNationalIdRecognizer:
    return TwNationalIdRecognizer()


class TestChecksum:
    @pytest.mark.parametrize("tw_id", VALID_IDS)
    def test_valid_ids(self, tw_id: str) -> None:
        assert is_valid_national_id(tw_id)

    @pytest.mark.parametrize("tw_id", INVALID_CHECKSUM_IDS)
    def test_invalid_checksum(self, tw_id: str) -> None:
        assert not is_valid_national_id(tw_id)


class TestRecognizer:
    @pytest.mark.parametrize("tw_id", VALID_IDS)
    def test_detects_valid_id_with_high_score(self, recognizer, tw_id: str) -> None:
        text = f"客戶身分證字號:{tw_id},已完成核保。"
        results = recognizer.analyze(text, entities=["TW_NATIONAL_ID"])
        assert len(results) == 1
        r = results[0]
        assert r.entity_type == "TW_NATIONAL_ID"
        assert text[r.start : r.end] == tw_id
        assert r.score == VALID_SCORE

    @pytest.mark.parametrize("tw_id", INVALID_CHECKSUM_IDS)
    def test_invalid_checksum_gets_low_score(self, recognizer, tw_id: str) -> None:
        results = recognizer.analyze(f"編號 {tw_id} 待查", entities=["TW_NATIONAL_ID"])
        assert len(results) == 1
        assert results[0].score == INVALID_CHECKSUM_SCORE
        assert results[0].score < 0.5  # 低於引擎預設門檻 → 預設不脫敏

    @pytest.mark.parametrize("text", NON_MATCHING)
    def test_non_matching_strings(self, recognizer, text: str) -> None:
        assert recognizer.analyze(f"資料 {text} 結束", entities=["TW_NATIONAL_ID"]) == []

    def test_embedded_in_longer_token_not_matched(self, recognizer) -> None:
        # 前後緊貼英數字 → 視為更長字串的一部分,不誤判
        assert recognizer.analyze("XA123456789", entities=["TW_NATIONAL_ID"]) == []
        assert recognizer.analyze("A1234567891", entities=["TW_NATIONAL_ID"]) == []

    def test_multiple_ids_in_text(self, recognizer) -> None:
        text = "甲方A123456789,乙方F131104093。"
        results = recognizer.analyze(text, entities=["TW_NATIONAL_ID"])
        assert [text[r.start : r.end] for r in results] == ["A123456789", "F131104093"]

    def test_entity_filter(self, recognizer) -> None:
        # 未勾選 TW_NATIONAL_ID 時不得回傳結果
        assert recognizer.analyze("A123456789", entities=["PERSON"]) == []
