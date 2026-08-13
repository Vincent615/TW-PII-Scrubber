"""F3/F4:Presidio analyzer/anonymizer 組裝與脫敏管線。

設計要點:
- Presidio 預設不支援 zh:以 spacy.blank("zh") 包成 SpacyNlpEngine
  (spacy 本為 presidio 相依,零額外下載、完全離線);實際 NER 由
  CkipNerRecognizer 負責,spacy 只提供 tokenization 過場。
- 白名單(F9)採「包含式」比對:finding 若完整落在任一白名單詞
  於原文的出現範圍內即剔除(例:白名單「台新人壽」可同時剔除
  CKIP 只標到「台新」的 finding)。exact match 是其特例。
- 佔位符編號:presidio-anonymizer 由文末往前替換,故先按出現順序
  預先配號,anonymizer 的 custom lambda 只查表,保證 <PERSON_1> 是
  文中第一個出現的人名。
- findings 與 anonymizer 輸出 1:1 對應:先自行解決 span 重疊
  (分數高者優先,平手取較長),並關閉 merge_entities_with_spaces,
  數量不符即拋例外(fail-closed)。
"""

import threading
from collections import defaultdict
from typing import Optional

import spacy
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from app import config
from app.recognizers import (
    TwLandlineRecognizer,
    TwMobileRecognizer,
    TwNationalIdRecognizer,
    TwUbnRecognizer,
)
from app.recognizers.ckip_ner import CkipNerRecognizer
from app.recognizers.email_zh import ZhEmailRecognizer
from app.recognizers.financial import (
    AgentCodeRecognizer,
    BirthdayRecognizer,
    CreditCardRecognizer,
    TwBankAccountRecognizer,
    TwPolicyNoRecognizer,
)
from app.recognizers.tw_address import TwAddressRecognizer

_RECOGNIZER_NAME_KEY = getattr(RecognizerResult, "RECOGNIZER_NAME_KEY", "recognizer_name")

KNOWN_ENTITIES = set(config.DEFAULT_ENTITIES)

# placeholder 模式的標籤名(SPEC 範例:<PERSON_1>、<TW_ID_1>)
PLACEHOLDER_TAGS = {
    "PERSON": "PERSON",
    "TW_NATIONAL_ID": "TW_ID",
    "TW_MOBILE": "MOBILE",
    "TW_PHONE": "PHONE",
    "TW_UBN": "UBN",
    "EMAIL_ADDRESS": "EMAIL",
    "ORG": "ORG",
    "LOC": "LOC",
    "BIRTHDAY": "BIRTHDAY",
    "TW_POLICY_NO": "POLICY",
    "CREDIT_CARD": "CARD",
    "AGENT_CODE": "AGENT",
    "TW_BANK_ACCOUNT": "ACCOUNT",
}


class TextTooLongError(ValueError):
    pass


class EntitySelectionError(ValueError):
    """entities 明確給了但沒有任何有效類型:寧可報錯,不可默默全開。"""


class BatchTimeoutError(RuntimeError):
    pass


# ---------- 跨行/空白截斷:影子映射 ----------

_ASCII_ALNUM = frozenset(
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
# 可合併的空白字元:半形/全形空白與換行。
# tab 刻意排除:tab 是表格(如 Excel 複製)的欄位分隔,合併會跨欄拼接。
_JOINABLE_WHITESPACE = " 　\r\n"
# 合併邊界除英數外,亦接受 email/帳號常見符號(qwe@↵gmail↵.com 斷在
# @ 或 . 旁);風險有限:這些符號不影響身分證/手機/統編的 lookaround
_JOIN_EXTRA_BOUNDARY = frozenset("@._")

# 市話無檢查碼且樣式較寬鬆,跨行拼接須有電話相關上下文才視為有效
_CROSSLINE_PHONE_KEYWORDS = (
    "手機", "電話", "門號", "聯絡", "致電", "回電", "撥", "分機", "簡訊",
)


def build_shadow_text(text: str) -> tuple[str, list[int]]:
    """建立影子文本與座標對映(shadow index → original index)。

    移除規則(可稽核),對每一段連續空白區段(僅含半形/全形空白與
    換行;tab 不參與):
    1. 前鄰字元為 ASCII 英數,或為「緊跟在英數後的連字號 -」
       (支援 0912-↵345678 的連字號換行);後鄰字元為 ASCII 英數。
    2. 區段含換行時:換行至多 1 個(\\r\\n 算 1 個)且總長 ≤ 3
       (涵蓋行尾空格+換行、換行+行首縮排);
       純空白無換行時:長度必須為 1(兩格以上視為表格對齊,不合併)。
    空行(兩個換行)不合併——段落結構為有意分隔。
    CJK 字元不受影響,對話內容與座標皆不變動。
    """
    n = len(text)
    removed = [False] * n
    i = 0
    while i < n:
        if text[i] in _JOINABLE_WHITESPACE:
            j = i
            newline_count = 0
            while j < n and text[j] in _JOINABLE_WHITESPACE:
                if text[j] == "\n":
                    newline_count += 1
                elif text[j] == "\r" and not (j + 1 < n and text[j + 1] == "\n"):
                    newline_count += 1  # 獨立 \r 也算一個換行
                j += 1
            run_len = j - i
            prev_ok = i > 0 and (
                text[i - 1] in _ASCII_ALNUM
                or text[i - 1] in _JOIN_EXTRA_BOUNDARY
                or (text[i - 1] == "-" and i > 1 and text[i - 2] in _ASCII_ALNUM)
            )
            next_ok = j < n and (
                text[j] in _ASCII_ALNUM or text[j] in _JOIN_EXTRA_BOUNDARY
            )
            length_ok = (newline_count == 1 and run_len <= 3) or (
                newline_count == 0 and run_len == 1
            )
            if prev_ok and next_ok and length_ok:
                for k in range(i, j):
                    removed[k] = True
            i = j
        else:
            i += 1
    shadow_chars: list[str] = []
    s2o: list[int] = []
    for idx, ch in enumerate(text):
        if not removed[idx]:
            shadow_chars.append(ch)
            s2o.append(idx)
    return "".join(shadow_chars), s2o


def _canonical_value(value: str) -> str:
    """跨行值的正規形(移除可合併空白),供佔位符同值判定與 mapping 使用。"""
    return "".join(c for c in value if c not in _JOINABLE_WHITESPACE)


def _filter_crossline(text: str, results: list[RecognizerResult]) -> list[RecognizerResult]:
    """跨行拼接防線:市話無檢查碼且樣式較寬鬆(區碼+6-8 碼),
    拼接命中須在原文 ±15 字內有電話相關關鍵詞,否則剔除。

    手機不設關鍵詞門檻:09 開頭恰 10 碼的樣式特異度高,且依鐵律
    「寧可多遮、不可外洩」,拼接誤遮的代價(明細表可見、可白名單)
    遠小於漏遮的代價(2026-08-13 依實測回饋調整)。
    身分證/統編由檢查碼把關、Email 由 @ 與網域結構把關。"""
    kept = []
    for r in results:
        raw = text[r.start : r.end]
        crossed = any(c in _JOINABLE_WHITESPACE for c in raw)
        if crossed and r.entity_type == "TW_PHONE":
            window = text[max(0, r.start - 15) : min(len(text), r.end + 15)]
            if not any(kw in window for kw in _CROSSLINE_PHONE_KEYWORDS):
                continue
        kept.append(r)
    return kept


class _PlaceholderAllocator:
    """佔位符配號:同值同編號;可跨多段文字(F7 檔案批次)共用。"""

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._by_value: dict[str, dict[str, str]] = defaultdict(dict)
        self.mapping: dict[str, str] = {}

    def get(self, entity_type: str, value: str) -> str:
        tag = PLACEHOLDER_TAGS.get(entity_type, entity_type)
        if value not in self._by_value[tag]:
            self._counters[tag] += 1
            placeholder = f"<{tag}_{self._counters[tag]}>"
            self._by_value[tag][value] = placeholder
            self.mapping[placeholder] = value
        return self._by_value[tag][value]


class BlankChineseNlpEngine(SpacyNlpEngine):
    """spacy.blank("zh"):純 tokenizer、無 NER、無需下載模型。"""

    def __init__(self) -> None:
        super().__init__(models=[{"lang_code": "zh", "model_name": "blank:zh"}])
        self.load()

    def load(self) -> None:
        self.nlp = {"zh": spacy.blank("zh")}


# ---------- 遮罩規則(mode=mask;README 有對照說明) ----------

def _mask_keep_first(value: str) -> str:
    """姓名/組織/地名:保留首字,其餘改「○」(王小明→王○○)。"""
    return value[0] + "○" * (len(value) - 1) if value else value


def _mask_alnum_positional(value: str, keep_head: int, keep_tail: int) -> str:
    """英數字元「前 keep_head、後 keep_tail 保留,中間 *」;
    非英數字元(斷行/空白/連字號)原位保留——跨行值的版面不被破壞
    (A12345\\n6789 → A1****\\n**89)。英數不足時全部遮蔽。

    fail-safe:以 Unicode isalnum() 判定可遮字元——regex 的 \\d 會
    命中全形數字(０-９),遮罩範圍必須至少涵蓋偵測範圍,否則會出現
    「有偵測、輸出卻保留原值」的洩漏。"""
    sig = [i for i, c in enumerate(value) if c.isalnum()]
    if len(sig) <= keep_head + keep_tail:
        keep: set[int] = set()
    else:
        keep = set(sig[:keep_head]) | set(sig[len(sig) - keep_tail :])
    sig_set = set(sig)
    return "".join(
        "*" if (i in sig_set and i not in keep) else c for i, c in enumerate(value)
    )


def _mask_national_id(value: str) -> str:
    """保留首尾各 2 碼,中間 *(A123456789→A1******89)。"""
    return _mask_alnum_positional(value, 2, 2)


def _mask_mobile(value: str) -> str:
    """中間 4 碼 *(0912345678→091****678);分隔符/斷行原位保留
    (0912-345-678→091*-***-678)。非 10 碼數字時退回前 2 後 2 規則。"""
    digit_positions = [i for i, c in enumerate(value) if c.isdigit()]
    if len(digit_positions) != 10:
        return _mask_alnum_positional(value, 2, 2)
    to_mask = set(digit_positions[3:7])
    return "".join("*" if i in to_mask else c for i, c in enumerate(value))


def _mask_phone(value: str) -> str:
    """保留區碼(前 2 位數字)與末 2 位數字,其餘數字改 *,分隔符保留。"""
    digit_positions = [i for i, c in enumerate(value) if c.isdigit()]
    keep = set(digit_positions[:2] + digit_positions[-2:])
    return "".join(
        "*" if (c.isdigit() and i not in keep) else c for i, c in enumerate(value)
    )


def _mask_email(value: str) -> str:
    """保留帳號首字元與網域(test@example.com→t***@example.com)。"""
    local, _, domain = value.partition("@")
    if not domain:
        return "***"
    return (local[0] if local else "") + "***@" + domain


def _mask_birthday(value: str) -> str:
    """保留民國年碼,遮月日 4 碼(1000101→100****)。"""
    digit_positions = [i for i, c in enumerate(value) if c.isdigit()]
    to_mask = set(digit_positions[-4:])
    return "".join("*" if i in to_mask else c for i, c in enumerate(value))


def _mask_keep_last4(value: str) -> str:
    """僅保留末 4 碼數字(信用卡/存款帳號業界慣例),分隔符原位保留。"""
    digit_positions = [i for i, c in enumerate(value) if c.isdigit()]
    keep = set(digit_positions[-4:])
    return "".join(
        "*" if (c.isdigit() and i not in keep) else c for i, c in enumerate(value)
    )


def _mask_digits_only(value: str) -> str:
    """數字全遮、其他字元保留(客服代號:代號11→代號**)。"""
    return "".join("*" if c.isdigit() else c for c in value)


_MASK_FUNCTIONS = {
    "PERSON": _mask_keep_first,
    "ORG": _mask_keep_first,
    "LOC": _mask_keep_first,
    "TW_NATIONAL_ID": _mask_national_id,
    "TW_MOBILE": _mask_mobile,
    "TW_PHONE": _mask_phone,
    "TW_UBN": _mask_national_id,  # 前 2 後 2 保留,同身分證規則
    "EMAIL_ADDRESS": _mask_email,
    "BIRTHDAY": _mask_birthday,
    "TW_POLICY_NO": _mask_national_id,  # 前 2 後 2 保留
    "CREDIT_CARD": _mask_keep_last4,
    "AGENT_CODE": _mask_digits_only,
    "TW_BANK_ACCOUNT": _mask_keep_last4,
}


def mask_value(entity_type: str, value: str) -> str:
    fn = _MASK_FUNCTIONS.get(entity_type)
    return fn(value) if fn else "*" * len(value)


def _filter_whitelisted(
    text: str, results: list[RecognizerResult], whitelist: list[str]
) -> list[RecognizerResult]:
    """F9:剔除完整落在白名單詞出現範圍內的 finding(包含式比對)。"""
    if not whitelist:
        return results
    protected: list[tuple[int, int]] = []
    for term in whitelist:
        pos = text.find(term)
        while pos != -1:
            protected.append((pos, pos + len(term)))
            pos = text.find(term, pos + 1)
    return [
        r
        for r in results
        if not any(ws <= r.start and r.end <= we for ws, we in protected)
    ]


def _resolve_overlaps(results: list[RecognizerResult]) -> list[RecognizerResult]:
    """重疊 span 只留一個:分數高者優先,平手取較長、再取較早。"""
    ordered = sorted(results, key=lambda r: (-r.score, -(r.end - r.start), r.start))
    kept: list[RecognizerResult] = []
    for r in ordered:
        if all(r.end <= k.start or k.end <= r.start for k in kept):
            kept.append(r)
    kept.sort(key=lambda r: (r.start, r.end))
    return kept


class ScrubEngine:
    def __init__(
        self,
        use_ckip: bool = True,
        whitelist_path=config.WHITELIST_PATH,
        ckip_model_path=None,
    ) -> None:
        registry = RecognizerRegistry(supported_languages=[config.LANGUAGE])
        self.ckip: Optional[CkipNerRecognizer] = None
        recognizers = [
            TwNationalIdRecognizer(),
            TwMobileRecognizer(),
            TwLandlineRecognizer(),
            TwUbnRecognizer(),
            # 不用 Presidio 內建 EmailRecognizer:其 \b 判界在中文緊鄰時失效
            ZhEmailRecognizer(),
            BirthdayRecognizer(),
            TwPolicyNoRecognizer(),
            CreditCardRecognizer(),
            AgentCodeRecognizer(),
            TwBankAccountRecognizer(),
            # 完整地址(路段巷弄號樓)結構規則,補 CKIP 只標行政區的缺口
            TwAddressRecognizer(),
        ]
        # 規則型 recognizers 另存一份:影子文本會移除空白分隔符,
        # 「02 2720 8889」這類原文樣式只有直接對原文比對才看得到,
        # 故偵測採雙軌(影子一次 + 原文規則一次)後合併
        self._pattern_recognizers = list(recognizers)
        if use_ckip:
            self.ckip = CkipNerRecognizer(model_path=ckip_model_path)
            recognizers.append(self.ckip)
        for rec in recognizers:
            registry.add_recognizer(rec)

        self.analyzer = AnalyzerEngine(
            nlp_engine=BlankChineseNlpEngine(),
            registry=registry,
            supported_languages=[config.LANGUAGE],
            default_score_threshold=config.SCORE_THRESHOLD,
        )
        self.anonymizer = AnonymizerEngine()
        self.whitelist_path = whitelist_path
        # 序列化脫敏請求:兩個分頁同時送出時,推論不交錯(記憶體與
        # torch 執行緒安全的雙保險;本機單人工具,序列化代價可忽略)
        self._lock = threading.Lock()

    def warmup(self) -> None:
        """啟動時載入 CKIP 模型(數十秒),之後常駐記憶體。"""
        if self.ckip is not None:
            self.ckip.load()

    def load_whitelist(self) -> list[str]:
        """每次請求讀取白名單(可熱編輯);# 開頭視為註解。"""
        try:
            lines = self.whitelist_path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return []
        return [w for w in (line.strip() for line in lines) if w and not w.startswith("#")]

    def scrub(self, text: str, mode: str = "mask", entities: Optional[list[str]] = None) -> dict:
        allocator = _PlaceholderAllocator()
        response = self._scrub_one(text, mode, entities, allocator)
        if mode == "placeholder":
            response["mapping"] = allocator.mapping
        return response

    def scrub_batch(
        self,
        texts: list[str],
        mode: str = "mask",
        entities: Optional[list[str]] = None,
        time_budget_seconds: float = config.BATCH_TIME_BUDGET_SECONDS,
    ) -> dict:
        """F7 檔案批次:多段文字(儲存格)共用佔位符編號與 mapping。

        逐段之間檢查累計耗時(合作式),超出預算即中止,不回傳部分結果。
        """
        import time

        deadline = time.monotonic() + time_budget_seconds
        allocator = _PlaceholderAllocator()
        results = []
        total_stats: dict[str, int] = defaultdict(int)
        for text in texts:
            if time.monotonic() > deadline:
                raise BatchTimeoutError("檔案處理逾時,請縮小檔案或減少 NER 欄位")
            one = self._scrub_one(text, mode, entities, allocator)
            # 完成後再檢查一次:最後一格不得無上限超時仍回傳成功
            if time.monotonic() > deadline:
                raise BatchTimeoutError("檔案處理逾時,請縮小檔案或減少 NER 欄位")
            for entity_type, count in one["stats"].items():
                total_stats[entity_type] += count
            results.append(one)
        response: dict = {"results": results, "stats": dict(total_stats)}
        if mode == "placeholder":
            response["mapping"] = allocator.mapping
        return response

    def _scrub_one(
        self,
        text: str,
        mode: str,
        entities: Optional[list[str]],
        allocator: _PlaceholderAllocator,
    ) -> dict:
        with self._lock:
            return self._scrub_one_locked(text, mode, entities, allocator)

    def _scrub_one_locked(
        self,
        text: str,
        mode: str,
        entities: Optional[list[str]],
        allocator: _PlaceholderAllocator,
    ) -> dict:
        if len(text) > config.MAX_TEXT_LENGTH:
            raise TextTooLongError(
                f"請分段處理(單次上限 {config.MAX_TEXT_LENGTH:,} 字)"
            )
        if mode not in ("mask", "placeholder"):
            raise ValueError(f"未知模式:{mode}")
        # 僅 None 代表「使用預設全開」;空陣列或全為未知值必須報錯——
        # 否則「取消全部勾選」語意會被靜默翻轉成「全部偵測」
        if entities is None:
            selected = list(config.DEFAULT_ENTITIES)
        else:
            selected = [e for e in entities if e in KNOWN_ENTITIES]
            if not selected:
                raise EntitySelectionError("entities 未包含任何有效的偵測類型")

        # 影子映射:偵測跑在影子文本(截斷號碼已接回),
        # 座標映回原文後,所有遮罩/替換都作用在「原文」上——原文零修改
        if config.JOIN_BROKEN_NUMBERS:
            shadow, s2o = build_shadow_text(text)
        else:
            shadow, s2o = text, None
        results = self.analyzer.analyze(
            text=shadow,
            language=config.LANGUAGE,
            entities=selected,
        )
        if s2o is not None and shadow != text:
            for r in results:
                r.start, r.end = s2o[r.start], s2o[r.end - 1] + 1
            results = _filter_crossline(text, results)
            # 雙軌:規則型 recognizers 再對「原文」跑一次——影子接合會
            # 破壞空白分隔樣式(02 2720 8889),只有原文能命中分隔式規則。
            # 重疊由 _resolve_overlaps 以高分優先去重。
            for rec in self._pattern_recognizers:
                for r in rec.analyze(text, selected):
                    if r.score >= config.SCORE_THRESHOLD:
                        results.append(r)
        results = _filter_whitelisted(text, results, self.load_whitelist())
        results = _resolve_overlaps(results)

        # 按出現順序預先決定替換字串(佔位符同值同編號,配號由 allocator 統籌)
        replacement_lookup: dict[tuple[str, str], str] = {}
        for r in results:
            value = text[r.start : r.end]
            if mode == "mask":
                replacement_lookup[(r.entity_type, value)] = mask_value(r.entity_type, value)
            else:
                # 佔位符以正規形配號:同一號碼不論有無截斷都拿同一編號,
                # mapping 中的原值也是乾淨的正規形
                replacement_lookup[(r.entity_type, value)] = allocator.get(
                    r.entity_type, _canonical_value(value)
                )

        def _make_operator(entity_type: str) -> OperatorConfig:
            return OperatorConfig(
                "custom",
                {"lambda": lambda v, et=entity_type: replacement_lookup[(et, v)]},
            )

        operators = {et: _make_operator(et) for et in {r.entity_type for r in results}}
        anonymized = self.anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators,
            merge_entities_with_spaces=False,
        )
        items = sorted(anonymized.items, key=lambda item: (item.start, item.end))
        if len(items) != len(results):
            raise RuntimeError(
                f"脫敏結果對應數量不符(findings {len(results)} vs 替換 {len(items)}),"
                "為避免輸出錯誤結果已中止"
            )

        findings = []
        stats: dict[str, int] = defaultdict(int)
        for r, item in zip(results, items):
            value = text[r.start : r.end]
            metadata = r.recognition_metadata or {}
            findings.append(
                {
                    "entity_type": r.entity_type,
                    "original_masked": mask_value(r.entity_type, value),
                    "start": r.start,
                    "end": r.end,
                    "score": round(r.score, 3),
                    "recognizer": metadata.get(_RECOGNIZER_NAME_KEY, "unknown"),
                    "replacement": item.text,
                    # 額外欄位(SPEC 之外,供前端在脫敏結果側高亮):
                    "scrubbed_start": item.start,
                    "scrubbed_end": item.end,
                }
            )
            stats[r.entity_type] += 1

        return {
            "scrubbed_text": anonymized.text,
            "findings": findings,
            "stats": dict(stats),
        }
