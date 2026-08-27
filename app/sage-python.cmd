@echo off
setlocal EnableExtensions
for %%I in ("%~dp0.") do set "ROOT_DIR=%%~fI"
set "RUNTIME_BOOTSTRAP=%ROOT_DIR%\system\tools\bootstrap_python.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RUNTIME_BOOTSTRAP%" "%ROOT_DIR%" "base" "python-shell" %*
exit /b %ERRORLEVEL%
