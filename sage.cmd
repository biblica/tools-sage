@echo off
setlocal EnableExtensions
set "ROOT_DIR=%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONPATH=%ROOT_DIR%core;%PYTHONPATH%"
set "BOOTSTRAP_SCRIPT=%ROOT_DIR%scripts\bootstrap_runtime.py"
set "VENV_PYTHON=%ROOT_DIR%.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
  "%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 goto bootstrap_venv
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 goto bootstrap_py
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 goto bootstrap_python
)
where python3 >nul 2>nul
if not errorlevel 1 (
  python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
  if not errorlevel 1 goto bootstrap_python3
)

echo SAGE ERROR 1>&2
echo Result: BLOCKED 1>&2
echo - Python 3.10 or later was not found. 1>&2
echo - Install Python 3.10+; SAGE will create and manage its local .venv on the next launch. 1>&2
exit /b 2

:bootstrap_venv
cd /d "%ROOT_DIR%"
"%VENV_PYTHON%" "%BOOTSTRAP_SCRIPT%" "%ROOT_DIR%"
if errorlevel 1 exit /b %ERRORLEVEL%
goto run_venv

:bootstrap_py
cd /d "%ROOT_DIR%"
py -3 "%BOOTSTRAP_SCRIPT%" "%ROOT_DIR%"
if errorlevel 1 exit /b %ERRORLEVEL%
goto run_venv

:bootstrap_python
cd /d "%ROOT_DIR%"
python "%BOOTSTRAP_SCRIPT%" "%ROOT_DIR%"
if errorlevel 1 exit /b %ERRORLEVEL%
goto run_venv

:bootstrap_python3
cd /d "%ROOT_DIR%"
python3 "%BOOTSTRAP_SCRIPT%" "%ROOT_DIR%"
if errorlevel 1 exit /b %ERRORLEVEL%
goto run_venv

:run_venv
if not exist "%VENV_PYTHON%" (
  echo SAGE ERROR 1>&2
  echo Result: BLOCKED 1>&2
  echo - Local .venv validation completed without a runnable Python interpreter. 1>&2
  exit /b 2
)
"%VENV_PYTHON%" -m sage_core.cli %*
exit /b %ERRORLEVEL%
