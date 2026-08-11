@echo off
set "PIDFILE=D:\InvoiceTool\shortage_app\data\app.pid"
if exist "%PIDFILE%" (
    set /p PID=<%PIDFILE%
    taskkill /pid %PID% /f >nul 2>&1
    del "%PIDFILE%" >nul 2>&1
    echo 已停止欠料看板 APP（PID=%PID%）
) else (
    echo 未找到 PID 文件，可能未运行。
)
