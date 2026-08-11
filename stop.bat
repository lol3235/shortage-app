@echo off
chcp 65001 >nul

set "PIDFILE=D:\InvoiceTool\shortage_app\data\app.pid"
if exist "%PIDFILE%" (
    set /p PID=<%PIDFILE%
    taskkill /pid %PID% /f >nul 2>&1
    del "%PIDFILE%" >nul 2>&1
    echo App stopped (PID=%PID%).
) else (
    echo PID file not found, app may not be running.
)
