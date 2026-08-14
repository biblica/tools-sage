@echo off
REM Clone and Install SAGE - Windows batch wrapper
setlocal EnableExtensions

set "SCRIPTS_DIR=%~dp0"
set "REPO_URL=%~1"
set "TARGET_DIR=%~2"

if "%REPO_URL%"=="" (
  echo Usage: clone_and_install.cmd ^<repo_url^> [target_directory]
  echo.
  echo Example:
  echo   clone_and_install.cmd https://github.com/biblica/tools-sage.git C:\sage
  echo.
  exit /b 2
)

REM Check for Python
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH. 1>&2
    echo Please install Python 3.10 or later from https://www.python.org/
    exit /b 1
  )
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)

REM Check for Git
where git >nul 2>nul
if errorlevel 1 (
  echo ERROR: Git is not installed or not in PATH. 1>&2
  echo Please install Git from https://git-scm.com/
  exit /b 1
)

REM Run the installation script
if "%TARGET_DIR%"=="" (
  "%PYTHON%" "%SCRIPTS_DIR%clone_and_install.py" "%REPO_URL%"
) else (
  "%PYTHON%" "%SCRIPTS_DIR%clone_and_install.py" "%REPO_URL%" "%TARGET_DIR%"
)

exit /b %ERRORLEVEL%
