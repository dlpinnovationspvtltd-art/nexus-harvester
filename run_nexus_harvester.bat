@echo off
title Launching Nexus Harvester...
echo Starting Nexus Harvester...
python -m pip install -r requirements.txt >nul 2>&1
python NexusHarvester.py
if %errorlevel% neq 0 (
    pause
)
