@echo off
title Building Nexus Harvester Windows EXE...
color 0A
echo =======================================================
echo        NEXUS HARVESTER - WINDOWS EXE BUILDER
echo =======================================================
echo.
echo [1/3] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    pause
    exit /b
)

echo [2/3] Installing required libraries (requests, pandas, openpyxl, pycountry, pyinstaller)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b
)

echo.
echo [3/3] Compiling standalone Nexus Harvester.exe with PyInstaller...
pyinstaller --noconsole --onefile --clean --name "Nexus Harvester" NexusHarvester.py

if exist "dist\Nexus Harvester.exe" (
    copy "dist\Nexus Harvester.exe" "Nexus Harvester.exe" >nul
    echo.
    echo =======================================================
    echo    SUCCESS! "Nexus Harvester.exe" is ready to sell!
    echo =======================================================
    echo The single executable is located at:
    echo   %CD%\Nexus Harvester.exe
    echo.
) else (
    echo [ERROR] Build failed. Please check the logs above.
)

pause
