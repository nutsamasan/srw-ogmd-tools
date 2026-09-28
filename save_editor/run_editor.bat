@echo off
setlocal
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0save_editor.py"
) else (
  python "%~dp0save_editor.py"
)
if errorlevel 1 pause
