@echo off
setlocal EnableExtensions
set "BIN_DIR=%~dp0"
for %%I in ("%BIN_DIR%..\..") do set "ROOT_DIR=%%~fI"
set "BOOTSTRAP_PROFILE=base"
for %%A in (%*) do if /I "%%~A"=="tui" set "BOOTSTRAP_PROFILE=tui"
set "RUNTIME_BOOTSTRAP=%ROOT_DIR%\system\tools\bootstrap_python.ps1"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%RUNTIME_BOOTSTRAP%" "%ROOT_DIR%" "%BOOTSTRAP_PROFILE%" "launch" %*
exit /b %ERRORLEVEL%
