# 第三方元件與授權聲明 / Third-Party Notices

本專案(TW-PII-Scrubber)以 **GPL-3.0-or-later**(見 `LICENSE`)發布。
授權選擇的主因:核心相依 `ckip-transformers` 與其模型為 GPL-3.0
(copyleft),本專案作為其衍生使用,採相容之 GPL 授權以確保合規。

## NLP 模型(不隨本專案散布)

| 元件 | 授權 | 說明 |
|------|------|------|
| [ckiplab/bert-base-chinese-ner](https://huggingface.co/ckiplab/bert-base-chinese-ner) | GPL-3.0 | 繁中命名實體辨識模型,by CKIP Lab(中央研究院資訊科學研究所)。**本倉庫不含模型權重**;使用者執行 `scripts/download_models.py` 自行從 Hugging Face 下載,受該模型自身授權約束。**綠色版可攜包例外**:其內含模型權重,散布聲明見包內 `PORTABLE_NOTICE.md`。 |

引用(Citation):CKIP Transformers — Mu Yang, CKIP Lab, Academia Sinica。
專案:<https://github.com/ckiplab/ckip-transformers>

## Python 套件

| 套件 | 授權 |
|------|------|
| [ckip-transformers](https://github.com/ckiplab/ckip-transformers) | GPL-3.0 |
| [presidio-analyzer / presidio-anonymizer](https://github.com/microsoft/presidio)(Microsoft) | MIT |
| [transformers](https://github.com/huggingface/transformers)(Hugging Face) | Apache-2.0 |
| [torch](https://github.com/pytorch/pytorch)(PyTorch) | BSD-3-Clause |
| [spaCy](https://github.com/explosion/spaCy) | MIT |
| [FastAPI](https://github.com/fastapi/fastapi) | MIT |
| [uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause |
| [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) | MIT |
| [anyio](https://github.com/agronholm/anyio) | MIT |
| [huggingface-hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 |
| [pydantic](https://github.com/pydantic/pydantic) | MIT |
| [Starlette](https://github.com/encode/starlette) | BSD-3-Clause |

## 演算法與測試資料參考

- [enylin/taiwan-id-validator](https://github.com/enylin/taiwan-id-validator)(MIT):
  台灣身分證/新式居留證/統一編號檢查碼演算法之參考實作;本專案的檢查碼
  對照表已逐字比對其原始碼驗證,部分測試 fixtures 取自其公開測試資料
  (皆為演算法測試值,非真實個資)。

## 前端

`static/index.html` 為本專案自行撰寫之單檔 vanilla JS/CSS,無任何外部
資源或第三方程式碼(離線環境鐵律)。
