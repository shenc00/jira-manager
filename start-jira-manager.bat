@echo off
REM ======================================================================
REM  Jira Manager - one-click launcher
REM  Double-click this file to start the app. The first time, it sets up
REM  the environment and installs the libraries automatically.
REM  No path to configure - it always uses the folder it lives in.
REM ======================================================================
title Jira Manager
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo First-time setup: creating the environment and installing libraries.
    echo This can take a few minutes - please wait...
    echo.
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Python was not found. Install Python 3.10+ first
        echo  ^(see the README - "Install Python"^), then run this again.
        echo.
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Install hit a network/SSL issue - retrying with relaxed settings...
        pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
    )
) else (
    call ".venv\Scripts\activate.bat"
)

echo.
echo Starting Jira Manager. Your browser will open automatically.
echo Keep THIS window open while you use the app. Close it to stop.
echo.
python run.py

echo.
echo The app has stopped. You can close this window.
pause
