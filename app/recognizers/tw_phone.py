"""F6:台灣手機(TW_MOBILE)與市話(TW_PHONE)recognizers。

手機:09 開頭共 10 碼,前後不得緊貼英數字。
市話:區碼 0[2-8](可含第三、四碼)+ 分隔符(- 或空白或括號)+ 6-8 碼號碼。
  無分隔符的裸市話(如 0227208889)給 0.45,低於引擎門檻 0.5,
  預設不遮罩——因與帳號/訂單編號難以區分,避免誤遮(README 已註記)。
  v1 不驗證各區碼對應的號碼長度。
"""

import re

from presidio_analyzer import EntityRecognizer, RecognizerResult

_RECOGNIZER_NAME_KEY = getattr(RecognizerResult, "RECOGNIZER_NAME_KEY", "recognizer_name")

MOBILE_SCORE = 0.85
LANDLINE_SEPARATED_SCORE = 0.75
LANDLINE_BARE_SCORE = 0.45

# 左右邊界對稱:緊貼英數字(不分左右)都視為更長 token 的子字串
_MOBILE_RE = re.compile(r"(?<![0-9A-Za-z])09\d{8}(?![0-9A-Za-z])")
# 連字號變體(明確列舉,非寬鬆匹配):0912-345-678、0912-345678
_MOBILE_HYPHEN_RE = re.compile(
    r"(?<![0-9A-Za-z-])09\d{2}-\d{3}-\d{3}(?![0-9A-Za-z-])"
    r"|(?<![0-9A-Za-z-])09\d{2}-\d{6}(?![0-9A-Za-z-])"
)

# 括號區碼:(02)2720-8889 / 分隔符區碼:02-27208889、037-123456、02 2720 8889
# 分隔符限空格/全形空格/連字號:換行不是市話分隔符——跨行拼接一律
# 交給影子映射路徑(那裡有關鍵詞防線),避免 \s 吃到換行繞過防線
_LANDLINE_SEPARATED_RE = re.compile(
    r"(?<![0-9A-Za-z(-])"
    r"(?:\(0[2-8]\d{0,2}\)|0[2-8]\d{0,2}[- 　])"
    r"\d{2,4}[- 　]?\d{4}"
    r"(?![0-9A-Za-z])"
)
# 裸市話(無分隔符):02+8碼 或 0X(X=3-8)+7-8碼
_LANDLINE_BARE_RE = re.compile(r"(?<![0-9A-Za-z(-])0[2-8]\d{7,8}(?![0-9])")


class TwMobileRecognizer(EntityRecognizer):
    ENTITY = "TW_MOBILE"

    def __init__(self, supported_language: str = "zh") -> None:
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=supported_language,
            name="TwMobileRecognizer",
        )

    def load(self) -> None:
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        matches = list(_MOBILE_RE.finditer(text)) + list(_MOBILE_HYPHEN_RE.finditer(text))
        return [
            RecognizerResult(
                entity_type=self.ENTITY,
                start=m.start(),
                end=m.end(),
                score=MOBILE_SCORE,
                recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
            )
            for m in matches
        ]


class TwLandlineRecognizer(EntityRecognizer):
    ENTITY = "TW_PHONE"

    def __init__(self, supported_language: str = "zh") -> None:
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=supported_language,
            name="TwLandlineRecognizer",
        )

    def load(self) -> None:
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        results = []
        seen_spans: set[tuple[int, int]] = set()
        for m in _LANDLINE_SEPARATED_RE.finditer(text):
            # 手機 09xx 不可誤入市話(區碼 regex 已排除 09,此處為雙保險)
            if m.group().replace("(", "").startswith("09"):
                continue
            seen_spans.add((m.start(), m.end()))
            results.append(
                RecognizerResult(
                    entity_type=self.ENTITY,
                    start=m.start(),
                    end=m.end(),
                    score=LANDLINE_SEPARATED_SCORE,
                    recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
                )
            )
        for m in _LANDLINE_BARE_RE.finditer(text):
            span = (m.start(), m.end())
            if any(s <= span[0] and span[1] <= e for s, e in seen_spans):
                continue
            results.append(
                RecognizerResult(
                    entity_type=self.ENTITY,
                    start=span[0],
                    end=span[1],
                    score=LANDLINE_BARE_SCORE,
                    recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
                )
            )
        return results
