@echo off
setlocal EnableExtensions
set "BIN_DIR=%~dp0"
call "%BIN_DIR%sage.cmd" launcher-shortcut --workflow saw -- %*
exit /b %ERRORLEVEL%
