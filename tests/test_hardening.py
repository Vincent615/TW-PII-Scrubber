"""外部審查(2026-08)P0/P1 修正之回歸測試。

涵蓋:全形數字身分證漏遮、CKIP chunk 邊界 entity 被切斷、
本機 API 防護(Origin/Host/Content-Length)。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine import ScrubEngine
from app.main import app
from app.recognizers.ckip_ner import CkipNerRecognizer, OVERLAP_CHARS

NO_WHITELIST = Path("/nonexistent-whitelist.txt")


@pytest.fixture(scope="module")
def eng() -> ScrubEngine:
    return ScrubEngine(use_ckip=False, whitelist_path=NO_WHITELIST)


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="http://127.0.0.1:7860") as c:
        yield c


class TestFullwidthNationalId:
    """P0:字元類 [1289] 只吃 ASCII,全形寫的身分證整串漏掉。"""

    def test_all_fullwidth_id_masked(self, eng) -> None:
        res = eng.scrub("身分證A１２３４５６７８９", "mask")
        assert res["stats"] == {"TW_NATIONAL_ID": 1}
        assert "１２３４５６７" not in res["scrubbed_text"]

    def test_mixed_width_id_masked(self, eng) -> None:
        res = eng.scrub("身分證A1２３４５６７８９", "mask")
        assert res["stats"] == {"TW_NATIONAL_ID": 1}

    def test_fullwidth_bad_checksum_not_masked(self, eng) -> None:
        # 正規化不得放寬檢查碼防線
        text = "身分證A１２３４５６７８０"
        assert eng.scrub(text, "mask")["scrubbed_text"] == text

    @pytest.mark.parametrize(
        "text,entity",
        [
            ("手機０９１２３４５６７８", "TW_MOBILE"),
            ("統編０４５９５２５７", "TW_UBN"),
            ("保單號碼１２３４５６７８９０", "TW_POLICY_NO"),
            ("生日１０００１０１", "BIRTHDAY"),
        ],
    )
    def test_other_fullwidth_types(self, eng, text, entity) -> None:
        assert eng.scrub(text, "mask")["stats"] == {entity: 1}

    def test_fullwidth_preserved_outside_findings(self, eng) -> None:
        # 未命中的全形數字不得被改寫成半形(原文只讀)
        text = "數量２０二十件"
        assert eng.scrub(text, "mask")["scrubbed_text"] == text


class TestChunkBoundary:
    """P0:硬切點落在 entity 中間時,只會辨識出片段(前段字元裸奔)。"""

    @pytest.fixture(scope="class")
    def rec(self) -> CkipNerRecognizer:
        r = CkipNerRecognizer()
        r.load()
        return r

    def _straddling_text(self) -> str:
        filler = "本公司內部訓練資料僅供測試使用不含任何真實個人資料" * 20
        return filler[:398] + "王小明先生表示已完成對保手續" + filler[:100]

    def test_entity_across_boundary_fully_detected(self, rec) -> None:
        text = self._straddling_text()
        found = {
            text[r.start : r.end]
            for r in rec.analyze(text, entities=["PERSON", "ORG", "LOC"])
        }
        assert "王小明" in found

    def test_no_duplicate_spans_from_overlap(self, rec) -> None:
        text = "王小明住台北市,任職於國泰人壽。" * 30
        spans = [
            (r.start, r.end)
            for r in rec.analyze(text, entities=["PERSON", "ORG", "LOC"])
        ]
        assert len(spans) == len(set(spans))

    def test_all_occurrences_detected(self, rec) -> None:
        text = "王小明住台北市,任職於國泰人壽。" * 30
        persons = [
            r for r in rec.analyze(text, entities=["PERSON"])
            if text[r.start : r.end] == "王小明"
        ]
        assert len(persons) == 30

    def test_overlap_is_configured(self) -> None:
        assert OVERLAP_CHARS >= 10


class TestLocalApiGuards:
    """P1:惡意網頁跨站觸發、DNS rebinding、無 Content-Length 繞過限制。"""

    def test_same_origin_allowed(self, client) -> None:
        res = client.post(
            "/api/scrub",
            json={"text": "A123456789", "mode": "mask"},
            headers={"Origin": "http://127.0.0.1:7860"},
        )
        assert res.status_code == 200

    def test_no_origin_allowed(self, client) -> None:
        # 非瀏覽器客戶端(curl/腳本)不帶 Origin,須維持可用
        assert client.post(
            "/api/scrub", json={"text": "A123456789", "mode": "mask"}
        ).status_code == 200

    @pytest.mark.parametrize(
        "origin", ["https://evil.example.com", "http://127.0.0.1.evil.com"]
    )
    def test_cross_origin_rejected(self, client, origin) -> None:
        res = client.post(
            "/api/scrub",
            json={"text": "A123456789", "mode": "mask"},
            headers={"Origin": origin},
        )
        assert res.status_code == 403

    def test_localhost_origin_allowed(self, client) -> None:
        res = client.post(
            "/api/scrub",
            json={"text": "A123456789", "mode": "mask"},
            headers={"Origin": "http://localhost:7860"},
        )
        assert res.status_code == 200

    def test_foreign_host_header_rejected(self, client) -> None:
        # DNS rebinding:攻擊者網域解析到 127.0.0.1,Host 仍是該網域
        res = client.get("/api/health", headers={"Host": "evil.example.com"})
        assert res.status_code == 421

    def test_oversize_content_length_rejected(self, client) -> None:
        res = client.post(
            "/api/scrub",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(999 * 1024 * 1024),
            },
        )
        assert res.status_code == 413
