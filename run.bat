@echo off
rem 一鍵啟動(Windows)。需先依 README 完成安裝。
rem chcp 65001:本檔為 UTF-8,切換主控台編碼避免中文亂碼(預設 cp950)
chcp 65001 >nul
cd /d %~dp0
set URL=http://127.0.0.1:7860

rem 優先使用專案內的虛擬環境(未啟用 venv 也能正確執行)
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

echo TW-PII-Scrubber 啟動中... %URL%
echo (首次啟動需載入模型,約數十秒)

rem 背景輪詢健康檢查,模型載入完成才開瀏覽器;curl 為 Windows 10 內建,
rem 若不可用則於輪詢結束後直接開啟
start "" /min cmd /c "(for /l %%i in (1,1,60) do (curl -s %URL%/api/health >nul 2>&1 && (start "" %URL% & exit) || timeout /t 2 >nul)) & start "" %URL%"

%PY% -m uvicorn app.main:app --host 127.0.0.1 --port 7860
