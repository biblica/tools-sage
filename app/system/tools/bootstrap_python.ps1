param(
    [Parameter(Position = 0, Mandatory = $true)]
    [string]$AppRoot,
    [Parameter(Position = 1, Mandatory = $true)]
    [ValidateSet("base", "tui")]
    [string]$Profile,
    [Parameter(Position = 2, Mandatory = $true)]
    [ValidateSet("launch", "python-shell")]
    [string]$Mode,
    [Parameter(Position = 3, ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)

$ErrorActionPreference = "Stop"
$AppRoot = [IO.Path]::GetFullPath($AppRoot)
$ManifestPath = Join-Path $AppRoot "system\config\python-runtime.json"
$BootstrapScript = Join-Path $AppRoot "system\tools\bootstrap_runtime.py"
$LastFailure = ""
$ForceReinstall = $false
$PythonVersion = "UNKNOWN"
$PythonMinor = "UNKNOWN"
$HostPythonMinimum = "UNKNOWN"
$PlatformKey = "UNKNOWN"
$Artifact = $null
$DataHome = $null
$ManagedPython = $null
$BootstrapPython = $null
$RuntimeProvider = $null
$RuntimeSourcePath = $null
$SelectedPythonVersion = $null
$NextAction = "attempt"

function Set-Failure([string]$Message) {
    $script:LastFailure = $Message
}

function Get-ExplicitDataHome([string[]]$Arguments) {
    for ($index = 0; $index -lt $Arguments.Count; $index++) {
        $value = $Arguments[$index]
        if ($value.StartsWith("--data-home=")) {
            return $value.Substring("--data-home=".Length)
        }
        if ($value -eq "--data-home" -and $index + 1 -lt $Arguments.Count) {
            return $Arguments[$index + 1]
        }
    }
    return $null
}

function Test-DataHomeReset([string[]]$Arguments) {
    $sawCommand = $false
    foreach ($value in $Arguments) {
        if ($value -eq "data-home") {
            $sawCommand = $true
        }
        elseif ($sawCommand -and $value -eq "reset") {
            return $true
        }
    }
    return $false
}

function Get-InstallationKey([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value.ToLowerInvariant())
        $digest = $sha.ComputeHash($bytes)
        return ([BitConverter]::ToString($digest) -replace "-", "").ToLowerInvariant().Substring(0, 20)
    }
    finally {
        $sha.Dispose()
    }
}

function Get-PersistedDataHome {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } elseif ($env:APPDATA) { $env:APPDATA } else { $null }
    if (-not $base) {
        return $null
    }
    $key = Get-InstallationKey $AppRoot
    $locator = Join-Path $base "SAGE\installations\$key.json"
    if (-not (Test-Path -LiteralPath $locator -PathType Leaf)) {
        return $null
    }
    try {
        $payload = Get-Content -LiteralPath $locator -Raw | ConvertFrom-Json
        return [string]$payload.data_home
    }
    catch {
        Set-Failure "The persisted localdata locator is invalid: $locator"
        return $null
    }
}

function Resolve-DataHome([string[]]$Arguments) {
    $bundleRoot = Split-Path -Parent $AppRoot
    $defaultData = Join-Path $bundleRoot "localdata"
    $explicit = Get-ExplicitDataHome $Arguments
    if ($explicit) {
        $candidate = $explicit
    }
    elseif (Test-DataHomeReset $Arguments) {
        $candidate = $defaultData
    }
    elseif ($env:SAGE_DATA_HOME) {
        $candidate = $env:SAGE_DATA_HOME
    }
    else {
        $persisted = Get-PersistedDataHome
        $candidate = if ($persisted) { $persisted } else { $defaultData }
    }
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        Set-Failure "The localdata path must be absolute before the Python runtime can be installed: $candidate"
        return $null
    }
    $resolved = [IO.Path]::GetFullPath($candidate)
    $appPrefix = $AppRoot.TrimEnd("\") + "\"
    if ($resolved.Equals($AppRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $resolved.StartsWith($appPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Set-Failure "Refusing to install mutable runtime data inside the immutable app directory: $resolved"
        return $null
    }
    return $resolved
}

function Test-ManagedPython([string]$Python, [string]$Version) {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        return $false
    }
    try {
        & $Python -c "import platform; raise SystemExit(0 if platform.python_implementation() == 'CPython' and platform.python_version() == '$Version' else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Test-ApprovedHostPython([string]$Python, [string]$MinimumVersion, [string]$MaximumVersion) {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        return $false
    }
    try {
        & $Python -c "import platform,sys,venv; version=sys.version_info[:3]; minimum=tuple(map(int, '$MinimumVersion'.split('.'))); maximum=tuple(map(int, '$MaximumVersion'.split('.'))); raise SystemExit(0 if platform.python_implementation() == 'CPython' and minimum <= version <= maximum else 1)" *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $Python
        $signatureStatus = [string]$signature.Status
        $signerSubject = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { "" }
        return $signatureStatus -eq "Valid" -and $signerSubject -match "Python Software Foundation"
    }
    catch {
        return $false
    }
}

function Get-PythonVersion([string]$Python) {
    try {
        return [string](& $Python -c "import platform; print(platform.python_version())" 2>$null | Select-Object -Last 1)
    }
    catch {
        return "UNKNOWN"
    }
}

function Get-ApprovedWindowsPython {
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($env:LOCALAPPDATA) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"))
    }
    if ($env:ProgramFiles) {
        $candidates.Add((Join-Path $env:ProgramFiles "Python312\python.exe"))
    }

    foreach ($registryRoot in @(
        "Registry::HKEY_CURRENT_USER\Software\Python\PythonCore\3.12\InstallPath",
        "Registry::HKEY_LOCAL_MACHINE\Software\Python\PythonCore\3.12\InstallPath"
    )) {
        try {
            $key = Get-Item -LiteralPath $registryRoot -ErrorAction Stop
            $executable = [string]$key.GetValue("ExecutablePath", "")
            if (-not $executable) {
                $installPath = [string]$key.GetValue("", "")
                if ($installPath) {
                    $executable = Join-Path $installPath "python.exe"
                }
            }
            if ($executable) {
                $candidates.Add($executable)
            }
        }
        catch {
            # This installation scope is simply absent.
        }
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $listed = & $launcher.Source -0p 2>$null
            foreach ($line in $listed) {
                if ($line -match "3\.12.*?([A-Za-z]:\\.+python(?:3\.12)?\.exe)\s*$") {
                    $candidates.Add($Matches[1].Trim())
                }
            }
        }
        catch {
            # Registry and standard-location discovery remain available.
        }
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-ApprovedHostPython $candidate $HostPythonMinimum $PythonVersion) {
            return $candidate
        }
    }
    return $null
}

function Get-WinGetCommand {
    $command = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $null
}

function Install-WinGetPython {
    $winget = Get-WinGetCommand
    if (-not $winget) {
        Set-Failure "WinGet is unavailable. Install App Installer from Microsoft, then launch SAGE again."
        return $false
    }
    Write-Host "Installing approved Python $PythonMinor with WinGet..."
    try {
        & $winget install --id "Python.Python.$PythonMinor" --exact --source winget --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            Set-Failure "WinGet could not install Python $PythonMinor. Review the WinGet output, then retry or exit."
            return $false
        }
        return $true
    }
    catch {
        Set-Failure "WinGet could not install Python $PythonMinor`: $($_.Exception.Message)"
        return $false
    }
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Download-Archive([string]$Url, [string]$Destination, [string]$ExpectedSha256) {
    $partial = "$Destination.part"
    Write-Host "Downloading SAGE-approved CPython $PythonVersion for $PlatformKey..."
    try {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            $arguments = @("-fL", "--retry", "3", "--connect-timeout", "20")
            if ($env:SAGE_CA_BUNDLE) {
                $arguments += @("--cacert", $env:SAGE_CA_BUNDLE)
            }
            $arguments += @("-o", $partial, $Url)
            & $curl.Source @arguments
            if ($LASTEXITCODE -ne 0) {
                throw "curl exited with $LASTEXITCODE"
            }
        }
        else {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $Url -OutFile $partial -UseBasicParsing
        }
        if ((Get-FileSha256 $partial) -ne $ExpectedSha256) {
            Set-Failure "The downloaded Python runtime failed SHA-256 verification."
            return $false
        }
        Move-Item -LiteralPath $partial -Destination $Destination -Force
        return $true
    }
    catch {
        if (-not $LastFailure) {
            Set-Failure "The approved Python runtime download failed: $($_.Exception.Message)"
        }
        return $false
    }
}

function Install-PythonRuntime {
    $script:RuntimeRoot = Join-Path $DataHome ".system\runtime"
    $script:PythonRoot = Join-Path $RuntimeRoot "python"
    $script:ManagedPython = Join-Path $RuntimeRoot ($Artifact.python_path -replace "/", "\")
    $downloadRoot = Join-Path $RuntimeRoot "downloads"
    $archivePath = Join-Path $downloadRoot $Artifact.archive_name

    if (-not $ForceReinstall -and (Test-ManagedPython $ManagedPython $PythonVersion)) {
        return $true
    }
    New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
    $cachedReady = (Test-Path -LiteralPath $archivePath -PathType Leaf) -and
        ((Get-FileSha256 $archivePath) -eq $Artifact.sha256)
    if (-not $cachedReady -and -not (Download-Archive $Artifact.url $archivePath $Artifact.sha256)) {
        return $false
    }

    $stageRoot = Join-Path $RuntimeRoot (".python-stage-" + [Diagnostics.Process]::GetCurrentProcess().Id)
    $oldRoot = Join-Path $RuntimeRoot (".python-old-" + [Diagnostics.Process]::GetCurrentProcess().Id)
    Remove-Item -LiteralPath $stageRoot, $oldRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
    try {
        & tar.exe -xzf $archivePath -C $stageRoot
        if ($LASTEXITCODE -ne 0) {
            throw "tar exited with $LASTEXITCODE"
        }
        $stagedPython = Join-Path $stageRoot ($Artifact.python_path -replace "/", "\")
        if (-not (Test-ManagedPython $stagedPython $PythonVersion)) {
            throw "The unpacked runtime did not match CPython $PythonVersion"
        }
        if (Test-Path -LiteralPath $PythonRoot) {
            Move-Item -LiteralPath $PythonRoot -Destination $oldRoot
        }
        Move-Item -LiteralPath (Join-Path $stageRoot "python") -Destination $PythonRoot
        Remove-Item -LiteralPath $oldRoot, $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Installed SAGE-approved CPython $PythonVersion at $PythonRoot"
        return $true
    }
    catch {
        if ((Test-Path -LiteralPath $oldRoot) -and -not (Test-Path -LiteralPath $PythonRoot)) {
            Move-Item -LiteralPath $oldRoot -Destination $PythonRoot
        }
        Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
        Set-Failure "The verified Python runtime could not be installed: $($_.Exception.Message)"
        return $false
    }
}

function Select-PythonRuntime {
    $script:RuntimeRoot = Join-Path $DataHome ".system\runtime"
    $managedCandidate = Join-Path $RuntimeRoot ($Artifact.python_path -replace "/", "\")
    if (-not $ForceReinstall -and (Test-ManagedPython $managedCandidate $PythonVersion)) {
        $script:ManagedPython = $managedCandidate
        $script:BootstrapPython = $managedCandidate
        $script:RuntimeProvider = "sage-managed"
        $script:RuntimeSourcePath = $managedCandidate
        $script:SelectedPythonVersion = $PythonVersion
        return $true
    }
    if (-not $ForceReinstall) {
        $hostPython = Get-ApprovedWindowsPython
        if ($hostPython) {
            $script:ManagedPython = $hostPython
            $script:BootstrapPython = $hostPython
            $script:RuntimeProvider = "python.org"
            $script:RuntimeSourcePath = $hostPython
            $script:SelectedPythonVersion = Get-PythonVersion $hostPython
            Write-Host "Using approved Python.org CPython $SelectedPythonVersion at $hostPython"
            return $true
        }
    }
    if (-not (Install-PythonRuntime)) {
        return $false
    }
    $script:BootstrapPython = $ManagedPython
    $script:RuntimeProvider = "sage-managed"
    $script:RuntimeSourcePath = $ManagedPython
    $script:SelectedPythonVersion = $PythonVersion
    return $true
}

function Write-BlockReport {
    [Console]::Error.WriteLine("SAGE RUNTIME INSTALLATION REPORT")
    [Console]::Error.WriteLine("Result: BLOCKED")
    [Console]::Error.WriteLine("Platform: $PlatformKey")
    [Console]::Error.WriteLine("Approved Python: CPython $PythonVersion")
    [Console]::Error.WriteLine("Reason: $LastFailure")
    [Console]::Error.WriteLine("Available actions:")
    [Console]::Error.WriteLine("  1. Install the SAGE Python runtime again")
    if (Get-WinGetCommand) {
        [Console]::Error.WriteLine("  2. Install approved Python $PythonMinor with WinGet")
        [Console]::Error.WriteLine("  3. Exit SAGE")
    }
    else {
        [Console]::Error.WriteLine("  2. Exit SAGE")
        [Console]::Error.WriteLine("WinGet option: unavailable because WinGet/App Installer is not installed.")
    }
}

function Request-RetryOrExit {
    if ([Console]::IsInputRedirected) {
        [Console]::Error.WriteLine("Non-interactive launch: exiting SAGE.")
        return "exit"
    }
    while ($true) {
        $wingetAvailable = [bool](Get-WinGetCommand)
        $choice = Read-Host $(if ($wingetAvailable) { "Choose 1, 2, or 3" } else { "Choose 1 or 2" })
        if ($choice -eq "1") { return "standalone" }
        if ($wingetAvailable) {
            if ($choice -eq "2") { return "winget" }
            if ($choice -eq "3") { return "exit" }
            [Console]::Error.WriteLine("Enter 1 to install again, 2 for WinGet, or 3 to exit.")
        }
        else {
            if ($choice -eq "2") { return "exit" }
            [Console]::Error.WriteLine("Enter 1 to install again or 2 to exit.")
        }
    }
}

try {
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "The governed Python runtime manifest is missing: $ManifestPath"
    }
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    $PythonVersion = [string]$Manifest.python_version
    $PythonMinor = $PythonVersion.Substring(0, $PythonVersion.LastIndexOf("."))
    $HostPythonMinimum = [string]$Manifest.host_python_minimum_version
    $PlatformKey = "windows-x86_64"
    $machineArchitecture = if ($env:PROCESSOR_ARCHITEW6432) {
        $env:PROCESSOR_ARCHITEW6432
    }
    else {
        $env:PROCESSOR_ARCHITECTURE
    }
    if (-not [Environment]::Is64BitOperatingSystem -or $machineArchitecture -notmatch "^(AMD64|x86_64)$") {
        throw "No approved SAGE Python runtime is pinned for Windows/$machineArchitecture."
    }
    $Artifact = $Manifest.artifacts.$PlatformKey
    if (-not $HostPythonMinimum -or -not $Artifact -or -not $Artifact.url -or -not $Artifact.sha256 -or -not $Artifact.python_path) {
        throw "The governed Python runtime manifest has no complete entry for $PlatformKey."
    }
    $DataHome = Resolve-DataHome $ForwardArgs
    if (-not $DataHome) {
        throw $LastFailure
    }
}
catch {
    Set-Failure $_.Exception.Message
}
$PreparationFailure = $LastFailure

while ($true) {
    if ($NextAction -eq "winget") {
        $NextAction = "attempt"
        $LastFailure = ""
        if (-not (Install-WinGetPython)) {
            Write-BlockReport
            $NextAction = Request-RetryOrExit
            if ($NextAction -eq "exit") {
                exit 2
            }
            continue
        }
        $ForceReinstall = $false
        $LastFailure = $PreparationFailure
    }
    elseif ($NextAction -eq "standalone") {
        $NextAction = "attempt"
        $ForceReinstall = $true
        $LastFailure = $PreparationFailure
    }
    $installed = $false
    if (-not $LastFailure) {
        try {
            $installed = Select-PythonRuntime
        }
        catch {
            Set-Failure "The approved Python runtime could not be installed: $($_.Exception.Message)"
        }
    }
    if (-not $LastFailure -and $installed) {
        $env:SAGE_DATA_HOME = $DataHome
        $env:SAGE_MANAGED_PYTHON_VERSION = $SelectedPythonVersion
        $env:SAGE_MANAGED_PYTHON_PLATFORM = $PlatformKey
        $env:SAGE_PYTHON_RUNTIME_PROVIDER = $RuntimeProvider
        $env:SAGE_PYTHON_RUNTIME_PATH = $RuntimeSourcePath
        if ($RuntimeProvider -eq "sage-managed") {
            $env:SAGE_MANAGED_PYTHON_SHA256 = $Artifact.sha256
        }
        else {
            Remove-Item Env:SAGE_MANAGED_PYTHON_SHA256 -ErrorAction SilentlyContinue
        }
        if ($ForceReinstall) {
            $env:SAGE_FORCE_RUNTIME_REINSTALL = "1"
        }
        else {
            Remove-Item Env:SAGE_FORCE_RUNTIME_REINSTALL -ErrorAction SilentlyContinue
        }
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $bootstrapStatus = -1
        try {
            & $BootstrapPython $BootstrapScript $AppRoot $Profile
            $bootstrapStatus = $LASTEXITCODE
        }
        catch {
            Set-Failure "The managed environment could not be prepared: $($_.Exception.Message)"
        }
        if (-not $LastFailure -and $bootstrapStatus -eq 0) {
            $venvPython = Join-Path $DataHome ".system\runtime\venv\Scripts\python.exe"
            $env:PYTHONPATH = (Join-Path $AppRoot "system\src")
            Set-Location -LiteralPath $AppRoot
            try {
                if ($Mode -eq "python-shell") {
                    & $venvPython @ForwardArgs
                }
                else {
                    & $venvPython -m sage.cli @ForwardArgs
                }
                exit $LASTEXITCODE
            }
            catch {
                Set-Failure "The SAGE application could not start in its managed environment: $($_.Exception.Message)"
            }
        }
        elseif (-not $LastFailure) {
            Set-Failure "The managed environment or its pinned dependencies failed validation."
        }
    }
    Write-BlockReport
    $NextAction = Request-RetryOrExit
    if ($NextAction -eq "exit") {
        exit 2
    }
}
