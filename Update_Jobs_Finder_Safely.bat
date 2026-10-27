@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Jobs-Finder - Safe Windows Update

rem Run only while the dashboard is closed. Never reset/stash local facts.
rem All real applicant data and the SQLite database are preserved.

set "PROJECT_DIR=%~dp0"
set "EXIT_CODE=1"
set "PORT=8080"
if defined JOBS_FINDER_PORT set "PORT=%JOBS_FINDER_PORT%"
if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%"
set "BACKUP_DIR=%LOCALAPPDATA%\Jobs-Finder\UpdateBackups"

echo =======================================================
echo        Jobs-Finder - SAFE UPDATE
echo =======================================================
echo No profile data, applications, or documents are deleted.
echo.
pushd "%PROJECT_DIR%" >nul 2>&1
if errorlevel 1 (
  echo FAILED: Could not open the project folder.
  if not defined CI pause
  exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
  echo FAILED: Git for Windows was not found.
  goto done
)
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo FAILED: This is not a Git checkout of Jobs-Finder.
  goto done
)
set "CURRENT_BRANCH="
for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "CURRENT_BRANCH=%%B"
if /I not "!CURRENT_BRANCH!"=="main" (
  echo HOLD: Only the main branch can be safely updated.
  echo Current branch: !CURRENT_BRANCH!
  goto done
)

netstat -ano -p tcp 2>nul | findstr /R /C:":!PORT! .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo HOLD: Port !PORT! is in use. Close Jobs-Finder before updating.
  goto done
)

rem Preserve the current canonical profile before ANY network operation.
if exist "profile.yaml" (
  call :backup_profile
  if errorlevel 1 goto done
)

rem Do not auto-stash, auto-merge, reset, or override owner-approved data.
set "LOCAL_CHANGES="
for /f "delims=" %%L in ('git status --porcelain --untracked-files=no 2^>nul') do set "LOCAL_CHANGES=1"
if defined LOCAL_CHANGES (
  echo HOLD: Local tracked changes were found.
  echo Your profile backup is safely stored in:
  echo   "!BACKUP_DIR!"
  echo No update was attempted. Review the differences before reconciling.
  git status --short
  goto done
)

echo Checking the official main branch...
git fetch --quiet origin main
if errorlevel 1 (
  echo FAILED: Could not fetch origin/main. Check internet and Git access.
  goto done
)
git merge --ff-only FETCH_HEAD
if errorlevel 1 (
  echo HOLD: A safe fast-forward update was not possible.
  echo No reset, forced merge, or profile overwrite was attempted.
  goto done
)
echo.
echo SUCCESS: Jobs-Finder source updated with a safe fast-forward.
git log -1 --oneline
echo Your personal profile and application database were preserved.
echo Start run_jobs_finder.bat to use the new version.
set "EXIT_CODE=0"
goto done

:backup_profile
if not exist "!BACKUP_DIR!" mkdir "!BACKUP_DIR!" >nul 2>&1
if not exist "!BACKUP_DIR!" (
  echo FAILED: Cannot create the private local profile backup folder.
  exit /b 1
)
set "TIMESTAMP="
for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss" 2^>nul') do set "TIMESTAMP=%%T"
if not defined TIMESTAMP (
  echo FAILED: Cannot timestamp a safe profile backup.
  exit /b 1
)
set "TARGET=!BACKUP_DIR!\profile-before-update-!TIMESTAMP!.yaml"
copy /Y "profile.yaml" "!TARGET!" >nul
if errorlevel 1 (
  echo FAILED: Could not back up profile.yaml; refusing to update.
  exit /b 1
)
echo Applicant profile backed up privately before update.
exit /b 0

:done
popd >nul 2>&1
if not defined CI pause
exit /b !EXIT_CODE!
