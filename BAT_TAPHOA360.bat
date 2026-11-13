@echo off
setlocal
chcp 65001 > nul
cd /d "%~dp0"
title Tap hoa 360 - Bat he thong
echo ============================================================
echo                KHOI DONG TAP HOA 360
echo ============================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" start_local.py %*
    goto :result
)

py -3 -c "import sys; sys.exit(sys.version_info[:2] < (3, 11))" > nul 2>&1
if not errorlevel 1 (
    py -3 start_local.py %*
    goto :result
)

python -c "import sys; sys.exit(sys.version_info[:2] < (3, 11))" > nul 2>&1
if not errorlevel 1 (
    python start_local.py %*
    goto :result
)

echo [LOI] Can cai Python 3.11 tro len. Chon "Add Python to PATH" khi cai.
echo Trang tai: https://www.python.org/downloads/windows/
pause
exit /b 1

:result
if errorlevel 1 (
    echo.
    echo [LOI] Khong the khoi dong. Vui long xem thong bao ben tren.
    pause
    exit /b 1
)
exit /b 0
