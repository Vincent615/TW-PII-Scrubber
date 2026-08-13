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


def _host_of(value: str) -> str:
    """取出 Origin/Host 標頭中的主機名(去掉 scheme 與 port)。"""
    host = value.split("://", 1)[-1].split("/", 1)[0]
    if host.startswith("["):                      # IPv6 字面值
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


@app.middleware("http")
async def guard_request(request: Request, call_next):
    """本機防護三道:
    1. Host 標頭必須是本機(擋 DNS rebinding——攻擊者網域解析到 127.0.0.1)。
    2. 有 Origin 時必須是本機(擋惡意網頁跨站觸發本機推論)。
    3. 請求體大小:有 Content-Length 先擋;沒有(chunked)則邊讀邊計量,
       避免無 Content-Length 的請求繞過限制。
    """
    host_header = request.headers.get("host", "")
    if host_header and _host_of(host_header) not in config.ALLOWED_ORIGIN_HOSTS:
        return JSONResponse(status_code=421, content={"detail": "僅接受本機連線"})

    origin = request.headers.get("origin")
    if origin and _host_of(origin) not in config.ALLOWED_ORIGIN_HOSTS:
        return JSONResponse(status_code=403, content={"detail": "跨來源請求已拒絕"})

    limit = (
        config.MAX_REQUEST_BYTES_ZIP
        if request.url.path == "/api/bundle-zip"
        else config.MAX_REQUEST_BYTES_DEFAULT
    )
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > limit:
        return JSONResponse(status_code=413, content={"detail": "請求內容過大"})

    if content_length is None and request.method in ("POST", "PUT", "PATCH"):
        # 無 Content-Length(chunked)時大小限制形同虛設,直接要求標頭:
        # 瀏覽器 fetch 送字串或 FormData 一律會帶 Content-Length,
        # 本機 GUI 不受影響(411 為此情境的標準狀態碼)
        return JSONResponse(
            status_code=411, content={"detail": "請求須帶 Content-Length"}
        )

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
