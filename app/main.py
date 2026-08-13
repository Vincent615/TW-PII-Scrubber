"""FastAPI 入口:掛載 static 與 API。

鐵律:只綁 127.0.0.1;停用 /docs(swagger-ui 走 CDN,離線環境禁止)。
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi import File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app import config
from app.engine import EntitySelectionError, ScrubEngine, TextTooLongError
from app.file_handlers import bundle_zip, preview_file, process_file
from app.recognizers.ckip_ner import (
    CkipTimeoutError,
    ModelNotFoundError,
    SpanAlignmentError,
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

ENTITY_LABELS = [
    {"id": "PERSON", "label": "姓名"},
    {"id": "TW_NATIONAL_ID", "label": "身分證"},
    {"id": "TW_MOBILE", "label": "手機"},
    {"id": "TW_PHONE", "label": "市話"},
    {"id": "TW_UBN", "label": "統一編號"},
    {"id": "EMAIL_ADDRESS", "label": "Email"},
    {"id": "ORG", "label": "組織"},
    {"id": "LOC", "label": "地址"},
    {"id": "BIRTHDAY", "label": "生日"},
    {"id": "TW_POLICY_NO", "label": "保單號碼"},
    {"id": "CREDIT_CARD", "label": "信用卡"},
    {"id": "AGENT_CODE", "label": "客服代號"},
    {"id": "TW_BANK_ACCOUNT", "label": "存款帳號"},
]

engine: Optional[ScrubEngine] = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global engine
    # 建構時即載入 CKIP 模型(常駐記憶體);缺模型 fail fast(SPEC §8)
    engine = ScrubEngine()
    yield
    engine = None


app = FastAPI(
    title="TW-PII-Scrubber",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    """依 Content-Length 先擋超大請求:限制若等到 multipart/JSON 全部
    進了記憶體才檢查,就失去防護意義。"""
    limit = (
        config.MAX_REQUEST_BYTES_ZIP
        if request.url.path == "/api/bundle-zip"
        else config.MAX_REQUEST_BYTES_DEFAULT
    )
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > limit:
        return JSONResponse(status_code=413, content={"detail": "請求內容過大"})
    return await call_next(request)


class ScrubRequest(BaseModel):
    text: str
    mode: Literal["mask", "placeholder"] = "mask"
    entities: Optional[list[str]] = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": engine is not None and engine.ckip is not None}


@app.get("/api/entities")
def entities() -> list[dict]:
    return ENTITY_LABELS


@app.post("/api/scrub")
def scrub(req: ScrubRequest) -> dict:
    if engine is None:
        raise HTTPException(status_code=503, detail="引擎尚未就緒")
    try:
        return engine.scrub(req.text, req.mode, req.entities)
    except EntitySelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TextTooLongError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except CkipTimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc)) from exc
    except SpanAlignmentError as exc:
        # fail-closed:座標對不上寧可整個請求失敗,也不回傳錯誤脫敏結果
        raise HTTPException(status_code=500, detail=f"座標對齊失敗,請回報:{exc}") from exc


@app.post("/api/scrub-file/preview")
async def scrub_file_preview(file: UploadFile = File(...)) -> dict:
    return await preview_file(file)


@app.post("/api/scrub-file")
async def scrub_uploaded_file(
    file: UploadFile = File(...),
    mode: Literal["mask", "placeholder"] = Form("mask"),
    entities: str = Form("null"),
    column_strategies: str = Form("{}"),
) -> dict:
    if engine is None:
        raise HTTPException(status_code=503, detail="引擎尚未就緒")
    return await process_file(file, mode, entities, column_strategies, engine)


@app.post("/api/bundle-zip")
def bundle_scrubbed_files(payload: dict) -> dict:
    return bundle_zip(payload.get("entries"))


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    run()
