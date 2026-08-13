"""上架前獨立審查(2026-08)發現之回歸測試。

每個測試對應一項已修復的審查發現,防止回歸;編號見各 docstring。
"""

import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from app import config
from app import file_handlers as fh
from app.engine import EntitySelectionError, ScrubEngine
from app.recognizers.ckip_ner import CkipNerRecognizer, SpanAlignmentError

NO_WHITELIST = Path("/nonexistent-whitelist.txt")


@pytest.fixture(scope="module")
def eng() -> ScrubEngine:
    return ScrubEngine(use_ckip=False, whitelist_path=NO_WHITELIST)


class TestSpaceSeparatedLandline:
    """#1(Critical):影子接合不得吃掉空白分隔市話的可辨識性。"""

    def test_space_separated_masked(self, eng) -> None:
        res = eng.scrub("電話02 2720 8889", "mask")
        assert res["stats"] == {"TW_PHONE": 1}
        assert "02 **** **89" in res["scrubbed_text"]

    def test_space_separated_without_keyword_still_masked(self, eng) -> None:
        # 原文直接命中分隔式樣式(非跨行拼接),不受關鍵詞防線約束
        res = eng.scrub("總機(02)2720 8889", "mask")
        assert res["stats"] == {"TW_PHONE": 1}


class TestFullwidthDigits:
    """#2(Critical):regex \\d 命中全形數字時,遮罩必須跟上(fail-safe)。"""

    def test_fullwidth_ubn_masked(self, eng) -> None:
        res = eng.scrub("統編０４５９５２５７", "mask")
        assert res["stats"] == {"TW_UBN": 1}
        assert "５９５２" not in res["scrubbed_text"]

    def test_fullwidth_policy_masked(self, eng) -> None:
        res = eng.scrub("保單號碼１２３４５６７８９０", "mask")
        assert res["stats"] == {"TW_POLICY_NO": 1}
        assert "３４５６７８" not in res["scrubbed_text"]


class TestSpanRealignUniqueness:
    """#4(High):重對齊只允許唯一候選,重複姓名必須 fail-closed。"""

    def test_ambiguous_duplicate_raises(self) -> None:
        with pytest.raises(SpanAlignmentError):
            CkipNerRecognizer._verify_span("王小明王小明", 4, 7, "王小明")

    def test_unique_candidate_realigns(self) -> None:
        assert CkipNerRecognizer._verify_span("○王小明", 0, 3, "王小明") == (1, 4)


class TestFilenamePii:
    """#3(High):檔名個資不得進輸出檔名與報告。"""

    def test_filename_id_masked(self, eng) -> None:
        res = fh._process_sync(
            "王小明_A123456789.txt", "txt", BytesIO("內容".encode()),
            "mask", None, "{}", eng,
        )
        assert "A123456789" not in res["filename"]
        assert "A123456789" not in res["report"]["source_filename"]


class TestZipNameSanitization:
    """#5(High):ZIP 檔名須同時消毒 POSIX 與 Windows 路徑成分。"""

    def test_traversal_names_cleaned(self) -> None:
        payload = [
            {"filename": name, "content_b64": base64.b64encode(b"x").decode()}
            for name in ["../../evil.txt", "..\\evil.txt", "C:\\temp\\evil.txt"]
        ]
        res = fh.bundle_zip(payload)
        names = ZipFile(BytesIO(base64.b64decode(res["zip_b64"]))).namelist()
        assert all(
            "\\" not in n and "/" not in n and ".." not in n and ":" not in n
            for n in names
        )


class TestResourceLimits:
    """#6/#7(High):限制須在大量記憶體配置之前生效。"""

    def test_bundle_rejects_by_encoded_length(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "MAX_ZIP_TOTAL_BYTES", 100)
        payload = [{"filename": "a.txt", "content_b64": "A" * 400}]
        with pytest.raises(Exception) as excinfo:
            fh.bundle_zip(payload)
        assert getattr(excinfo.value, "status_code", None) == 413

    def _make_xlsx(self, rows: int) -> BytesIO:
        wb = Workbook()
        ws = wb.active
        for i in range(rows):
            ws.append([f"r{i}", "x"])
        buffer = BytesIO()
        wb.save(buffer)
        return buffer

    def test_xlsx_row_cap(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "MAX_XLSX_ROWS", 5)
        with pytest.raises(Exception) as excinfo:
            fh._parse_xlsx(self._make_xlsx(rows=10))
        assert getattr(excinfo.value, "status_code", None) == 400

    def test_xlsx_uncompressed_cap(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "MAX_XLSX_UNCOMPRESSED_BYTES", 10)
        with pytest.raises(Exception) as excinfo:
            fh._parse_xlsx(self._make_xlsx(rows=3))
        assert getattr(excinfo.value, "status_code", None) == 400


class TestBirthdayCalendar:
    """#8(Medium):不存在的日期不得判為生日。"""

    @pytest.mark.parametrize("value", ["990229", "990230", "990231", "990431", "1000229"])
    def test_nonexistent_dates_rejected(self, eng, value) -> None:
        assert not eng.scrub(f"生日{value}", "mask")["stats"]

    def test_real_leap_day_detected(self, eng) -> None:
        # 民國 109 = 2020,閏年
        assert eng.scrub("生日1090229", "mask")["stats"] == {"BIRTHDAY": 1}


class TestSymmetricBoundaries:
    """#9(Medium):左右邊界對稱——右側緊貼字母同樣視為序號。"""

    @pytest.mark.parametrize(
        "text",
        ["0912345678A", "0912-345-678X", "統編12345675Q", "帳號0123456789012Z"],
    )
    def test_suffix_letter_not_matched(self, eng, text) -> None:
        assert not eng.scrub(text, "mask")["stats"]


class TestEntitySelection:
    """#10(Medium):空/全未知 entities 必須報錯,不得靜默改為全部偵測。"""

    def test_empty_list_raises(self, eng) -> None:
        with pytest.raises(EntitySelectionError):
            eng.scrub("A123456789", "mask", entities=[])

    def test_all_unknown_raises(self, eng) -> None:
        with pytest.raises(EntitySelectionError):
            eng.scrub("A123456789", "mask", entities=["BOGUS"])

    def test_none_means_default(self, eng) -> None:
        assert eng.scrub("A123456789", "mask", entities=None)["stats"]
