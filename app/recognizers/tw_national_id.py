"""F1:台灣身分證/新式居留證 recognizer(entity:TW_NATIONAL_ID)。

檢查碼規則來源:enylin/taiwan-id-validator。
字母對照表為官方非連續表(注意 I=34、O=35、W=32、X=30、Y=31、Z=33),
已逐字比對上游原始碼的 TAIWAN_ID_LOCALE_CODE_LIST 預計算值驗證無誤。

演算法:首字母轉兩位數 d1d2,與後 9 碼組成 11 個數字,
乘上權重 [1,9,8,7,6,5,4,3,2,1,1] 加總,總和 mod 10 == 0 即合格。
新式居留證(第二碼 8/9)使用完全相同的檢查碼演算法。

已知限制(v1):全形數字、含空白分隔(A12345 6789)不支援。
"""

import re

from presidio_analyzer import EntityRecognizer, RecognizerResult

LETTER_VALUES = {
    "A": 10, "B": 11, "C": 12, "D": 13, "E": 14, "F": 15, "G": 16,
    "H": 17, "I": 34, "J": 18, "K": 19, "L": 20, "M": 21, "N": 22,
    "O": 35, "P": 23, "Q": 24, "R": 25, "S": 26, "T": 27, "U": 28,
    "V": 29, "W": 32, "X": 30, "Y": 31, "Z": 33,
}
WEIGHTS = (1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1)

VALID_SCORE = 0.95
INVALID_CHECKSUM_SCORE = 0.1

_FULLMATCH_RE = re.compile(r"[A-Z][1289]\d{8}")
# 前後緊貼英數字視為更長 token 的子字串,不當成身分證
_SEARCH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][1289]\d{8}(?![A-Za-z0-9])")

_RECOGNIZER_NAME_KEY = getattr(RecognizerResult, "RECOGNIZER_NAME_KEY", "recognizer_name")


def is_valid_national_id(candidate: str) -> bool:
    """檢查碼驗證(身分證與新式居留證共用)。"""
    if not _FULLMATCH_RE.fullmatch(candidate):
        return False
    letter_value = LETTER_VALUES[candidate[0]]
    digits = [letter_value // 10, letter_value % 10, *(int(c) for c in candidate[1:])]
    total = sum(d * w for d, w in zip(digits, WEIGHTS))
    return total % 10 == 0


class TwNationalIdRecognizer(EntityRecognizer):
    ENTITY = "TW_NATIONAL_ID"

    def __init__(self, supported_language: str = "zh") -> None:
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=supported_language,
            name="TwNationalIdRecognizer",
        )

    def load(self) -> None:
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        results = []
        for match in _SEARCH_RE.finditer(text):
            score = (
                VALID_SCORE
                if is_valid_national_id(match.group())
                else INVALID_CHECKSUM_SCORE
            )
            results.append(
                RecognizerResult(
                    entity_type=self.ENTITY,
                    start=match.start(),
                    end=match.end(),
                    score=score,
                    recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
                )
            )
        return results
