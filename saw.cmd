@echo off
setlocal EnableExtensions
set "ROOT_DIR=%~dp0"
set "SETTINGS_PATH="
set "JSON_FLAG="
set "NO_PROMPT_FLAG="
set "LOG_MODE_FLAG="
:global
if /I "%~1"=="--settings" (
  if "%~2"=="" (echo saw: --settings requires a .yml filename 1>&2& exit /b 2)
  set "SETTINGS_PATH=%~2"
  shift
  shift
  goto global
)
if /I "%~1"=="--json" (
  set "JSON_FLAG=--json"
  shift
  goto global
)
if /I "%~1"=="--no-prompt" (
  set "NO_PROMPT_FLAG=--no-prompt"
  shift
  goto global
)
if /I "%~1"=="--quiet" (set "LOG_MODE_FLAG=--quiet"& shift& goto global)
if /I "%~1"=="--verbose" (set "LOG_MODE_FLAG=--verbose"& shift& goto global)
if /I "%~1"=="--debug" (set "LOG_MODE_FLAG=--debug"& shift& goto global)
if "%~1"=="" (
  set "COMMAND=status"
  goto run
)
if /I "%~1"=="help" goto help
if /I "%~1"=="-h" goto help
if /I "%~1"=="--help" goto help
set "COMMAND=%~1"
shift
:run
if defined SETTINGS_PATH (
  call "%ROOT_DIR%sage.cmd" --settings "%SETTINGS_PATH%" %JSON_FLAG% %NO_PROMPT_FLAG% %LOG_MODE_FLAG% shortcut --workflow saw "%COMMAND%" -- %*
) else (
  call "%ROOT_DIR%sage.cmd" %JSON_FLAG% %NO_PROMPT_FLAG% %LOG_MODE_FLAG% shortcut --workflow saw "%COMMAND%" -- %*
)
exit /b %ERRORLEVEL%
:help
echo usage: saw.cmd [--settings FILE.yml] [--json] [--no-prompt] [--quiet^|--verbose^|--debug] ^<command^> [options]
echo Commands: status, qa, focused, ol, submit, plan
echo Invalid input is corrected interactively when possible.
echo Use --no-prompt or --json for structured INPUT_REQUIRED output.
echo Use --grammar-override-id only to record existing grammar-review provenance.
exit /b 0
