@echo off
chcp 65001 >nul 2>&1
title Offline Twitter

echo ================================
echo   Offline Twitter Web App
echo ================================
echo.

REM Load credentials from .env file
set "ENV_FILE=%~dp0.env"
if exist "%ENV_FILE%" (
    echo Loading credentials from .env...
    for /F "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
        set "%%A=%%B"
    )
) else (
    echo WARNING: .env file not found at %ENV_FILE%
    echo Please create .env with AUTH_TOKEN and CT0
    pause
    exit /b 1
)

echo Starting server on http://127.0.0.1:5210
echo Press Ctrl+C to stop
echo.

python "%~dp0app.py" %*
