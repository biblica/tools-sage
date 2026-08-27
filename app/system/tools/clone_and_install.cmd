@echo off
setlocal EnableExtensions
set "TOOLS_DIR=%~dp0"
for %%I in ("%TOOLS_DIR%..\..") do set "APP_ROOT=%%~fI"
call "%APP_ROOT%\sage-python.cmd" "%TOOLS_DIR%clone_and_install.py" %*
exit /b %ERRORLEVEL%
