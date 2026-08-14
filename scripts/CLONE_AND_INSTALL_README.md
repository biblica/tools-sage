# SAGE Clone and Install Tool

This directory contains cross-platform installation scripts for cloning and setting up SAGE with a clean installation.

## Quick Start

### macOS / Linux
```bash
bash scripts/clone_and_install.sh https://github.com/biblica/tools-sage.git ~/sage
```

### Windows (Command Prompt or PowerShell)
```cmd
python scripts\clone_and_install.py https://github.com/biblica/tools-sage.git C:\sage
```

Or use the batch wrapper:
```cmd
scripts\clone_and_install.cmd https://github.com/biblica/tools-sage.git C:\sage
```

## Requirements

- **Python 3.10 or later** (required on all platforms)
- **Git** (required on all platforms)

### Installing Prerequisites

#### macOS
```bash
# Using Homebrew
brew install python@3.12 git
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install python3.10 git
```

#### Linux (Fedora/RHEL)
```bash
sudo dnf install python3.10 git
```

#### Windows
Download and install from:
- Python: https://www.python.org/downloads/
- Git: https://git-scm.com/download/win

## Installation Scripts

### `clone_and_install.py` (Core Installer)
Main Python script that performs the installation. Works on all platforms (macOS, Linux, Windows).

**Features:**
- Validates Python 3.10+ availability
- Verifies Git is installed
- Clones the repository
- Creates isolated Python virtual environment
- Installs dependencies from `requirements.txt`
- Installs development dependencies from `requirements-dev.txt`
- Validates the complete installation
- Generates installation log (`state/installation.json`)

**Direct usage (all platforms):**
```bash
python scripts/clone_and_install.py <repo_url> [target_directory]
```

**Example:**
```bash
# macOS/Linux
python3 scripts/clone_and_install.py https://github.com/biblica/tools-sage.git ~/sage

# Windows
python scripts\clone_and_install.py https://github.com/biblica/tools-sage.git C:\sage
```

### `clone_and_install.sh` (Unix Wrapper)
Bash shell script wrapper for Unix-like systems.

**Platforms:** macOS, Linux, WSL

**Usage:**
```bash
bash scripts/clone_and_install.sh <repo_url> [target_directory]
```

**Features:**
- Auto-detects Python 3 or python3
- Validates Python 3.10+ requirement
- Checks for Git availability
- Delegates to `clone_and_install.py`

**Permissions:** Executable (`rwxr-xr-x`)

### `clone_and_install.cmd` (Windows Batch Wrapper)
Windows batch file for Command Prompt or PowerShell.

**Platforms:** Windows (7+)

**Usage:**
```cmd
scripts\clone_and_install.cmd <repo_url> [target_directory]
```

**Features:**
- Auto-detects `python` or `py` launcher
- Validates Python 3.10+ requirement
- Checks for Git availability
- Delegates to `clone_and_install.py`

**Permissions:** Standard batch file (no execution bit needed)

## Installation Process

The installation performs these steps in sequence:

1. **Pre-flight Checks**
   - Verify Python 3.10+ is available
   - Verify Git is installed
   - Display system information

2. **Repository Setup**
   - Clone repository from provided URL
   - Verify clone was successful

3. **Virtual Environment**
   - Create isolated `.venv` directory
   - Use platform-specific Python executable location

4. **Dependency Installation**
   - Upgrade pip
   - Install from `requirements.txt`
   - Install from `requirements-dev.txt` (if present)

5. **Validation**
   - Verify virtual environment creation
   - Test Python 3.10+ in venv
   - Check for core module presence
   - Create installation log

6. **Completion Report**
   - Display success/failure status
   - Provide next steps for using SAGE
   - Show platform-specific commands

## Installation Log

After installation, check `state/installation.json` for details:
```json
{
  "timestamp": "2026-08-14T10:30:00+00:00",
  "success": true,
  "python_version": "3.12.4",
  "platform": "Darwin",
  "root_directory": "/Users/pietertraut/sage"
}
```

## Next Steps After Installation

### macOS / Linux
```bash
cd ~/sage
./sage status           # Check SAGE status
./bic help             # Bible Interchange Control commands
./saw help             # Scripture Alignment Workflow commands
```

### Windows
```cmd
cd C:\sage
sage.cmd status        REM Check SAGE status
bic.cmd help           REM Bible Interchange Control commands
saw.cmd help           REM Scripture Alignment Workflow commands
```

## Troubleshooting

### Python Not Found
**Error:** "Python is not installed or not in PATH"

**Solution:**
- Install Python 3.10+ from https://www.python.org/
- On Windows, ensure "Add Python to PATH" is checked during installation
- On macOS/Linux, verify installation: `python3 --version`

### Git Not Found
**Error:** "Git is not installed or not in PATH"

**Solution:**
- Install Git from https://git-scm.com/
- On macOS with Homebrew: `brew install git`
- On Linux (Ubuntu): `sudo apt-get install git`

### Repository Clone Failed
**Error:** "Repository clone failed"

**Solution:**
- Verify repository URL is correct
- Check internet connectivity
- Ensure write permissions in target directory
- Try manually cloning: `git clone <repo_url>`

### Virtual Environment Creation Failed
**Error:** "Failed to create virtual environment"

**Solution:**
- Ensure sufficient disk space (at least 1GB)
- Check write permissions in target directory
- Verify Python 3.10+ is being used
- Try manual creation: `python3 -m venv .venv`

### Dependency Installation Failed
**Error:** "Dependency installation failed"

**Solution:**
- Check internet connectivity
- Verify `requirements.txt` exists in repository
- Try manual installation: `source .venv/bin/activate && pip install -r requirements.txt`
- Check for conflicting packages with `pip check`

## Platform-Specific Notes

### macOS
- Use `python3` or `python` depending on installation method
- M1/M2 Macs: May need Rosetta or native Python 3.11+
- Recommended: Use Homebrew or MacPorts

### Linux
- Use `python3` (typically mapped to Python 3.10+)
- Ensure `python3-venv` package is installed: `sudo apt-get install python3-venv`
- SELinux may require additional permissions

### Windows
- Use `python` or `py` launcher
- Ensure Python is added to PATH during installation
- Use forward slashes in paths or wrap in quotes
- PowerShell may require script execution policy adjustment

## Development

### Modifying the Installer

The core installer is written in Python 3 and follows these design principles:

1. **Cross-platform compatibility**: Uses `pathlib.Path` for all file operations
2. **Minimal dependencies**: Only uses Python stdlib, no external packages
3. **Clear error messages**: Specific errors with actionable remediation steps
4. **Logging**: Generates installation log for troubleshooting

### Testing

Test on your target platform:
```bash
# Test Python detection
python --version
python3 --version

# Test Git detection
git --version

# Test clone in a temp directory
mkdir /tmp/test-sage-clone
python scripts/clone_and_install.py https://github.com/biblica/tools-sage.git /tmp/test-sage-clone
```

## License

Same as SAGE project.

## Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review `state/installation.json` log for details
3. Open an issue on GitHub: https://github.com/biblica/tools-sage/issues
