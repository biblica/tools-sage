#!/bin/bash
# Clone and Install SAGE - Shell script wrapper

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_URL="$1"
TARGET_DIR="$2"

if [ -z "$REPO_URL" ]; then
  echo "Usage: clone_and_install.sh <repo_url> [target_directory]" >&2
  echo "" >&2
  echo "Example:" >&2
  echo "  bash clone_and_install.sh https://github.com/biblica/tools-sage.git ./sage" >&2
  exit 2
fi

# Check for Python 3.10+
if ! command -v python3 &> /dev/null; then
  if ! command -v python &> /dev/null; then
    echo "ERROR: Python 3.10+ is not installed or not in PATH." >&2
    echo "Please install Python from https://www.python.org/" >&2
    exit 1
  fi
  PYTHON="python"
else
  PYTHON="python3"
fi

# Verify Python version
$PYTHON -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null
if [ $? -ne 0 ]; then
  echo "ERROR: Python 3.10 or later is required." >&2
  exit 1
fi

# Check for Git
if ! command -v git &> /dev/null; then
  echo "ERROR: Git is not installed or not in PATH." >&2
  echo "Please install Git from https://git-scm.com/" >&2
  exit 1
fi

# Run the installation script
if [ -z "$TARGET_DIR" ]; then
  "$PYTHON" "$SCRIPTS_DIR/clone_and_install.py" "$REPO_URL"
else
  "$PYTHON" "$SCRIPTS_DIR/clone_and_install.py" "$REPO_URL" "$TARGET_DIR"
fi

exit $?
