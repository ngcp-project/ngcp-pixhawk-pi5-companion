@echo off
TITLE GCS Telemetry MAVProxy Router
echo ========================================================
echo   GCS Windows Laptop Telemetry Router
echo ========================================================
echo.

:: Check if python is in PATH
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not added to your system PATH.
    echo Please install Python 3.9+ from python.org and check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Attempt to install dependencies quietly just in case
echo Checking dependencies (MAVProxy, pyserial)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pyserial MAVProxy prompt_toolkit wxPython
IF %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Failed to automatically install dependencies. You may need to run this as Administrator or manually type:
    echo pip install pyserial MAVProxy prompt_toolkit wxPython
)

echo.
echo Launching automated COM port scanner and MAVProxy Router...
echo.

python launch_gcs_router.py

pause
