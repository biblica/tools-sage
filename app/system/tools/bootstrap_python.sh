#!/bin/sh
set -u

if [ "$#" -lt 3 ]; then
    printf '%s\n' \
        'SAGE RUNTIME INSTALLATION REPORT' \
        'Result: BLOCKED' \
        'Platform: UNKNOWN' \
        'Approved Python: UNKNOWN' \
        'Reason: The SAGE runtime bootstrap was called without its required launcher arguments.' \
        'Available actions:' \
        '  1. Install the SAGE Python runtime again' \
        '  2. Exit SAGE' \
        'Non-interactive launch: exiting SAGE.' >&2
    exit 2
fi

APP_ROOT=$1
PROFILE=$2
MODE=$3
shift 3

canonical_app_root=$(CDPATH= cd -- "$APP_ROOT" 2>/dev/null && pwd -P) || canonical_app_root=$APP_ROOT
APP_ROOT=$canonical_app_root
BUNDLE_ROOT=$(CDPATH= cd -- "$APP_ROOT/.." 2>/dev/null && pwd -P) || BUNDLE_ROOT="$APP_ROOT/.."

MANIFEST="$APP_ROOT/system/config/python-runtime.json"
BOOTSTRAP_SCRIPT="$APP_ROOT/system/tools/bootstrap_runtime.py"
LAST_ERROR=""
FORCE_REINSTALL=0
HOST_SYSTEM=UNKNOWN
HOST_ARCH=UNKNOWN
PLATFORM_KEY=UNKNOWN
PYTHON_VERSION=UNKNOWN
PYTHON_MINOR=UNKNOWN
HOST_PYTHON_MINIMUM=UNKNOWN
ARCHIVE_NAME=""
PYTHON_PATH=""
RUNTIME_SHA256=""
RUNTIME_URL=""
DATA_HOME=""
MANAGED_PYTHON=""
BOOTSTRAP_PYTHON=""
RUNTIME_PROVIDER=""
RUNTIME_SOURCE_PATH=""
SELECTED_PYTHON_VERSION=""
NEXT_ACTION=attempt
RECOVERY_ONLY=0

fail() {
    LAST_ERROR=$1
    return 1
}

manifest_global() {
    field=$1
    sed -n "s/^[[:space:]]*\"$field\":[[:space:]]*\"\([^\"]*\)\"[,]*[[:space:]]*$/\1/p" "$MANIFEST" | head -n 1
}

manifest_artifact() {
    target=$1
    field=$2
    awk -v target="$target" -v field="$field" '
        $0 ~ "\\\"" target "\\\"[[:space:]]*:" { selected = 1; next }
        selected && $0 ~ /^[[:space:]]*}/ { exit }
        selected && $0 ~ "\\\"" field "\\\"[[:space:]]*:" {
            value = $0
            sub(/^[^:]*:[[:space:]]*\"/, "", value)
            sub(/\"[,]*[[:space:]]*$/, "", value)
            print value
            exit
        }
    ' "$MANIFEST"
}

sha256_file() {
    target=$1
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$target" | awk '{print $1}'
        return
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$target" | awk '{print $1}'
        return
    fi
    if command -v openssl >/dev/null 2>&1; then
        openssl dgst -sha256 "$target" | awk '{print $NF}'
        return
    fi
    return 1
}

sha256_text() {
    value=$1
    if command -v shasum >/dev/null 2>&1; then
        printf '%s' "$value" | shasum -a 256 | awk '{print substr($1, 1, 20)}'
        return
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        printf '%s' "$value" | sha256sum | awk '{print substr($1, 1, 20)}'
        return
    fi
    if command -v openssl >/dev/null 2>&1; then
        printf '%s' "$value" | openssl dgst -sha256 | awk '{print substr($NF, 1, 20)}'
        return
    fi
    return 1
}

explicit_data_home() {
    expect_value=0
    for argument in "$@"; do
        if [ "$expect_value" -eq 1 ]; then
            printf '%s\n' "$argument"
            return
        fi
        case "$argument" in
            --data-home=*) printf '%s\n' "${argument#--data-home=}"; return ;;
            --data-home) expect_value=1 ;;
        esac
    done
}

is_data_home_reset() {
    saw_command=0
    for argument in "$@"; do
        if [ "$argument" = "data-home" ]; then
            saw_command=1
        elif [ "$saw_command" -eq 1 ] && [ "$argument" = "reset" ]; then
            return 0
        fi
    done
    return 1
}

persisted_data_home() {
    install_key=$(sha256_text "$APP_ROOT") || return 1
    case "$HOST_SYSTEM" in
        Darwin)
            [ -n "${HOME:-}" ] || return 1
            locator="$HOME/Library/Application Support/SAGE/installations/$install_key.json"
            ;;
        Linux)
            if [ -n "${XDG_CONFIG_HOME:-}" ]; then
                locator="$XDG_CONFIG_HOME/sage/installations/$install_key.json"
            elif [ -n "${HOME:-}" ]; then
                locator="$HOME/.config/sage/installations/$install_key.json"
            else
                return 1
            fi
            ;;
        *) return 1 ;;
    esac
    [ -f "$locator" ] || return 1
    sed -n 's/^[[:space:]]*"data_home":[[:space:]]*"\(.*\)"[,]*[[:space:]]*$/\1/p' "$locator" | head -n 1
}

lexical_absolute_path() {
    printf '%s\n' "$1" | awk -F/ '
        {
            count = 0
            for (i = 1; i <= NF; i++) {
                if ($i == "" || $i == ".") continue
                if ($i == "..") {
                    if (count > 0) count--
                    continue
                }
                parts[++count] = $i
            }
            result = ""
            for (i = 1; i <= count; i++) result = result "/" parts[i]
            print (result == "" ? "/" : result)
        }
    '
}

canonicalize_absolute_path() {
    clean=$(lexical_absolute_path "$1") || return 1
    probe=$clean
    suffix=""
    while [ ! -d "$probe" ]; do
        name=${probe##*/}
        [ -n "$name" ] || return 1
        suffix="/$name$suffix"
        parent=${probe%/*}
        [ -n "$parent" ] || parent=/
        [ "$parent" != "$probe" ] || return 1
        probe=$parent
    done
    physical=$(CDPATH= cd -- "$probe" 2>/dev/null && pwd -P) || return 1
    if [ "$physical" = "/" ]; then
        printf '/%s\n' "${suffix#/}"
    else
        printf '%s%s\n' "$physical" "$suffix"
    fi
}

resolve_data_home() {
    explicit=$(explicit_data_home "$@")
    if [ -n "$explicit" ]; then
        DATA_HOME=$explicit
    elif is_data_home_reset "$@"; then
        DATA_HOME=$(CDPATH= cd -- "$APP_ROOT/.." && pwd)/localdata
    elif [ -n "${SAGE_DATA_HOME:-}" ]; then
        DATA_HOME=$SAGE_DATA_HOME
    else
        persisted=$(persisted_data_home 2>/dev/null || true)
        if [ -n "$persisted" ]; then
            DATA_HOME=$persisted
        else
            DATA_HOME=$(CDPATH= cd -- "$APP_ROOT/.." && pwd)/localdata
        fi
    fi
    case "$DATA_HOME" in
        /*) ;;
        *) fail "The localdata path must be absolute before the Python runtime can be installed: $DATA_HOME"; return 1 ;;
    esac
    unresolved_data_home=$DATA_HOME
    DATA_HOME=$(canonicalize_absolute_path "$unresolved_data_home") || {
        fail "The localdata path could not be resolved safely: $unresolved_data_home"
        return 1
    }
    case "$DATA_HOME/" in
        "$APP_ROOT/"*) fail "Refusing to install mutable runtime data inside the immutable app directory: $DATA_HOME"; return 1 ;;
    esac
    return 0
}

detect_platform() {
    HOST_SYSTEM=$(uname -s 2>/dev/null || printf 'UNKNOWN')
    HOST_ARCH=$(uname -m 2>/dev/null || printf 'UNKNOWN')
    case "$HOST_SYSTEM:$HOST_ARCH" in
        Darwin:arm64|Darwin:aarch64) PLATFORM_KEY=macos-arm64 ;;
        Darwin:x86_64) PLATFORM_KEY=macos-x86_64 ;;
        Linux:arm64|Linux:aarch64) PLATFORM_KEY=linux-arm64 ;;
        Linux:x86_64|Linux:amd64) PLATFORM_KEY=linux-x86_64 ;;
        *) fail "No approved SAGE Python runtime is pinned for $HOST_SYSTEM/$HOST_ARCH."; return 1 ;;
    esac
    return 0
}

python_matches_manifest() {
    candidate=$1
    [ -x "$candidate" ] || return 1
    "$candidate" -c "import platform,sys; raise SystemExit(0 if platform.python_implementation() == 'CPython' and platform.python_version() == '$PYTHON_VERSION' else 1)" >/dev/null 2>&1
}

python_matches_approved_minor() {
    candidate=$1
    [ -x "$candidate" ] || return 1
    "$candidate" -c "import platform,sys,venv; version=sys.version_info[:3]; minimum=tuple(map(int, '$HOST_PYTHON_MINIMUM'.split('.'))); maximum=tuple(map(int, '$PYTHON_VERSION'.split('.'))); raise SystemExit(0 if platform.python_implementation() == 'CPython' and minimum <= version <= maximum else 1)" >/dev/null 2>&1
}

python_version() {
    "$1" -c 'import platform; print(platform.python_version())' 2>/dev/null
}

python_org_candidate_is_trusted() {
    candidate=$1
    [ "$HOST_SYSTEM" = "Darwin" ] || return 1
    [ -x /usr/bin/codesign ] || return 1
    /usr/bin/codesign --verify --strict "$candidate" >/dev/null 2>&1 || return 1
    /usr/bin/codesign -dv --verbose=4 "$candidate" 2>&1 | awk -F= '
        $1 == "TeamIdentifier" && $2 == "BMM5U3QVKW" { trusted = 1 }
        END { exit(trusted ? 0 : 1) }
    '
}

homebrew_command() {
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

select_host_python() {
    [ "$HOST_SYSTEM" = "Darwin" ] || return 1
    python_org="/Library/Frameworks/Python.framework/Versions/$PYTHON_MINOR/bin/python$PYTHON_MINOR"
    if python_matches_approved_minor "$python_org" && python_org_candidate_is_trusted "$python_org"; then
        BOOTSTRAP_PYTHON=$python_org
        RUNTIME_PROVIDER=python.org
        RUNTIME_SOURCE_PATH=$python_org
        SELECTED_PYTHON_VERSION=$(python_version "$python_org")
        printf '%s\n' "Using approved Python.org CPython $SELECTED_PYTHON_VERSION at $python_org"
        return 0
    fi

    brew=$(homebrew_command 2>/dev/null || true)
    if [ -n "$brew" ]; then
        brew_prefix=$($brew --prefix "python@$PYTHON_MINOR" 2>/dev/null || true)
        brew_python="$brew_prefix/bin/python$PYTHON_MINOR"
        if [ -n "$brew_prefix" ] && python_matches_approved_minor "$brew_python"; then
            BOOTSTRAP_PYTHON=$brew_python
            RUNTIME_PROVIDER=homebrew
            RUNTIME_SOURCE_PATH=$brew_python
            SELECTED_PYTHON_VERSION=$(python_version "$brew_python")
            printf '%s\n' "Using approved Homebrew CPython $SELECTED_PYTHON_VERSION at $brew_python"
            return 0
        fi
    fi
    return 1
}

select_python_runtime() {
    RUNTIME_ROOT="$DATA_HOME/.system/runtime"
    MANAGED_PYTHON="$RUNTIME_ROOT/$PYTHON_PATH"
    if [ "$FORCE_REINSTALL" -eq 0 ]; then
        if ! has_macos_quarantine_tree "$RUNTIME_ROOT/python" && python_matches_manifest "$MANAGED_PYTHON"; then
            BOOTSTRAP_PYTHON=$MANAGED_PYTHON
            RUNTIME_PROVIDER=sage-managed
            RUNTIME_SOURCE_PATH=$MANAGED_PYTHON
            SELECTED_PYTHON_VERSION=$PYTHON_VERSION
            return 0
        fi
        if select_host_python; then
            return 0
        fi
    fi
    install_python_runtime || return 1
    BOOTSTRAP_PYTHON=$MANAGED_PYTHON
    RUNTIME_PROVIDER=sage-managed
    RUNTIME_SOURCE_PATH=$MANAGED_PYTHON
    SELECTED_PYTHON_VERSION=$PYTHON_VERSION
    return 0
}

install_homebrew_python() {
    brew=$(homebrew_command 2>/dev/null || true)
    if [ -z "$brew" ]; then
        fail "Homebrew is not installed. Install it from https://brew.sh, then launch SAGE again."
        return 1
    fi
    printf '%s\n' "Installing approved Python $PYTHON_MINOR with Homebrew..."
    if ! "$brew" install "python@$PYTHON_MINOR"; then
        fail "Homebrew could not install Python $PYTHON_MINOR. Review the Homebrew output, then retry or exit."
        return 1
    fi
    return 0
}

has_macos_quarantine() {
    target=$1
    [ "$HOST_SYSTEM" = "Darwin" ] || return 1
    [ -x /usr/bin/xattr ] || return 1
    /usr/bin/xattr -p com.apple.quarantine "$target" >/dev/null 2>&1
}

has_macos_quarantine_tree() {
    target=$1
    [ "$HOST_SYSTEM" = "Darwin" ] || return 1
    [ -x /usr/bin/xattr ] || return 1
    [ -e "$target" ] || return 1
    /usr/bin/xattr -r -p com.apple.quarantine "$target" >/dev/null 2>&1
}

macos_launch_quarantine_path() {
    [ "$HOST_SYSTEM" = "Darwin" ] || return 1
    [ -x /usr/bin/xattr ] || return 1
    for quarantine_candidate in \
        "$BUNDLE_ROOT" \
        "$APP_ROOT" \
        "$APP_ROOT/system/bin/sage" \
        "$APP_ROOT/system/tools/bootstrap_python.sh" \
        "$APP_ROOT/system/tools/bootstrap_runtime.py" \
        "$DATA_HOME" \
        "$DATA_HOME/.system/runtime/venv"
    do
        [ -e "$quarantine_candidate" ] || continue
        if /usr/bin/xattr -p com.apple.quarantine "$quarantine_candidate" >/dev/null 2>&1; then
            printf '%s\n' "$quarantine_candidate"
            return 0
        fi
    done
    if has_macos_quarantine_tree "$DATA_HOME/.system/runtime/venv"; then
        printf '%s\n' "$DATA_HOME/.system/runtime/venv"
        return 0
    fi
    return 1
}

clear_verified_archive_quarantine() {
    target=$1
    has_macos_quarantine "$target" || return 0
    /usr/bin/xattr -d com.apple.quarantine "$target" >/dev/null 2>&1 || {
        fail "macOS quarantined the SHA-256-verified Python runtime archive and SAGE could not clear that attribute without elevated privileges."
        return 1
    }
    if has_macos_quarantine "$target"; then
        fail "macOS retained quarantine on the SHA-256-verified Python runtime archive."
        return 1
    fi
    printf '%s\n' "Cleared macOS quarantine from the exact SHA-256-verified Python runtime archive."
    return 0
}

download_archive() {
    destination=$1
    part="$destination.part"
    printf '%s\n' "Downloading SAGE-approved CPython $PYTHON_VERSION for $PLATFORM_KEY..."
    if command -v curl >/dev/null 2>&1; then
        if [ -n "${SAGE_CA_BUNDLE:-}" ]; then
            curl -fL --retry 3 --connect-timeout 20 --cacert "$SAGE_CA_BUNDLE" -o "$part" "$RUNTIME_URL" || return 1
        else
            curl -fL --retry 3 --connect-timeout 20 -o "$part" "$RUNTIME_URL" || return 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if [ -n "${SAGE_CA_BUNDLE:-}" ]; then
            wget --ca-certificate="$SAGE_CA_BUNDLE" -O "$part" "$RUNTIME_URL" || return 1
        else
            wget -O "$part" "$RUNTIME_URL" || return 1
        fi
    else
        fail "Neither curl nor wget is available to download the approved SAGE Python runtime."
        return 1
    fi
    actual=$(sha256_file "$part") || {
        fail "No SHA-256 utility is available to verify the downloaded Python runtime."
        return 1
    }
    if [ "$actual" != "$RUNTIME_SHA256" ]; then
        fail "The downloaded Python runtime failed SHA-256 verification."
        return 1
    fi
    mv -f "$part" "$destination" || return 1
    return 0
}

install_python_runtime() {
    RUNTIME_ROOT="$DATA_HOME/.system/runtime"
    PYTHON_ROOT="$RUNTIME_ROOT/python"
    MANAGED_PYTHON="$RUNTIME_ROOT/$PYTHON_PATH"
    DOWNLOAD_ROOT="$RUNTIME_ROOT/downloads"
    ARCHIVE_PATH="$DOWNLOAD_ROOT/$ARCHIVE_NAME"

    if [ "$FORCE_REINSTALL" -eq 0 ]; then
        if has_macos_quarantine_tree "$PYTHON_ROOT"; then
            printf '%s\n' "The existing managed Python is quarantined; reinstalling it from the verified archive."
        elif python_matches_manifest "$MANAGED_PYTHON"; then
            return 0
        fi
    fi
    command -v tar >/dev/null 2>&1 || {
        fail "The platform tar utility is required to unpack the approved Python runtime."
        return 1
    }
    mkdir -p "$DOWNLOAD_ROOT" || {
        fail "SAGE could not create its runtime directory under localdata: $RUNTIME_ROOT"
        return 1
    }
    cached_sha=""
    if [ -f "$ARCHIVE_PATH" ]; then
        cached_sha=$(sha256_file "$ARCHIVE_PATH" 2>/dev/null || true)
    fi
    if [ "$cached_sha" != "$RUNTIME_SHA256" ]; then
        download_archive "$ARCHIVE_PATH" || {
            [ -n "$LAST_ERROR" ] || fail "The approved Python runtime download failed. Check the network/TLS connection and try Install again."
            return 1
        }
    fi
    clear_verified_archive_quarantine "$ARCHIVE_PATH" || return 1

    STAGE_ROOT="$RUNTIME_ROOT/.python-stage-$$"
    OLD_ROOT="$RUNTIME_ROOT/.python-old-$$"
    rm -rf "$STAGE_ROOT" "$OLD_ROOT"
    mkdir -p "$STAGE_ROOT" || {
        fail "SAGE could not create a temporary runtime installation directory."
        return 1
    }
    if ! tar -xzf "$ARCHIVE_PATH" -C "$STAGE_ROOT"; then
        rm -rf "$STAGE_ROOT"
        fail "The verified Python runtime archive could not be unpacked."
        return 1
    fi
    STAGED_PYTHON="$STAGE_ROOT/$PYTHON_PATH"
    if has_macos_quarantine_tree "$STAGE_ROOT/python"; then
        rm -rf "$STAGE_ROOT"
        fail "macOS quarantined the unpacked Python runtime even after verification; SAGE did not bypass Gatekeeper."
        return 1
    fi
    if ! python_matches_manifest "$STAGED_PYTHON"; then
        rm -rf "$STAGE_ROOT"
        fail "The unpacked Python runtime did not match CPython $PYTHON_VERSION."
        return 1
    fi
    if [ -e "$PYTHON_ROOT" ]; then
        mv "$PYTHON_ROOT" "$OLD_ROOT" || {
            rm -rf "$STAGE_ROOT"
            fail "The existing managed Python runtime could not be replaced safely."
            return 1
        }
    fi
    if ! mv "$STAGE_ROOT/python" "$PYTHON_ROOT"; then
        [ ! -e "$OLD_ROOT" ] || mv "$OLD_ROOT" "$PYTHON_ROOT"
        rm -rf "$STAGE_ROOT"
        fail "The new managed Python runtime could not be installed."
        return 1
    fi
    rm -rf "$OLD_ROOT" "$STAGE_ROOT"
    printf '%s\n' "Installed SAGE-approved CPython $PYTHON_VERSION at $PYTHON_ROOT"
    return 0
}

render_block_report() {
    printf '%s\n' \
        'SAGE RUNTIME INSTALLATION REPORT' \
        'Result: BLOCKED' \
        "Platform: $PLATFORM_KEY" \
        "Approved Python: CPython $PYTHON_VERSION" \
        "Reason: $LAST_ERROR" \
        'Available actions:' >&2
    if [ "$RECOVERY_ONLY" -eq 1 ]; then
        printf '%s\n' \
            '  1. Exit SAGE and follow the checksum-first macOS quarantine recovery guide' \
            'SAGE will not change or disable macOS security settings.' >&2
        return
    fi
    printf '%s\n' '  1. Install the SAGE Python runtime again' >&2
    if [ "$HOST_SYSTEM" = "Darwin" ] && homebrew_command >/dev/null 2>&1; then
        printf '%s\n' \
            "  2. Install approved Python $PYTHON_MINOR with Homebrew" \
            '  3. Exit SAGE' >&2
    else
        printf '%s\n' '  2. Exit SAGE' >&2
        if [ "$HOST_SYSTEM" = "Darwin" ]; then
            printf '%s\n' 'Homebrew option: unavailable because Homebrew is not installed (https://brew.sh).' >&2
        fi
    fi
}

request_retry_or_exit() {
    if [ "$RECOVERY_ONLY" -eq 1 ]; then
        printf '%s\n' 'macOS quarantine recovery is required before SAGE can start; exiting SAGE.' >&2
        return 1
    fi
    if [ ! -t 0 ]; then
        printf '%s\n' 'Non-interactive launch: exiting SAGE.' >&2
        return 1
    fi
    while :; do
        if [ "$HOST_SYSTEM" = "Darwin" ] && homebrew_command >/dev/null 2>&1; then
            printf '%s' 'Choose 1, 2, or 3: ' >&2
        else
            printf '%s' 'Choose 1 or 2: ' >&2
        fi
        IFS= read -r choice || return 1
        if [ "$choice" = "1" ]; then
            NEXT_ACTION=standalone
            return 0
        fi
        if [ "$HOST_SYSTEM" = "Darwin" ] && homebrew_command >/dev/null 2>&1; then
            case "$choice" in
                2) NEXT_ACTION=homebrew; return 0 ;;
                3) return 1 ;;
                *) printf '%s\n' 'Enter 1 to install again, 2 for Homebrew, or 3 to exit.' >&2 ;;
            esac
        else
            case "$choice" in
                2) return 1 ;;
                *) printf '%s\n' 'Enter 1 to install again or 2 to exit.' >&2 ;;
            esac
        fi
    done
}

prepare_install() {
    LAST_ERROR=""
    HOST_SYSTEM=UNKNOWN
    HOST_ARCH=UNKNOWN
    PLATFORM_KEY=UNKNOWN
    PYTHON_VERSION=UNKNOWN
    PYTHON_MINOR=UNKNOWN
    HOST_PYTHON_MINIMUM=UNKNOWN
    ARCHIVE_NAME=""
    PYTHON_PATH=""
    RUNTIME_SHA256=""
    RUNTIME_URL=""
    DATA_HOME=""
    RECOVERY_ONLY=0
    detect_platform || return 1
    [ -f "$MANIFEST" ] || {
        fail "The governed Python runtime manifest is missing: $MANIFEST"
        return 1
    }
    PYTHON_VERSION=$(manifest_global python_version 2>/dev/null || true)
    PYTHON_MINOR=${PYTHON_VERSION%.*}
    HOST_PYTHON_MINIMUM=$(manifest_global host_python_minimum_version 2>/dev/null || true)
    ARCHIVE_NAME=$(manifest_artifact "$PLATFORM_KEY" archive_name 2>/dev/null || true)
    PYTHON_PATH=$(manifest_artifact "$PLATFORM_KEY" python_path 2>/dev/null || true)
    RUNTIME_SHA256=$(manifest_artifact "$PLATFORM_KEY" sha256 2>/dev/null || true)
    RUNTIME_URL=$(manifest_artifact "$PLATFORM_KEY" url 2>/dev/null || true)
    if [ -z "$PYTHON_VERSION" ] || [ -z "$HOST_PYTHON_MINIMUM" ] || [ -z "$ARCHIVE_NAME" ] || [ -z "$PYTHON_PATH" ] || [ -z "$RUNTIME_SHA256" ] || [ -z "$RUNTIME_URL" ]; then
        fail "The governed Python runtime manifest has no complete entry for $PLATFORM_KEY."
        return 1
    fi
    resolve_data_home "$@" || return 1
    quarantined_path=$(macos_launch_quarantine_path 2>/dev/null || true)
    if [ -n "$quarantined_path" ]; then
        RECOVERY_ONLY=1
        fail "macOS quarantine is attached to the SAGE launch/runtime boundary: $quarantined_path. SAGE stopped before installing or importing native Python dependencies and did not bypass Gatekeeper. Verify the release checksum, then follow app/docs/macos-linux/RECOVERY.md to authorize this exact SAGE copy."
        return 1
    fi
    return 0
}

while :; do
    if [ "$NEXT_ACTION" = "homebrew" ]; then
        NEXT_ACTION=attempt
        LAST_ERROR=""
        if ! install_homebrew_python; then
            render_block_report
            if ! request_retry_or_exit; then
                exit 2
            fi
            continue
        fi
        FORCE_REINSTALL=0
    elif [ "$NEXT_ACTION" = "standalone" ]; then
        NEXT_ACTION=attempt
        FORCE_REINSTALL=1
    fi
    if prepare_install "$@" && select_python_runtime; then
        export SAGE_DATA_HOME="$DATA_HOME"
        export SAGE_MANAGED_PYTHON_VERSION="$SELECTED_PYTHON_VERSION"
        export SAGE_MANAGED_PYTHON_PLATFORM="$PLATFORM_KEY"
        export SAGE_PYTHON_RUNTIME_PROVIDER="$RUNTIME_PROVIDER"
        export SAGE_PYTHON_RUNTIME_PATH="$RUNTIME_SOURCE_PATH"
        if [ "$RUNTIME_PROVIDER" = "sage-managed" ]; then
            export SAGE_MANAGED_PYTHON_SHA256="$RUNTIME_SHA256"
        else
            unset SAGE_MANAGED_PYTHON_SHA256 2>/dev/null || true
        fi
        if [ "$FORCE_REINSTALL" -eq 1 ]; then
            export SAGE_FORCE_RUNTIME_REINSTALL=1
        else
            unset SAGE_FORCE_RUNTIME_REINSTALL 2>/dev/null || true
        fi
        export PYTHONDONTWRITEBYTECODE=1
        "$BOOTSTRAP_PYTHON" "$BOOTSTRAP_SCRIPT" "$APP_ROOT" "$PROFILE"
        bootstrap_status=$?
        if [ "$bootstrap_status" -eq 0 ]; then
            VENV_PYTHON="$DATA_HOME/.system/runtime/venv/bin/python"
            export PYTHONPATH="$APP_ROOT/system/src${PYTHONPATH:+:$PYTHONPATH}"
            cd "$APP_ROOT" || exit 2
            if [ "$MODE" = "python-shell" ]; then
                exec "$VENV_PYTHON" "$@"
            fi
            exec "$VENV_PYTHON" -m sage.cli "$@"
        fi
        LAST_ERROR="The managed environment or its pinned dependencies failed validation."
    fi
    render_block_report
    if ! request_retry_or_exit; then
        exit 2
    fi
    LAST_ERROR=""
done
