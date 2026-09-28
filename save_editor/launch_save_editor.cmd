@echo off
setlocal
cd /d "%~dp0"
if exist "OGMD Save Editor.exe" (
  start "" "OGMD Save Editor.exe" %*
  exit /b 0
)
python save_editor.py %*
if errorlevel 1 (
  echo.
  echo The save editor exited with an error.
  pause
)
