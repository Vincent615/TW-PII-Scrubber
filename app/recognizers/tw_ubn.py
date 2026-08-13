"""F6:統一編號 recognizer(entity:TW_UBN)。

檢查碼規則來源:enylin/taiwan-id-validator(財政部新制,2023-04 起):
  各位數乘權重 [1,2,1,2,1,2,4,1],乘積十位數+個位數相加後加總,
  總和 mod 5 == 0 即合格;第 7 位為 7 時,(總和+1) mod 5 == 0 亦合格。

信心分層(README 已註記):
  新制 mod 5 讓隨機 8 碼數字有 1/5 機率通過檢查碼,裸 8 碼一律高分
  會大量誤遮金額/訂單編號。因此:
  - 上下文含統編關鍵詞 + 檢查碼合格 → 0.95
  - 裸 8 碼檢查碼合格 → 0.45(低於門檻 0.5,預設不遮)
  - 有上下文但檢查碼不合 → 0.1(稽核可見,不遮)
  - 裸 8 碼且檢查碼不合 → 不產生 finding(避免稽核噪音)
"""

import re

from presidio_analyzer import EntityRecognizer, RecognizerResult

_RECOGNIZER_NAME_KEY = getattr(RecognizerResult, "RECOGNIZER_NAME_KEY", "recognizer_name")

UBN_WEIGHTS = (1, 2, 1, 2, 1, 2, 4, 1)

CONTEXT_SCORE = 0.95
BARE_SCORE = 0.45
INVALID_CHECKSUM_SCORE = 0.1

CONTEXT_KEYWORDS = ("統編", "統一編號", "營利事業", "買受人", "賣方", "公司統編")
_CONTEXT_BEFORE = 15  # 往前看的字元數
_CONTEXT_AFTER = 8    # 往後看的字元數

# 左右邊界對稱:緊貼英數字(不分左右)都視為更長 token 的子字串
_UBN_RE = re.compile(r"(?<![0-9A-Za-z])\d{8}(?![0-9A-Za-z])")


def is_valid_ubn(candidate: str) -> bool:
    if not re.fullmatch(r"\d{8}", candidate):
        return False
    products = [int(c) * w for c, w in zip(candidate, UBN_WEIGHTS)]
    total = sum(p // 10 + p % 10 for p in products)
    if total % 5 == 0:
        return True
    return candidate[6] == "7" and (total + 1) % 5 == 0


class TwUbnRecognizer(EntityRecognizer):
    ENTITY = "TW_UBN"

    def __init__(self, supported_language: str = "zh") -> None:
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=supported_language,
            name="TwUbnRecognizer",
        )

    def load(self) -> None:
        pass

    def _has_context(self, text: str, start: int, end: int) -> bool:
        window = text[max(0, start - _CONTEXT_BEFORE) : min(len(text), end + _CONTEXT_AFTER)]
        return any(kw in window for kw in CONTEXT_KEYWORDS)

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        results = []
        for m in _UBN_RE.finditer(text):
            checksum_ok = is_valid_ubn(m.group())
            has_context = self._has_context(text, m.start(), m.end())
            if checksum_ok and has_context:
                score = CONTEXT_SCORE
            elif checksum_ok:
                score = BARE_SCORE
            elif has_context:
                score = INVALID_CHECKSUM_SCORE
            else:
                continue  # 裸 8 碼且檢查碼不合:不產生 finding
            results.append(
                RecognizerResult(
                    entity_type=self.ENTITY,
                    start=m.start(),
                    end=m.end(),
                    score=score,
                    recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
                )
            )
        return results
