@echo off
setlocal EnableExtensions
set "BIN_DIR=%~dp0"
for %%I in ("%BIN_DIR%..\..") do set "ROOT_DIR=%%~fI"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONPATH=%ROOT_DIR%\system\src;%PYTHONPATH%"
set "BOOTSTRAP_SCRIPT=%ROOT_DIR%\system\tools\bootstrap_runtime.py"
set "BOOTSTRAP_PROFILE=base"
for %%A in (%*) do if /I "%%~A"=="tui" set "BOOTSTRAP_PROFILE=tui"

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
echo - Install Python 3.10+; SAGE will create and manage its environment under SAGEdata on the next launch. 1>&2
exit /b 2

:bootstrap_py
pushd "%ROOT_DIR%" >nul 2>nul
if errorlevel 1 goto root_failed
py -3 "%BOOTSTRAP_SCRIPT%" "%ROOT_DIR%" "%BOOTSTRAP_PROFILE%" --launch %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:bootstrap_python
pushd "%ROOT_DIR%" >nul 2>nul
if errorlevel 1 goto root_failed
python "%BOOTSTRAP_SCRIPT%" "%ROOT_DIR%" "%BOOTSTRAP_PROFILE%" --launch %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:bootstrap_python3
pushd "%ROOT_DIR%" >nul 2>nul
if errorlevel 1 goto root_failed
python3 "%BOOTSTRAP_SCRIPT%" "%ROOT_DIR%" "%BOOTSTRAP_PROFILE%" --launch %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:root_failed
echo SAGE ERROR 1>&2
echo Result: BLOCKED 1>&2
echo - SAGE root could not be entered: %ROOT_DIR% 1>&2
exit /b 2
