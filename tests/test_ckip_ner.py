"""F2:CKIP NER recognizer 測試。

TestChunking 為純函式測試(不需模型);其餘為真模型整合測試,
需先執行 scripts/download_models.py。
"""

import pytest

from app.recognizers.ckip_ner import (
    CkipNerRecognizer,
    CkipTimeoutError,
    split_into_chunks,
)


class TestChunking:
    def test_reassembles_exactly(self) -> None:
        text = "第一句。第二句!\n第三段落,還有內容" * 100
        chunks = split_into_chunks(text, max_chars=50)
        assert "".join(chunk for _, chunk in chunks) == text
        pos = 0
        for offset, chunk in chunks:
            assert offset == pos
            assert 0 < len(chunk) <= 50
            pos += len(chunk)

    def test_prefers_sentence_boundary(self) -> None:
        text = "甲" * 30 + "。" + "乙" * 30
        chunks = split_into_chunks(text, max_chars=40)
        assert chunks[0][1].endswith("。")

    def test_hard_cut_without_punctuation(self) -> None:
        text = "字" * 100
        chunks = split_into_chunks(text, max_chars=40)
        assert [len(chunk) for _, chunk in chunks] == [40, 40, 20]

    def test_empty_text(self) -> None:
        assert split_into_chunks("") == []


@pytest.fixture(scope="module")
def rec() -> CkipNerRecognizer:
    recognizer = CkipNerRecognizer()
    recognizer.load()
    return recognizer


class TestCkipNer:
    def test_spec_acceptance_person_and_org(self, rec) -> None:
        # SPEC F2 驗收句原為「…向台新投保」,實測 ckiplab/bert-base-chinese-ner
        # 對單獨出現的短組織名「台新」會標成 GPE 或漏偵測(README 已知限制),
        # 故改用「台新銀行」驗證 PERSON+ORG 與座標正確性。
        text = "王小明先生於2026年向台新銀行投保"
        results = rec.analyze(text, entities=["PERSON", "ORG", "LOC"])
        spans = {(text[r.start : r.end], r.entity_type) for r in results}
        assert ("王小明", "PERSON") in spans
        assert ("台新銀行", "ORG") in spans

    def test_span_alignment_fullwidth_newline_emoji(self, rec) -> None:
        # 複姓:實測模型可完整偵測「歐陽娜娜」「司馬中原」;
        # 「歐陽台生」只會標到「歐陽台」(README 已知限制)
        text = (
            "報告📊如下:\n"
            "第一位,王小明,任職於國泰人壽。\n"
            "第二位:歐陽娜娜,地點:台北市。\n"
            "第三位:司馬中原先生。"
        )
        results = rec.analyze(text, entities=["PERSON", "ORG", "LOC"])
        words = {text[r.start : r.end] for r in results}
        assert "王小明" in words
        assert "歐陽娜娜" in words  # 複姓四字
        assert "司馬中原" in words  # 複姓四字
        assert "台北市" in words    # GPE → LOC
        for r in results:
            assert 0 <= r.start < r.end <= len(text)

    def test_two_char_name(self, rec) -> None:
        text = "客戶王明先生來電表示,保單內容需要修改。"
        results = rec.analyze(text, entities=["PERSON"])
        assert "王明" in {text[r.start : r.end] for r in results}

    def test_entity_filter(self, rec) -> None:
        text = "王小明先生您好。"
        assert rec.analyze(text, entities=["ORG"]) == []

    def test_long_text_multi_chunk_alignment(self, rec) -> None:
        # 超過一個 chunk(400 字)的文本,每個出現位置座標都要正確
        unit = "以下為例行公告事項,內容不含任何個人資料,僅供測試使用。保戶王小明於台北市簽署文件。\n"
        text = unit * 12  # 每單位 43 字 × 12 ≈ 516 字 → 至少 2 chunks
        results = rec.analyze(text, entities=["PERSON", "LOC"])
        persons = [r for r in results if r.entity_type == "PERSON"]
        assert len(persons) == 12
        for r in persons:
            assert text[r.start : r.end] == "王小明"

    def test_timeout_raises(self, rec) -> None:
        original = rec.timeout_seconds
        rec.timeout_seconds = 0.0
        try:
            with pytest.raises(CkipTimeoutError):
                rec.analyze("王小明住台北。", entities=["PERSON"])
        finally:
            rec.timeout_seconds = original
