@echo off
setlocal enabledelayedexpansion
title Building Nexus Harvester Windows EXE...
color 0A
echo =======================================================
echo        NEXUS HARVESTER - WINDOWS EXE BUILDER
echo =======================================================
echo.

echo [1/3] Detecting Python installation...
set PYTHON_CMD=python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=py
        echo Found Python via Windows Launcher 'py'.
    ) else (
        echo [ERROR] Python is not installed or not in PATH!
        echo Please download and install Python from https://www.python.org/downloads/
        echo IMPORTANT: Check the box "Add Python to PATH" during installation.
        pause
        exit /b
    )
) else (
    echo Found Python command in system PATH.
)

echo.
echo [2/3] Installing/updating required libraries (requests, pandas, openpyxl, pycountry, pyinstaller)...
%PYTHON_CMD% -m pip install --upgrade pip
%PYTHON_CMD% -m pip install requests pandas openpyxl pycountry pyinstaller
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements. Please check internet connection.
    pause
    exit /b
)

echo.
echo [3/3] Compiling standalone Nexus Harvester.exe with PyInstaller...
%PYTHON_CMD% -m PyInstaller --noconsole --onefile --clean --name "Nexus Harvester" NexusHarvester.py

if exist "dist\Nexus Harvester.exe" (
    copy "dist\Nexus Harvester.exe" "Nexus Harvester.exe" >nul
    echo.
    echo =======================================================
    echo    SUCCESS! "Nexus Harvester.exe" is ready to sell!
    echo =======================================================
    echo The standalone executable has been created at:
    echo   %CD%\Nexus Harvester.exe
    echo.
) else (
    echo [ERROR] Build failed. Please check the logs above.
)

pause
