@echo off
chcp 65001 >nul
cd /d "D:\InvoiceTool\shortage_app"

REM Start the web server with pythonw (no console window).
start "" "C:\Users\Apua\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe" "D:\InvoiceTool\shortage_app\app.py" > "D:\InvoiceTool\shortage_app\app.log" 2>&1

timeout /t 2 >nul

REM Open app in default browser.
start "" http://localhost:8765
