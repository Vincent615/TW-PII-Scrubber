"""全域設定。所有數值集中此處,方便合規稽核。"""

from pathlib import Path

# --- 伺服器(鐵律:只綁本機) ---
HOST = "127.0.0.1"
PORT = 7860

# --- 脫敏引擎 ---
LANGUAGE = "zh"
# findings 低於此分數即不回傳、不脫敏(檢查碼錯誤的候選字串分數為 0.1)
SCORE_THRESHOLD = 0.5
# 單次請求文字上限(字元)
MAX_TEXT_LENGTH = 50_000

# --- CKIP 模型 ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
CKIP_MODEL_NAME = "ckiplab/bert-base-chinese-ner"
CKIP_LOCAL_DIR = MODELS_DIR / "ckiplab" / "bert-base-chinese-ner"
# 合作式逾時:分段推論,段與段之間檢查累計耗時
CKIP_TIMEOUT_SECONDS = 60
# F7 檔案批次總時間預算(儲存格之間檢查)
BATCH_TIME_BUDGET_SECONDS = 300

# --- 批次 ZIP 下載 ---
MAX_ZIP_ENTRIES = 40
MAX_ZIP_TOTAL_BYTES = 60 * 1024 * 1024

# --- 本機 API 防護 ---
# 只接受來自本機 GUI 的請求:惡意網頁雖讀不到回應(同源政策),
# 但可跨站送出 multipart(simple request 免預檢)觸發本機高耗能推論,
# 或以 DNS rebinding 手法讀取回應。驗 Origin/Host 成本低、收斂此面。
ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

# --- 請求體上限(middleware 依 Content-Length 先擋,避免大量記憶體配置後才拒絕)---
MAX_REQUEST_BYTES_DEFAULT = 16 * 1024 * 1024   # 一般端點(單檔上傳 10MB + multipart 開銷)
MAX_REQUEST_BYTES_ZIP = 96 * 1024 * 1024       # bundle-zip(60MB 內容的 Base64 + JSON 開銷)

# --- XLSX 解析防護(zip bomb / 超大表格)---
MAX_XLSX_ZIP_ENTRIES = 2000
MAX_XLSX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_XLSX_ROWS = 20_000
MAX_XLSX_COLS = 500

# --- 跨行/空白截斷(影子映射) ---
# 數字或英數序列被「單一」空白/斷行切開時(如 A12345\n6789),
# 以影子文本(移除該空白)偵測,再映回原文座標遮罩——原文零修改。
# 防線:僅跨單一空白單元(空行不合併)、身分證/統編靠檢查碼把關、
# 手機/市話(無檢查碼)須在 ±15 字內有電話相關關鍵詞。
# 設 False 可完全停用,回到不支援截斷的行為。
JOIN_BROKEN_NUMBERS = True

# --- 白名單 ---
WHITELIST_PATH = PROJECT_ROOT / "whitelist.txt"

# --- 預設偵測的 entity 類型 ---
DEFAULT_ENTITIES = [
    "PERSON",
    "TW_NATIONAL_ID",
    "TW_MOBILE",
    "TW_PHONE",
    "TW_UBN",
    "EMAIL_ADDRESS",
    "ORG",
    "LOC",
    "BIRTHDAY",
    "TW_POLICY_NO",
    "CREDIT_CARD",
    "AGENT_CODE",
    "TW_BANK_ACCOUNT",
]
