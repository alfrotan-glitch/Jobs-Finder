@echo off
setlocal
cd /d "%~dp0"
echo ===================================================
echo    JOBS-FINDER - READ-ONLY ACCEPTANCE CHECK
echo ===================================================
echo This does not scan jobs, edit profiles, or send emails.
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Python environment not found. Start run_jobs_finder.bat first.
  echo No files or profile information were changed.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "tools\release_readiness.py"
set "CODE=%ERRORLEVEL%"
echo.
if not "%CODE%"=="0" echo Release readiness requires attention. Do not treat this as production approval.
if "%CODE%"=="0" echo Local automated checks passed. Browser and privacy checks still require your approval.
pause
exit /b %CODE%
