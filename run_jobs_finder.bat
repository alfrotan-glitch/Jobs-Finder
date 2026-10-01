@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Jobs-Finder one-click Windows launcher.
rem It starts only the canonical dashboard and never runs scans, watchers,
rem browser automation, or application submission.

title Jobs-Finder

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "MAIN_PY=%PROJECT_DIR%main.py"
set "REQUIREMENTS=%PROJECT_DIR%requirements.txt"

set "HOST=127.0.0.1"
if not "%JOBS_FINDER_HOST%"=="" set "HOST=%JOBS_FINDER_HOST%"
set "PORT=8080"
if not "%JOBS_FINDER_PORT%"=="" set "PORT=%JOBS_FINDER_PORT%"
set "DASHBOARD_URL=http://localhost:%PORT%"

echo ============================================================
echo   Jobs-Finder
echo ============================================================
echo Project directory: "%PROJECT_DIR%"
echo Dashboard URL: %DASHBOARD_URL%
echo.

pushd "%PROJECT_DIR%" >nul 2>&1
if errorlevel 1 (
    echo Startup status: FAILED
    echo Could not switch to the Jobs-Finder project directory.
    pause
    exit /b 1
)

if not exist "%MAIN_PY%" (
    echo Startup status: FAILED
    echo main.py was not found. Keep this launcher in the Jobs-Finder project root.
    popd >nul 2>&1
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo Python/venv: MISSING
    echo First-run setup will create only this project .venv:
    echo   "%VENV_DIR%"
    echo.
    if not exist "%REQUIREMENTS%" (
        echo Startup status: FAILED
        echo requirements.txt was not found.
        popd >nul 2>&1
        pause
        exit /b 1
    )

    call :find_bootstrap_python
    if errorlevel 1 (
        echo Startup status: FAILED
        echo Python 3.11 or 3.12 was not found. Install Python 3.11 or 3.12, then run this file again.
        popd >nul 2>&1
        pause
        exit /b 1
    )

    echo First-run setup: using !BOOTSTRAP_PY!
    call !BOOTSTRAP_PY! -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Startup status: FAILED
        echo Could not create the project .venv folder.
        popd >nul 2>&1
        pause
        exit /b 1
    )

    echo First-run setup: installing dependencies from requirements.txt...
    "%VENV_PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 goto dependency_failed
    "%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS%"
    if errorlevel 1 goto dependency_failed
    echo First-run setup: complete.
    echo.
)

echo Python/venv: "%VENV_PYTHON%"
"%VENV_PYTHON%" --version
if errorlevel 1 (
    echo Startup status: FAILED
    echo The virtual-environment Python exists but could not run.
    popd >nul 2>&1
    pause
    exit /b 1
)

"%VENV_PYTHON%" -c "import fastapi, uvicorn, yaml, bs4, docx, reportlab" >nul 2>&1
if errorlevel 1 (
    echo Startup status: FAILED
    echo Required dependencies are missing from .venv.
    echo Run: .venv\Scripts\python.exe -m pip install -r requirements.txt
    popd >nul 2>&1
    pause
    exit /b 1
)

netstat -ano -p tcp 2>nul | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo Startup status: FAILED
    echo Port %PORT% is already in use. Open %DASHBOARD_URL% if Jobs-Finder is already running.
    echo Or set JOBS_FINDER_PORT to another port.
    popd >nul 2>&1
    pause
    exit /b 1
)

echo Canonical command:
echo   "%VENV_PYTHON%" "%MAIN_PY%" server --host %HOST% --port %PORT%
echo.
echo Startup status: starting dashboard...
echo Browser: opening %DASHBOARD_URL%
echo Background scanning: disabled. Use Find Jobs in the dashboard.
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
)
popd >nul 2>&1
pause
exit /b %EXIT_CODE%

:dependency_failed
echo Startup status: FAILED
echo Dependency installation failed. Install Python 3.12 or 3.11, delete .venv, and run this file again.
popd >nul 2>&1
pause
exit /b 1

:find_bootstrap_python
set "BOOTSTRAP_PY="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] < (3, 13)))" >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_PY=py -3.12"
        exit /b 0
    )
    py -3.11 -c "import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] < (3, 13)))" >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_PY=py -3.11"
        exit /b 0
    )
    py -3 -c "import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] < (3, 13)))" >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_PY=py -3"
        exit /b 0
    )
)
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] < (3, 13)))" >nul 2>&1
    if not errorlevel 1 (
        set "BOOTSTRAP_PY=python"
        exit /b 0
    )
)
exit /b 1
