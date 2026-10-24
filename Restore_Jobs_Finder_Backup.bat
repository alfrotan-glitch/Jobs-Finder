@echo off
setlocal EnableExtensions
title Jobs-Finder - Safe Backup Recovery
set "PROJECT_DIR=%~dp0"
set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
if exist "%PYTHON%" goto run_venv
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys; raise SystemExit(sys.version_info[:2] != (3,12))" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=py -3.12"
        goto run
    )
    py -3.11 -c "import sys; raise SystemExit(sys.version_info[:2] != (3,11))" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=py -3.11"
        goto run
    )
)
echo Python 3.11 or 3.12 was not found. Start run_jobs_finder.bat once first.
pause
exit /b 1

:run_venv
echo Choose your private ZIP backup in the file chooser.
echo The existing Jobs-Finder installation will NOT be overwritten.
cd /d "%PROJECT_DIR%"
"%PYTHON%" "%PROJECT_DIR%tools\restore_backup_gui.py"
goto completed

:run
echo Choose your private ZIP backup in the file chooser.
echo The existing Jobs-Finder installation will NOT be overwritten.
cd /d "%PROJECT_DIR%"
call %PYTHON% "%PROJECT_DIR%tools\restore_backup_gui.py"
:completed
if errorlevel 1 (
    echo Recovery was not completed. Your existing program was not changed.
    pause
    exit /b 1
)
exit /b 0
