"""F2:CKIP NER recognizer(包裝 ckip-transformers)。

- 模型只從本地 ./models/ 載入(鐵律:執行期不碰網路);缺模型 fail fast。
- CKIP NerToken.idx 為字元座標,理論上與 Presidio offset 直通,
  但每個 token 都做 span 驗證:text[start:end] 必須等於 token 文字,
  不符先嘗試小範圍重對齊,再不符直接拋例外(fail-closed,寧可報錯
  也不回傳座標錯誤的脫敏結果)。
- 逾時採合作式:文字切成 ≤CHUNK_CHARS 的段落,逐批推論,
  每批之前檢查累計耗時。Python thread 無法強殺,thread timeout 會留
  殭屍推論;合作式檢查點乾淨退出,50k 字上限保證最壞情況有界。
"""

import time
from pathlib import Path

from presidio_analyzer import EntityRecognizer, RecognizerResult

from app import config

_RECOGNIZER_NAME_KEY = getattr(RecognizerResult, "RECOGNIZER_NAME_KEY", "recognizer_name")

# CKIP(OntoNotes)→ 本工具 entity;GPE(行政區)併入 LOC
CKIP_TO_ENTITY = {
    "PERSON": "PERSON",
    "ORG": "ORG",
    "GPE": "LOC",
    "LOC": "LOC",
}
CKIP_SCORE = 0.85

CHUNK_CHARS = 400        # 每段字元上限(bert-base 上限 510 token,留裕度)
CHUNKS_PER_BATCH = 8     # 每批段數(批與批之間為逾時檢查點)
_BREAK_CHARS = "\n。!?;!?;"


class ModelNotFoundError(RuntimeError):
    pass


class CkipTimeoutError(RuntimeError):
    pass


class SpanAlignmentError(RuntimeError):
    pass


def split_into_chunks(text: str, max_chars: int = CHUNK_CHARS) -> list[tuple[int, str]]:
    """切段並保留每段在原文中的起始 offset。優先在換行/句末標點切。

    保證:所有段串接後等於原文(不遺漏、不重疊)。
    """
    chunks: list[tuple[int, str]] = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + max_chars, n)
        if end < n:
            window = text[pos:end]
            cut = max(window.rfind(c) for c in _BREAK_CHARS)
            if cut > 0:
                end = pos + cut + 1
        chunks.append((pos, text[pos:end]))
        pos = end
    return chunks


def resolve_model_path() -> Path:
    local_dir = config.CKIP_LOCAL_DIR
    if local_dir.is_dir() and any(local_dir.iterdir()):
        return local_dir
    raise ModelNotFoundError(
        "找不到本地模型,請先在有網路環境執行 scripts/download_models.py"
    )


class CkipNerRecognizer(EntityRecognizer):
    def __init__(
        self,
        model_path: Path | None = None,
        supported_language: str = "zh",
        timeout_seconds: float = config.CKIP_TIMEOUT_SECONDS,
    ) -> None:
        # 注意:EntityRecognizer.__init__ 結尾會呼叫 self.load(),
        # 所以屬性必須先設定。效果是建構時即載入模型(startup 載入、
        # 缺模型 fail fast,符合 SPEC §8)。
        self._model_path = model_path
        self._driver = None
        self.timeout_seconds = timeout_seconds
        super().__init__(
            supported_entities=sorted(set(CKIP_TO_ENTITY.values())),
            supported_language=supported_language,
            name="CkipNerRecognizer",
        )

    def load(self) -> None:
        """載入模型(僅一次)。FastAPI startup 時呼叫,常駐記憶體。"""
        if self._driver is not None:
            return
        # 鐵律:模型一律走本地路徑,並「無條件」強制 HF 離線模式——
        # setdefault 會被環境既有值覆蓋,不是強制(審查發現);
        # 需要重新下載模型時請用 scripts/download_models.py(獨立程序)
        import os

        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        from ckip_transformers.nlp import CkipNerChunker

        path = self._model_path or resolve_model_path()
        self._driver = CkipNerChunker(model_name=str(path), device=-1)

    def analyze(self, text, entities, nlp_artifacts=None):
        wanted = {e for e in self.supported_entities if e in entities}
        if not wanted or not text.strip():
            return []
        self.load()

        deadline = time.monotonic() + self.timeout_seconds
        chunks = split_into_chunks(text)
        results: list[RecognizerResult] = []
        for i in range(0, len(chunks), CHUNKS_PER_BATCH):
            if time.monotonic() > deadline:
                raise CkipTimeoutError("處理逾時,請縮短文字")
            batch = chunks[i : i + CHUNKS_PER_BATCH]
            # use_delim=True:CKIP 內部按「,。:;!?」切句(NerToken.idx
            # 仍為對原輸入的全域座標,已實測驗證),短句可明顯提升辨識率
            ner_lists = self._driver(
                [chunk for _, chunk in batch],
                use_delim=True,
                batch_size=CHUNKS_PER_BATCH,
                show_progress=False,
            )
            # 推論完成後再檢查一次 deadline:最後一批不得無上限超時
            if time.monotonic() > deadline:
                raise CkipTimeoutError("處理逾時,請縮短文字")
            for (offset, chunk), tokens in zip(batch, ner_lists):
                for tok in tokens:
                    entity = CKIP_TO_ENTITY.get(tok.ner)
                    if entity is None or entity not in wanted:
                        continue
                    word = tok.word
                    if not word or word.isspace():
                        continue
                    start = offset + tok.idx[0]
                    end = offset + tok.idx[1]
                    start, end = self._verify_span(text, start, end, word)
                    results.append(
                        RecognizerResult(
                            entity_type=entity,
                            start=start,
                            end=end,
                            score=CKIP_SCORE,
                            recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
                        )
                    )
        return results

    @staticmethod
    def _verify_span(text: str, start: int, end: int, word: str) -> tuple[int, int]:
        """驗證座標;不符時僅在「搜尋窗內候選唯一」時重對齊,否則拋例外。

        窗內若有多個相同字串(如「王小明王小明」),取第一個可能對到
        錯的那一個、讓真正目標裸奔——寧可整個請求失敗(fail-closed)。"""
        if text[start:end] == word:
            return start, end
        search_from = max(0, start - 8)
        search_to = min(len(text), end + 8)
        first = text.find(word, search_from, search_to)
        if first != -1 and text.find(word, first + 1, search_to) == -1:
            return first, first + len(word)
        raise SpanAlignmentError(
            f"CKIP span 對齊失敗:預期 {word!r} 於 [{start}:{end}],"
            f"實際為 {text[start:end]!r}(候選不存在或不唯一)"
        )
