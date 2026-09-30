@echo off
setlocal EnableExtensions

rem Jobs-Finder one-click Windows launcher.
rem This file intentionally uses the existing project runtime only:
rem   .venv\Scripts\python.exe main.py server --host 0.0.0.0 --port 8080
rem It never creates a virtual environment, installs packages, runs discovery,
rem starts the watcher command, or submits an application.

title Jobs-Finder

set "APP_NAME=Jobs-Finder"
set "PROJECT_DIR=%~dp0"
set "VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
set "MAIN_PY=%PROJECT_DIR%main.py"
set "REQUIREMENTS=%PROJECT_DIR%requirements.txt"

set "HOST=0.0.0.0"
if not "%JOBS_FINDER_HOST%"=="" set "HOST=%JOBS_FINDER_HOST%"
set "PORT=8080"
if not "%JOBS_FINDER_PORT%"=="" set "PORT=%JOBS_FINDER_PORT%"
set "DASHBOARD_URL=http://localhost:%PORT%"

echo ============================================================
echo   Jobs-Finder
echo ============================================================
echo Project directory: "%PROJECT_DIR%"
echo Environment: existing local .venv only
echo Dashboard URL: %DASHBOARD_URL%
echo.

pushd "%PROJECT_DIR%" >nul 2>&1
if errorlevel 1 (
    echo Startup status: FAILED
    echo Could not switch to the Jobs-Finder project directory.
    echo Path: "%PROJECT_DIR%"
    echo.
    pause
    exit /b 1
)

if not exist "%MAIN_PY%" (
    echo Startup status: FAILED
    echo main.py was not found. This launcher must stay in the Jobs-Finder project root.
    echo Expected: "%MAIN_PY%"
    echo.
    popd >nul 2>&1
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo Python/venv: MISSING
    echo Startup status: FAILED
    echo.
    echo The project virtual environment was not found:
    echo   "%PROJECT_DIR%.venv"
    echo.
    echo This launcher will not create a second environment automatically.
    echo Use the project's existing dependency mechanism from this folder:
    echo.
    echo   py -3.11 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo   .venv\Scripts\python.exe -m playwright install chromium
    echo.
    if exist "%REQUIREMENTS%" (
        echo Dependency file found: "%REQUIREMENTS%"
    ) else (
        echo WARNING: requirements.txt was not found at "%REQUIREMENTS%".
    )
    echo.
    popd >nul 2>&1
    pause
    exit /b 1
)

echo Python/venv: "%VENV_PYTHON%"
"%VENV_PYTHON%" --version
if errorlevel 1 (
    echo.
    echo Startup status: FAILED
    echo The virtual-environment Python exists but could not run.
    echo.
    popd >nul 2>&1
    pause
    exit /b 1
)

"%VENV_PYTHON%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Startup status: FAILED
    echo Required dashboard dependencies are missing from .venv.
    echo Install them with the existing requirements file:
    echo.
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    popd >nul 2>&1
    pause
    exit /b 1
)

netstat -ano -p tcp 2>nul | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo Startup status: FAILED
    echo Port %PORT% is already in use, so this launcher will not start a duplicate dashboard server.
    echo If Jobs-Finder is already running, open: %DASHBOARD_URL%
    echo Otherwise close the process using port %PORT% or set JOBS_FINDER_PORT to another port.
    echo.
    popd >nul 2>&1
    pause
    exit /b 1
)

echo.
echo Canonical command:
echo   "%VENV_PYTHON%" "%MAIN_PY%" server --host %HOST% --port %PORT%
echo.
echo Startup status: starting dashboard...
echo Browser: opening %DASHBOARD_URL%
echo Watcher: not launched by this launcher; dashboard uses the project's normal scheduler settings only.
echo Press Ctrl+C in this window to stop Jobs-Finder.
echo ------------------------------------------------------------

where powershell.exe >nul 2>&1
if not errorlevel 1 (
    start "Jobs-Finder Browser" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 3; Start-Process '%DASHBOARD_URL%'"
) else (
    start "" "%DASHBOARD_URL%"
)

"%VENV_PYTHON%" "%MAIN_PY%" server --host "%HOST%" --port "%PORT%"
set "EXIT_CODE=%ERRORLEVEL%"

echo ------------------------------------------------------------
if "%EXIT_CODE%"=="0" (
    echo Startup status: Jobs-Finder stopped.
) else (
    echo Startup status: FAILED or stopped with error code %EXIT_CODE%.
    echo Review the messages above for details.
)
echo.
popd >nul 2>&1
pause
exit /b %EXIT_CODE%
