"""台灣地址 recognizer(entity:LOC,與 CKIP 地名共用類別)。

CKIP 只會標到行政區層級(台北市/大安區),完整地址的「路段巷弄號樓」
會漏。本 recognizer 以結構規則補齊:

    [縣市]? [鄉鎮市區]? 路名(路|街|大道) [段]? [巷]? [弄]? 號 [之]? [樓]? [室]?

「號」為必要錨點,路名與號之間只允許結構化元件(段/巷/弄),
一般敘述(「道路施工3號出口」)不會誤中。已知取捨:路名前綴最長取
4 個中文字,偶爾會多吃到 1-2 個前導字(「在中山路5號」的「在」)——
方向是多遮不漏遮,README 已註記。
"""

import re

from presidio_analyzer import EntityRecognizer, RecognizerResult

_RECOGNIZER_NAME_KEY = getattr(RecognizerResult, "RECOGNIZER_NAME_KEY", "recognizer_name")

ADDRESS_SCORE = 0.9

_ADDRESS_RE = re.compile(
    r"(?:[一-鿿]{1,3}(?:市|縣))?"          # 縣市(可省)
    r"(?:[一-鿿]{1,3}(?:區|鄉|鎮|市))?"    # 鄉鎮市區(可省)
    r"[一-鿿]{1,4}(?:路|街|大道)"           # 路名
    r"(?:[一二三四五六七八九十\d]{1,3}段)?"
    r"(?:\d{1,4}巷)?"
    r"(?:\d{1,4}弄)?"
    r"\d{1,5}(?:之\d{1,3})?號"                      # 門牌號(必要錨點)
    r"(?:之\d{1,3})?"
    r"(?:[Bb]?\d{1,3}樓(?:之\d{1,3})?)?"
    r"(?:\d{1,4}室)?"
)


class TwAddressRecognizer(EntityRecognizer):
    ENTITY = "LOC"

    def __init__(self, supported_language: str = "zh") -> None:
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=supported_language,
            name="TwAddressRecognizer",
        )

    def load(self) -> None:
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        return [
            RecognizerResult(
                entity_type=self.ENTITY,
                start=m.start(),
                end=m.end(),
                score=ADDRESS_SCORE,
                recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
            )
            for m in _ADDRESS_RE.finditer(text)
        ]
