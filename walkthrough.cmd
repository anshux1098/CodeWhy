@echo off
rem Run the guided walkthrough with the project's virtual environment.
rem The script writes the same output to walkthrough_report.txt (see --out).
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\walkthrough.py %*
) else (
  python scripts\walkthrough.py %*
)
set "CODE=%ERRORLEVEL%"
endlocal & exit /b %CODE%
