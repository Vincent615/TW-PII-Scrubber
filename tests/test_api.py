"""F3:API 端到端測試(TestClient 會觸發 lifespan,載入真 CKIP 模型)。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="http://127.0.0.1:7860") as c:
        yield c


class TestScrubApi:
    def test_happy_path_end_to_end(self, client) -> None:
        # SPEC F3 驗收:含身分證+姓名的段落
        payload = {
            "text": "本人王小明(A123456789)申請理賠。",
            "mode": "mask",
            "entities": ["PERSON", "TW_NATIONAL_ID"],
        }
        res = client.post("/api/scrub", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert "A1******89" in body["scrubbed_text"]
        assert "王○○" in body["scrubbed_text"]
        assert "A123456789" not in body["scrubbed_text"]
        types = {f["entity_type"] for f in body["findings"]}
        assert types == {"PERSON", "TW_NATIONAL_ID"}
        for f in body["findings"]:
            assert set(f) >= {
                "entity_type", "original_masked", "start", "end",
                "score", "recognizer", "replacement",
            }

    def test_placeholder_mode_returns_mapping(self, client) -> None:
        payload = {"text": "身分證A123456789", "mode": "placeholder"}
        body = client.post("/api/scrub", json=payload).json()
        assert body["mapping"] == {"<TW_ID_1>": "A123456789"}

    def test_too_long_returns_413(self, client) -> None:
        res = client.post("/api/scrub", json={"text": "字" * 50_001, "mode": "mask"})
        assert res.status_code == 413
        assert "分段" in res.json()["detail"]

    def test_invalid_mode_rejected(self, client) -> None:
        res = client.post("/api/scrub", json={"text": "測試", "mode": "delete"})
        assert res.status_code == 422

    def test_health(self, client) -> None:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["model_loaded"] is True

    def test_entities_list(self, client) -> None:
        body = client.get("/api/entities").json()
        ids = {e["id"] for e in body}
        assert {"PERSON", "TW_NATIONAL_ID", "TW_MOBILE", "EMAIL_ADDRESS"} <= ids

    def test_index_served(self, client) -> None:
        res = client.get("/")
        assert res.status_code == 200
        assert "TW-PII-Scrubber" in res.text

    def test_docs_disabled_no_cdn(self, client) -> None:
        # swagger-ui 走 CDN,離線環境必須停用
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
