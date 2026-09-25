@echo off
setlocal
cd /d "%~dp0"
REM Prefer a local venv if present, else python on PATH
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" gremlinEx.py %*
) else if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" gremlinEx.py %*
) else (
  python gremlinEx.py %*
)
