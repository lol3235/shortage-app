@echo off
cd /d "D:\InvoiceTool\shortage_app"
REM 用 venv 的 pythonw 启动（无黑窗），输出重定向到 app.log
start "" "C:\Users\Apua\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe" "D:\InvoiceTool\shortage_app\app.py" > "D:\InvoiceTool\shortage_app\app.log" 2>&1
timeout /t 2 >nul
REM 打开浏览器
start "" http://localhost:8765
