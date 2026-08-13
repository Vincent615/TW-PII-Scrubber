"""跨行/空白截斷個資偵測(影子映射)測試。

原則:偵測跑在影子文本,遮罩作用在原文——原文零修改、版面零破壞。
"""

from pathlib import Path

import pytest

from app.engine import ScrubEngine, build_shadow_text

NO_WHITELIST = Path("/nonexistent-whitelist.txt")


@pytest.fixture(scope="module")
def regex_engine() -> ScrubEngine:
    return ScrubEngine(use_ckip=False, whitelist_path=NO_WHITELIST)


@pytest.fixture(scope="module")
def full_engine() -> ScrubEngine:
    return ScrubEngine(use_ckip=True, whitelist_path=NO_WHITELIST)


class TestShadowBuilder:
    def test_join_single_newline_between_digits(self) -> None:
        shadow, s2o = build_shadow_text("A12345\n6789")
        assert shadow == "A123456789"
        assert len(s2o) == len(shadow)
        assert s2o[6] == 7  # shadow 的 '6' 在原文 index 7(跳過 \n)

    def test_join_single_space(self) -> None:
        assert build_shadow_text("A12345 6789")[0] == "A123456789"

    def test_join_crlf_as_one_unit(self) -> None:
        assert build_shadow_text("0912\r\n345678")[0] == "0912345678"

    def test_blank_line_not_joined(self) -> None:
        text = "0912\n\n345678"
        assert build_shadow_text(text)[0] == text

    def test_cjk_boundaries_not_joined(self) -> None:
        # 空白兩側只要有一側不是 ASCII 英數(如中文字)就保留
        text = "手機 0912345678 已登記"
        assert build_shadow_text(text)[0] == text

    def test_identity_mapping_without_joins(self) -> None:
        text = "王小明,0912345678。"
        shadow, s2o = build_shadow_text(text)
        assert shadow == text
        assert s2o == list(range(len(text)))


class TestCrossLineNationalId:
    def test_newline_break_masked_layout_preserved(self, regex_engine) -> None:
        res = regex_engine.scrub("身分證字號A12345\n6789,已核對。", "mask")
        assert res["stats"] == {"TW_NATIONAL_ID": 1}
        assert "A1****\n**89" in res["scrubbed_text"]
        # 斷行原位保留 → 對話行數不變
        assert res["scrubbed_text"].count("\n") == 1

    def test_space_break_masked(self, regex_engine) -> None:
        # SPEC v1 已知限制「A12345 6789 不支援」在此解除
        res = regex_engine.scrub("身分證 A12345 6789 已核對", "mask")
        assert res["stats"] == {"TW_NATIONAL_ID": 1}
        assert "A1**** **89" in res["scrubbed_text"]

    def test_invalid_checksum_crossline_not_masked(self, regex_engine) -> None:
        # 檢查碼防線:拼接後檢查碼不合 → 不遮
        text = "編號A12345\n6780核對"
        res = regex_engine.scrub(text, "mask")
        assert res["scrubbed_text"] == text

    def test_finding_spans_point_to_original(self, regex_engine) -> None:
        text = "字號A12345\n6789。"
        res = regex_engine.scrub(text, "mask")
        f = res["findings"][0]
        assert text[f["start"] : f["end"]] == "A12345\n6789"
        assert (
            res["scrubbed_text"][f["scrubbed_start"] : f["scrubbed_end"]]
            == f["replacement"]
        )


class TestCrossLineMobile:
    def test_with_keyword_masked(self, regex_engine) -> None:
        res = regex_engine.scrub("手機0912\n345678請記下", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}
        assert "091*\n***678" in res["scrubbed_text"]

    def test_bare_crossline_masked(self, regex_engine) -> None:
        # 手機不設關鍵詞門檻(2026-08-13 依實測回饋調整):
        # 09 開頭恰 10 碼特異度高,依鐵律「寧可多遮」一律遮罩
        res = regex_engine.scrub("0912\n345678", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}

    def test_trailing_space_before_newline(self, regex_engine) -> None:
        # 行尾多一個空格再換行(複製貼上常見)
        res = regex_engine.scrub("手機0912 \n345678", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}

    def test_indent_after_newline(self, regex_engine) -> None:
        # 換行後行首縮排
        res = regex_engine.scrub("0912\n 345678", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}

    def test_fullwidth_space_joined(self, regex_engine) -> None:
        res = regex_engine.scrub("手機0912　345678", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}

    def test_hyphen_linewrap_joined(self, regex_engine) -> None:
        # 連字號後換行:0912-↵345678 → 連字號變體
        res = regex_engine.scrub("0912-\n345678", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}

    def test_blank_line_never_joined(self, regex_engine) -> None:
        text = "手機0912\n\n345678"
        res = regex_engine.scrub(text, "mask")
        assert res["scrubbed_text"] == text

    def test_double_space_not_joined(self, regex_engine) -> None:
        # 兩格以上純空白=表格欄位對齊,不合併
        text = "編號0912  345678資料"
        assert regex_engine.scrub(text, "mask")["scrubbed_text"] == text

    def test_tab_not_joined(self, regex_engine) -> None:
        # tab=表格欄位分隔(Excel 複製),不合併
        text = "0912\t345678"
        assert regex_engine.scrub(text, "mask")["scrubbed_text"] == text


class TestCrossLineOthers:
    def test_email_crossline_masked(self, regex_engine) -> None:
        res = regex_engine.scrub("信箱 test@exam\nple.com 收信", "mask")
        assert res["stats"] == {"EMAIL_ADDRESS": 1}
        assert "test@exam" not in res["scrubbed_text"]

    def test_email_broken_at_symbol_boundaries(self, regex_engine) -> None:
        # 斷在 @ 之後與 . 之前(2026-08-13 使用者實測回報的樣態)
        res = regex_engine.scrub("信箱qwe@\ngmail\n.com請收", "mask")
        assert res["stats"] == {"EMAIL_ADDRESS": 1}
        s = res["scrubbed_text"]
        assert "q***@\ngmail\n.com" in s    # 帳號已遮、兩個斷行都保留
        assert "qwe@" not in s
        assert s.count("\n") == 2

    def test_email_broken_before_at(self, regex_engine) -> None:
        res = regex_engine.scrub("寄到 qwe\n@gmail.com 謝謝", "mask")
        assert res["stats"] == {"EMAIL_ADDRESS": 1}

    def test_email_broken_at_underscore(self, regex_engine) -> None:
        res = regex_engine.scrub("信箱 john_\ndoe@example.com 收信", "mask")
        assert res["stats"] == {"EMAIL_ADDRESS": 1}

    def test_prose_period_join_harmless(self, regex_engine) -> None:
        # 句末 ASCII 句點+換行會被合併進影子,但不得產生任何誤判
        text = "end of line.\nNext line 123"
        res = regex_engine.scrub(text, "mask")
        assert res["scrubbed_text"] == text

    def test_ubn_crossline_with_context_masked(self, regex_engine) -> None:
        res = regex_engine.scrub("統編1234\n5675開發票", "mask")
        assert res["stats"] == {"TW_UBN": 1}

    def test_landline_crossline_with_keyword(self, regex_engine) -> None:
        res = regex_engine.scrub("電話02-2720\n8889分機3", "mask")
        assert res["stats"] == {"TW_PHONE": 1}
        assert "02-****\n**89" in res["scrubbed_text"]

    def test_landline_crossline_without_keyword_not_masked(self, regex_engine) -> None:
        # 市話樣式較寬鬆,跨行拼接仍須電話關鍵詞
        text = "編號02-2720\n8889資料"
        assert regex_engine.scrub(text, "mask")["scrubbed_text"] == text


class TestPlaceholderCanonical:
    def test_broken_and_whole_share_placeholder(self, regex_engine) -> None:
        res = regex_engine.scrub("A123456789與字號A12345\n6789相同", "placeholder")
        assert res["scrubbed_text"].count("<TW_ID_1>") == 2
        # mapping 存正規形(乾淨值),不含斷行
        assert res["mapping"] == {"<TW_ID_1>": "A123456789"}


class TestHyphenMobile:
    def test_hyphen_3_3_variant(self, regex_engine) -> None:
        res = regex_engine.scrub("聯絡0912-345-678謝謝", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}
        assert "091*-***-678" in res["scrubbed_text"]

    def test_hyphen_6_variant(self, regex_engine) -> None:
        res = regex_engine.scrub("手機0912-345678", "mask")
        assert res["stats"] == {"TW_MOBILE": 1}

    def test_date_like_string_not_matched(self, regex_engine) -> None:
        text = "檔案2023-0912-345-678號"
        res = regex_engine.scrub(text, "mask")
        assert res["scrubbed_text"] == text


class TestCrossLineWithCkip:
    def test_mixed_entities_offsets_stay_aligned(self, full_engine) -> None:
        # 接合點「之後」的 entity 座標必須被正確位移回原文
        text = "客戶王小明來電,身分證A12345\n6789,住台北市。"
        res = full_engine.scrub(text, "mask")
        found = {text[f["start"] : f["end"]]: f["entity_type"] for f in res["findings"]}
        assert found.get("王小明") == "PERSON"
        assert found.get("A12345\n6789") == "TW_NATIONAL_ID"
        assert found.get("台北市") == "LOC"
        for f in res["findings"]:
            assert (
                res["scrubbed_text"][f["scrubbed_start"] : f["scrubbed_end"]]
                == f["replacement"]
            )
