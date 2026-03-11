@echo off
title IGRA to FSL Converter
echo ============================================================
echo  IGRA to FSL Converter
echo ============================================================
echo.

cd /d "%~dp0"

:: Check for Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python 3.8+ and add it to PATH.
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Install dependencies if needed
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install flask requests
    echo.
)

echo Starting server...
echo.
python gui\server.py

pause
