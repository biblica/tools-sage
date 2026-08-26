@echo off
setlocal EnableExtensions
set "TOOLS_DIR=%~dp0"

:find_python
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 goto run_py
)

where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 goto run_python
)

where python3 >nul 2>nul
if not errorlevel 1 (
  python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 goto run_python3
)

echo ERROR: Python 3.10 or later was not found. 1>&2
echo ACTION REQUIRED: Install System Python 3.10 or later and add it to PATH. 1>&2
echo On the Python installer, enable "Add python.exe to PATH" when that option is available. 1>&2
echo SAGE will create its managed runtime in SAGEdata/.system/runtime/venv after System Python is available. 1>&2
choice /C RQ /N /M "After adding System Python, choose [R]etry or [Q]uit: "
if errorlevel 2 exit /b 1
if errorlevel 1 goto find_python
exit /b 1

:run_py
py -3 "%TOOLS_DIR%clone_and_install.py" %*
exit /b %ERRORLEVEL%

:run_python
python "%TOOLS_DIR%clone_and_install.py" %*
exit /b %ERRORLEVEL%

:run_python3
python3 "%TOOLS_DIR%clone_and_install.py" %*
exit /b %ERRORLEVEL%
