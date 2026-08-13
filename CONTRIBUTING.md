# 貢獻指南 / Contributing

感謝你有興趣改進 TW-PII-Scrubber!

## 開發環境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/download_models.py   # CKIP 模型(約 400MB,僅此步需網路)
```

開發用 `requirements.txt`(寬鬆版本範圍);正式部署與可重現建置用
`requirements.lock`(pip-compile 產出,含所有相依的固定版本與 SHA-256):

```bash
pip install --require-hashes -r requirements.lock
# 更新鎖定檔:pip-compile --generate-hashes --output-file=requirements.lock requirements.txt
```

## 跑測試(PR 前必過)

```bash
python -m pytest tests/
```

測試涵蓋檢查碼演算法、座標對齊(全形/emoji/跨行)、遮罩格式、
檔案批次與 API。**任何觸及偵測/遮罩的變更都必須附測試**——這是
個資工具,遮錯位置等於洩漏。

## 原則(不可協商)

1. **任何資料不得離開本機**:執行期禁止外部 API、CDN、遙測。
2. **原文只讀**:偵測可以用影子文本,但所有遮罩必須以映回的座標
   作用在原文;座標對不上寧可整個請求失敗(fail-closed)。
3. 映射表(佔位符↔原值)僅存在記憶體,不落地、不進 ZIP、不進報告。
4. 前端單檔、零外部資源;伺服器回傳文字一律 escape 後渲染。
5. 新增 recognizer 請在 README 規則表補上規則與信心分層說明(合規稽核用)。

## 提交

- Conventional Commits(`feat:`/`fix:`/`docs:`…)。
- 模型能力邊界(哪些抓得到/抓不到)請以實測為準,並更新 README 已知限制。

## 授權

本專案為 GPL-3.0-or-later;提交貢獻即表示同意以相同授權發布。
