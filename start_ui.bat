@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 找不到 .venv，請先執行 create_venv.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" app.py
rem 正常結束(網頁關閉)時自動關閉視窗 出錯時保留視窗以便查看訊息
if errorlevel 1 pause
