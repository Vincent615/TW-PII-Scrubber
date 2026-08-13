"""中文語境 Email recognizer(entity:EMAIL_ADDRESS)。

Presidio 內建 EmailRecognizer 以 \\b 判界,但 Python regex 的 \\w 包含
中文字元——email 緊貼中文(「信箱qwe@gmail.com」)時沒有字邊界,
完全偵測不到。本 recognizer 改用明確 lookaround:只排除「更長英數
token 的子字串」,中文字、全形標點緊鄰皆可命中。
"""

import re

from presidio_analyzer import EntityRecognizer, RecognizerResult

_RECOGNIZER_NAME_KEY = getattr(RecognizerResult, "RECOGNIZER_NAME_KEY", "recognizer_name")

EMAIL_SCORE = 1.0

_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}"
    r"(?![A-Za-z0-9-])"
)


class ZhEmailRecognizer(EntityRecognizer):
    ENTITY = "EMAIL_ADDRESS"

    def __init__(self, supported_language: str = "zh") -> None:
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=supported_language,
            name="ZhEmailRecognizer",
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
                score=EMAIL_SCORE,
                recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
            )
            for m in _EMAIL_RE.finditer(text)
        ]
