@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Jobs-Finder one-click Windows launcher.
rem This file intentionally uses the existing project runtime only:
rem   .venv\Scripts\python.exe main.py server --host 0.0.0.0 --port 8080
rem It never clones another project, creates a second environment, runs discovery,
rem starts the watcher command, or submits an application.

title Jobs-Finder

set "APP_NAME=Jobs-Finder"
set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
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
echo Environment: existing local .venv, or first-run setup in that exact folder
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
    echo Startup status: first-run setup required
    echo.
    echo The project virtual environment was not found:
    echo   "%VENV_DIR%"
    echo.
    echo This launcher will not create a second project, create a second environment elsewhere, or use a global Python runtime.
    echo It will create the project's normal .venv folder only, using requirements.txt.
    echo.
    if not exist "%REQUIREMENTS%" (
        echo Startup status: FAILED
        echo requirements.txt was not found, so dependencies cannot be installed safely.
        echo Expected: "%REQUIREMENTS%"
        echo.
        popd >nul 2>&1
        pause
        exit /b 1
    )

    call :find_bootstrap_python
    if errorlevel 1 (
        echo Startup status: FAILED
        echo Python 3.11+ was not found. Install Python 3.11 or newer, then double-click this file again.
        echo.
        popd >nul 2>&1
        pause
        exit /b 1
    )

    echo First-run setup: creating .venv in this project only...
    call !BOOTSTRAP_PY! -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Startup status: FAILED
        echo Could not create the project .venv folder.
        echo.
        popd >nul 2>&1
        pause
        exit /b 1
    )

    echo First-run setup: installing dependencies from requirements.txt...
    "%VENV_PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 (
        echo Startup status: FAILED
        echo pip could not be upgraded inside .venv.
        echo.
        popd >nul 2>&1
        pause
        exit /b 1
    )
    "%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS%"
    if errorlevel 1 (
        echo Startup status: FAILED
        echo Dependencies could not be installed from requirements.txt.
        echo.
        popd >nul 2>&1
        pause
        exit /b 1
    )

    echo First-run setup: installing Playwright Chromium browser...
    "%VENV_PYTHON%" -m playwright install chromium
    if errorlevel 1 (
        echo Startup status: FAILED
        echo Playwright Chromium could not be installed. Check the network connection and try again.
        echo.
        popd >nul 2>&1
        pause
        exit /b 1
    )
    echo First-run setup: complete.
    echo.
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

:find_bootstrap_python
set "BOOTSTRAP_PY="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.11 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_PY=py -3.11"
        exit /b 0
    )
    py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_PY=py -3"
        exit /b 0
    )
)
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_PY=python"
        exit /b 0
    )
)
exit /b 1
