@echo off
echo ============================================================
echo   AERMET Automation Tool
echo ============================================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.8+ and add to PATH.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Install dependencies
echo Installing dependencies...
pip install flask requests >nul 2>&1
if errorlevel 1 (
    echo WARNING: pip install had issues. Trying to continue anyway...
)

echo.
echo Starting server...
echo Open your browser to: http://localhost:5000
echo Press Ctrl+C to stop.
echo ============================================================
echo.

cd /d "%~dp0"
python server.py

pause
