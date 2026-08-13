"""金融/客服場景的五種 recognizers。

- BIRTHDAY        生日(民國年月日,6-7 碼數字,月日合法性驗證)
- TW_POLICY_NO    保單號碼(10 碼:純數字或 2-5 碼英文開頭)
- CREDIT_CARD     信用卡號(16 碼,Luhn 檢查碼;含 4-4-4-4 連字號變體)
- AGENT_CODE      客服人員代號(字面「代號」+2-3 碼數字)
- TW_BANK_ACCOUNT 存款帳號(銀行 13 碼/郵局 14 碼)

信心分層原則(README 有對照):有檢查碼者靠檢查碼(信用卡);
無檢查碼者依樣式鑑別度與上下文關鍵詞分層,容易撞常見數字的
(生日 6-7 碼、保單純數字 10 碼)裸值低於門檻預設不遮。
"""

import datetime
import re

from presidio_analyzer import EntityRecognizer, RecognizerResult

_RECOGNIZER_NAME_KEY = getattr(RecognizerResult, "RECOGNIZER_NAME_KEY", "recognizer_name")


class _SimpleRecognizer(EntityRecognizer):
    """regex + 上下文關鍵詞信心分層的共同骨架。"""

    ENTITY = ""
    NAME = ""

    def __init__(self, supported_language: str = "zh") -> None:
        super().__init__(
            supported_entities=[self.ENTITY],
            supported_language=supported_language,
            name=self.NAME,
        )

    def load(self) -> None:
        pass

    @staticmethod
    def _has_context(text, start, end, keywords, before=15, after=8) -> bool:
        window = text[max(0, start - before) : min(len(text), end + after)]
        return any(kw in window for kw in keywords)

    def _make(self, start: int, end: int, score: float) -> RecognizerResult:
        return RecognizerResult(
            entity_type=self.ENTITY,
            start=start,
            end=end,
            score=score,
            recognition_metadata={_RECOGNIZER_NAME_KEY: self.name},
        )


# ---------- 生日(民國年月日) ----------

# 年:2 碼(01-99)或 3 碼(100-129);月 01-12;日 01-31
_BIRTHDAY_RE = re.compile(
    r"(?<!\d)"
    r"(?:1[0-2]\d|0[1-9]|[1-9]\d)"
    r"(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])"
    r"(?!\d)"
)
BIRTHDAY_CONTEXT = ("生日", "出生", "生於")
BIRTHDAY_CONTEXT_SCORE = 0.95
BIRTHDAY_BARE_SCORE = 0.45  # 6-7 碼數字太常見,裸值低於門檻不遮


def _is_valid_roc_date(value: str) -> bool:
    """完整曆法驗證(990229、990431 這類不存在的日期要排除)。"""
    year, month, day = int(value[:-4]), int(value[-4:-2]), int(value[-2:])
    try:
        datetime.date(year + 1911, month, day)
    except ValueError:
        return False
    return True


class BirthdayRecognizer(_SimpleRecognizer):
    ENTITY = "BIRTHDAY"
    NAME = "BirthdayRecognizer"

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        results = []
        for m in _BIRTHDAY_RE.finditer(text):
            if not _is_valid_roc_date(m.group()):
                continue
            score = (
                BIRTHDAY_CONTEXT_SCORE
                if self._has_context(text, m.start(), m.end(), BIRTHDAY_CONTEXT)
                else BIRTHDAY_BARE_SCORE
            )
            results.append(self._make(m.start(), m.end(), score))
        return results


# ---------- 保單號碼 ----------

_POLICY_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:\d{10}|[A-Z]{2}\d{8}|[A-Z]{3}\d{7}|[A-Z]{4}\d{6}|[A-Z]{5}\d{5})"
    r"(?![A-Za-z0-9])"
)
POLICY_CONTEXT = ("保單", "保號", "契約", "保件")
POLICY_CONTEXT_SCORE = 0.95
POLICY_LETTER_BARE_SCORE = 0.7   # 英文開頭 10 碼鑑別度高,裸值也遮
POLICY_DIGIT_BARE_SCORE = 0.45   # 純數字 10 碼會撞電話/金額,裸值不遮


class TwPolicyNoRecognizer(_SimpleRecognizer):
    ENTITY = "TW_POLICY_NO"
    NAME = "TwPolicyNoRecognizer"

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        results = []
        for m in _POLICY_RE.finditer(text):
            if self._has_context(text, m.start(), m.end(), POLICY_CONTEXT):
                score = POLICY_CONTEXT_SCORE
            elif m.group()[0].isdigit():
                score = POLICY_DIGIT_BARE_SCORE
            else:
                score = POLICY_LETTER_BARE_SCORE
            results.append(self._make(m.start(), m.end(), score))
        return results


# ---------- 信用卡號 ----------

_CARD_PLAIN_RE = re.compile(r"(?<![0-9A-Za-z-])\d{16}(?![0-9A-Za-z-])")
_CARD_SEP_RE = re.compile(r"(?<![0-9A-Za-z-])\d{4}-\d{4}-\d{4}-\d{4}(?![0-9A-Za-z-])")
CARD_VALID_SCORE = 0.95
CARD_INVALID_SCORE = 0.1


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class CreditCardRecognizer(_SimpleRecognizer):
    ENTITY = "CREDIT_CARD"
    NAME = "CreditCardRecognizer"

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        results = []
        for pattern in (_CARD_PLAIN_RE, _CARD_SEP_RE):
            for m in pattern.finditer(text):
                digits = m.group().replace("-", "")
                score = CARD_VALID_SCORE if luhn_ok(digits) else CARD_INVALID_SCORE
                results.append(self._make(m.start(), m.end(), score))
        return results


# ---------- 客服人員代號 ----------

_AGENT_RE = re.compile(r"代號[：:]?\s?\d{2,3}(?!\d)")
AGENT_SCORE = 0.9  # 字面標籤,鑑別度高


class AgentCodeRecognizer(_SimpleRecognizer):
    ENTITY = "AGENT_CODE"
    NAME = "AgentCodeRecognizer"

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        return [
            self._make(m.start(), m.end(), AGENT_SCORE)
            for m in _AGENT_RE.finditer(text)
        ]


# ---------- 存款帳號 ----------

_ACCOUNT_RE = re.compile(r"(?<![0-9A-Za-z])\d{13,14}(?![0-9A-Za-z])")
ACCOUNT_CONTEXT = ("帳號", "帳戶", "匯款", "轉帳", "匯入", "郵局")
ACCOUNT_CONTEXT_SCORE = 0.95
ACCOUNT_BARE_SCORE = 0.75  # 13-14 碼長串在客服語境幾乎必是帳號,寧可多遮


class TwBankAccountRecognizer(_SimpleRecognizer):
    ENTITY = "TW_BANK_ACCOUNT"
    NAME = "TwBankAccountRecognizer"

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.ENTITY not in entities:
            return []
        results = []
        for m in _ACCOUNT_RE.finditer(text):
            score = (
                ACCOUNT_CONTEXT_SCORE
                if self._has_context(text, m.start(), m.end(), ACCOUNT_CONTEXT)
                else ACCOUNT_BARE_SCORE
            )
            results.append(self._make(m.start(), m.end(), score))
        return results
