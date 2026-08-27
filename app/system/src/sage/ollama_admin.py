"""Host-local Ollama lifecycle and fixed SAGE admin-model provisioning."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import certifi

from . import __version__
from .atomic import atomic_write_json, atomic_write_text
from .errors import ConfigurationError, ValidationError
from .storage import storage_layout
from .executors.base import ProviderRequest
from .executors.http import get_json
from .executors.ollama import OllamaExecutor
from .llm_settings import load_llm_settings, set_local_admin_enabled
from .ollama_policy import (
    SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
    SAGE_LOCAL_ADMIN_INSTALL_FREE_BYTES,
    SAGE_LOCAL_ADMIN_KEEP_ALIVE,
    SAGE_LOCAL_ADMIN_MIN_RAM_BYTES,
    SAGE_LOCAL_ADMIN_MODEL,
    SAGE_LOCAL_ADMIN_SOURCE_BYTES,
    SAGE_LOCAL_ADMIN_SOURCE_FILENAME,
    SAGE_LOCAL_ADMIN_SOURCE_REPOSITORY,
    SAGE_LOCAL_ADMIN_SOURCE_REVISION,
    SAGE_LOCAL_ADMIN_SOURCE_SHA256,
    SAGE_LOCAL_ADMIN_SOURCE_URL,
)


ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class OllamaAdminStatus:
    """One non-mutating view of the local Ollama admin-assistant state."""

    installed: bool
    executable: str | None
    version: str | None
    service_running: bool
    service_ownership: str
    endpoint: str
    model: str
    model_installed: bool
    context_window: int
    total_ram_bytes: int | None
    available_ram_bytes: int | None
    ram_ready: bool
    enabled: bool
    ready: bool
    diagnostic: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready status row."""
        return asdict(self)


class OllamaAdminService:
    """Install and manage Ollama without granting it governed workflow authority."""

    # Lifecycle methods deliberately share one service instance so process ownership
    # cannot be inferred from a broad process-name match after navigating menus.

    def __init__(self, root: Path) -> None:
        """Bind host-local receipts, logs, and managed-process state to one workspace."""
        self.root = root.expanduser().resolve()
        self.state_root = storage_layout(self.root).state_root
        self.runtime_receipt = self.state_root / "ollama-runtime.json"
        self.model_receipt = self.state_root / "ollama-model.json"
        self.log_path = self.state_root / "logs" / "ollama.log"
        self._managed_process: subprocess.Popen[str] | None = None

    @staticmethod
    def _known_executables() -> tuple[Path, ...]:
        """Return normal per-platform Ollama executable locations."""
        system = platform.system()
        if system == "Windows":
            local = Path(os.environ.get("LOCALAPPDATA", ""))
            return (
                local / "Programs" / "Ollama" / "ollama.exe",
                Path("C:/Program Files/Ollama/ollama.exe"),
            )
        if system == "Darwin":
            return (
                Path("/opt/homebrew/bin/ollama"),
                Path("/usr/local/bin/ollama"),
                Path("/Applications/Ollama.app/Contents/Resources/ollama"),
            )
        return (Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"))

    def executable(self) -> Path | None:
        """Detect an explicit override, PATH command, or normal installed binary."""
        override = os.environ.get("SAGE_OLLAMA_COMMAND", "").strip()
        if override:
            path = Path(override).expanduser()
            return path.resolve() if path.is_file() else None
        discovered = shutil.which("ollama")
        if discovered:
            return Path(discovered).resolve()
        return next((path for path in self._known_executables() if path.is_file()), None)

    @staticmethod
    def _memory_bytes() -> tuple[int | None, int | None]:
        """Return total and currently available physical memory without dependencies."""
        system = platform.system()
        if system == "Windows":
            class MemoryStatus(ctypes.Structure):
                """Mirror the Windows MEMORYSTATUSEX structure used by the kernel API."""

                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong),
                    ("avail_phys", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("avail_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended_virtual", ctypes.c_ulonglong),
                ]

            row = MemoryStatus()
            row.length = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(row)):
                return int(row.total_phys), int(row.avail_phys)
            return None, None

        if system == "Darwin":
            total: int | None = None
            try:
                total_result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=5,
                )
                if total_result.returncode == 0:
                    total = int(total_result.stdout.strip())
            except (OSError, subprocess.SubprocessError, ValueError):
                total = None
            try:
                result = subprocess.run(
                    ["vm_stat"], text=True, capture_output=True, check=False, timeout=5
                )
                page_match = re.search(r"page size of (\d+) bytes", result.stdout)
                vm_page_size = int(page_match.group(1)) if page_match else 4096
                available_pages = 0
                for label in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
                    match = re.search(rf"^{re.escape(label)}:\s+(\d+)\.", result.stdout, re.MULTILINE)
                    if match:
                        available_pages += int(match.group(1))
                available = available_pages * vm_page_size if available_pages else None
                return total, available
            except (OSError, subprocess.SubprocessError, ValueError):
                return total, None

        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            total = page_size * int(os.sysconf("SC_PHYS_PAGES"))
        except (AttributeError, OSError, ValueError):
            return None, None
        try:
            return total, page_size * int(os.sysconf("SC_AVPHYS_PAGES"))
        except (AttributeError, OSError, ValueError):
            return total, None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        """Read a local lifecycle receipt without turning absence into setup failure."""
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(value) if isinstance(value, dict) else {}

    def _version(self, executable: Path | None) -> str | None:
        """Return the installed Ollama client version without starting its service."""
        if executable is None:
            return None
        try:
            result = subprocess.run(
                [str(executable), "--version"],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        text = (result.stdout or result.stderr).strip()
        match = re.search(r"(?:client|ollama) version(?: is)?\s+v?([0-9][0-9A-Za-z.-]*)", text, re.I)
        return match.group(1) if match else (text.splitlines()[-1] if text else None)

    def _api_rows(self, endpoint: str) -> tuple[bool, tuple[dict[str, Any], ...]]:
        """Probe the loopback API and return its installed-model rows."""
        try:
            version = get_json(f"{endpoint}/api/version", timeout=2)
            tags = get_json(f"{endpoint}/api/tags", timeout=4)
        except ValidationError:
            return False, ()
        if not isinstance(version, dict) or not isinstance(tags, dict):
            return False, ()
        rows = tuple(item for item in tags.get("models", []) if isinstance(item, dict))
        return True, rows

    def _managed_ownership(self, running: bool) -> str:
        """Distinguish this session's exact child process from an external service."""
        if not running:
            return "STOPPED"
        if self._managed_process is not None and self._managed_process.poll() is None:
            return "SAGE_MANAGED"
        return "EXTERNAL"

    def status(self) -> OllamaAdminStatus:
        """Detect Ollama, its API, model, RAM, and SAGE enablement without mutation."""
        settings = load_llm_settings(self.root)
        item = settings["providers"]["ollama"]
        endpoint = str(item["endpoint"])
        executable = self.executable()
        running, rows = self._api_rows(endpoint)
        names = {
            str(row.get("name") or row.get("model") or "").removesuffix(":latest")
            for row in rows
        }
        model_name = SAGE_LOCAL_ADMIN_MODEL.removesuffix(":latest")
        receipt = self._read_json(self.model_receipt)
        model_installed = (
            model_name in names
            if running
            else (
                receipt.get("model") == SAGE_LOCAL_ADMIN_MODEL
                and receipt.get("source_sha256") == SAGE_LOCAL_ADMIN_SOURCE_SHA256
            )
        )
        total_ram, available_ram = self._memory_bytes()
        ram_ready = total_ram is not None and total_ram >= SAGE_LOCAL_ADMIN_MIN_RAM_BYTES
        enabled = bool(item.get("admin_assistant_enabled", False))
        ready = bool(executable and running and model_installed and ram_ready and enabled)
        if executable is None:
            diagnostic = "Ollama is not installed."
        elif not running:
            diagnostic = "Ollama is installed but its local service is stopped."
        elif not model_installed:
            diagnostic = "Ollama running; governed SAGE model not installed."
        elif not ram_ready:
            diagnostic = "The model is installed but this host has less than 16 GiB RAM."
        elif not enabled:
            diagnostic = "Ollama is running with the governed SAGE model."
        else:
            diagnostic = "The local SAGE admin assistant is ready."
        return OllamaAdminStatus(
            installed=executable is not None,
            executable=str(executable) if executable else None,
            version=self._version(executable),
            service_running=running,
            service_ownership=self._managed_ownership(running),
            endpoint=endpoint,
            model=SAGE_LOCAL_ADMIN_MODEL,
            model_installed=model_installed,
            context_window=SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
            total_ram_bytes=total_ram,
            available_ram_bytes=available_ram,
            ram_ready=ram_ready,
            enabled=enabled,
            ready=ready,
            diagnostic=diagnostic,
        )

    @staticmethod
    def _https_context() -> ssl.SSLContext:
        """Build a verified HTTPS context from host roots plus SAGE's portable CA bundle."""
        context = ssl.create_default_context()
        override = os.environ.get("SAGE_CA_BUNDLE", "").strip()
        bundle = Path(override).expanduser() if override else Path(certifi.where())
        if not bundle.is_file():
            raise ValidationError(
                f"The configured HTTPS CA bundle does not exist: {bundle}",
                code="OLLAMA_CA_BUNDLE_INVALID",
                next_action=(
                    "Set SAGE_CA_BUNDLE to an authorized PEM CA bundle for this host or proxy, "
                    "then restart SAGE."
                ),
            )
        try:
            context.load_verify_locations(cafile=str(bundle))
        except (OSError, ssl.SSLError) as exc:
            raise ValidationError(
                f"The configured HTTPS CA bundle could not be loaded: {bundle}: {exc}",
                code="OLLAMA_CA_BUNDLE_INVALID",
                next_action=(
                    "Provide an authorized PEM CA bundle through SAGE_CA_BUNDLE, then restart SAGE."
                ),
            ) from exc
        return context

    @staticmethod
    def _download(url: str, destination: Path, progress: ProgressCallback | None = None) -> None:
        """Download one approved artifact with bounded progress reporting."""
        request = urllib.request.Request(url, headers={"User-Agent": f"SAGE/{__version__}"})
        context = OllamaAdminService._https_context()
        try:
            with urllib.request.urlopen(
                request,
                timeout=60,
                context=context,
            ) as response, destination.open("wb") as output:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            destination.unlink(missing_ok=True)
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            certificate_failure = isinstance(reason, ssl.SSLCertVerificationError) or (
                "CERTIFICATE_VERIFY_FAILED" in str(exc)
            )
            raise ValidationError(
                f"Download failed: {url}: {exc}",
                code="OLLAMA_DOWNLOAD_FAILED",
                next_action=(
                    "Set SAGE_CA_BUNDLE to an authorized PEM CA bundle for this host or proxy, "
                    "restart SAGE, then retry. Do not disable TLS verification."
                    if certificate_failure
                    else "Check the internet connection or proxy configuration, then retry."
                ),
            ) from exc

    def install_runtime(self, progress: ProgressCallback | None = None) -> dict[str, Any]:
        """Run the official platform installer after caller consent."""
        existing = self.executable()
        if existing is not None:
            return {"status": "ALREADY_INSTALLED", "executable": str(existing)}
        system = platform.system()
        installer_root = storage_layout(self.root).system_root / "installers"
        installer_root.mkdir(parents=True, exist_ok=True)
        if system == "Darwin":
            destination = installer_root / "Ollama.dmg"
            self._download("https://ollama.com/download/Ollama.dmg", destination, progress)
            result = subprocess.run(["open", str(destination)], check=False, timeout=30)
            if result.returncode != 0:
                raise ValidationError("Could not open the Ollama macOS installer", code="OLLAMA_INSTALL_FAILED")
            return {
                "status": "OPERATOR_ACTION_REQUIRED",
                "installer": str(destination),
                "next_action": "Drag Ollama to Applications, start it once, then return to SAGE status.",
            }
        if system == "Windows":
            destination = installer_root / "OllamaSetup.exe"
            self._download("https://ollama.com/download/OllamaSetup.exe", destination, progress)
            result = subprocess.run([str(destination)], check=False, timeout=900)
            if result.returncode != 0:
                raise ValidationError("The Ollama Windows installer failed", code="OLLAMA_INSTALL_FAILED")
            destination.unlink(missing_ok=True)
            return {"status": "INSTALLED", "executable": str(self.executable() or "")}
        if system == "Linux":
            destination = installer_root / "ollama-install.sh"
            self._download("https://ollama.com/install.sh", destination, progress)
            result = subprocess.run(["sh", str(destination)], check=False, timeout=900)
            destination.unlink(missing_ok=True)
            if result.returncode != 0:
                raise ValidationError("The Ollama Linux installer failed", code="OLLAMA_INSTALL_FAILED")
            return {"status": "INSTALLED", "executable": str(self.executable() or "")}
        raise ConfigurationError(f"Ollama installation is not supported on {system}")

    def start(self) -> OllamaAdminStatus:
        """Start one SAGE-managed Ollama server unless an external service already runs."""
        current = self.status()
        if current.service_running:
            return current
        executable = self.executable()
        if executable is None:
            raise ValidationError(
                "Ollama is not installed",
                code="OLLAMA_NOT_INSTALLED",
                next_action="Install Ollama from the Local Admin Assistant menu.",
            )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("a", encoding="utf-8")
        kwargs: dict[str, Any] = {
            "cwd": str(self.root),
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
            "text": True,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            self._managed_process = subprocess.Popen([str(executable), "serve"], **kwargs)
        finally:
            log.close()
        atomic_write_json(
            self.runtime_receipt,
            {
                "schema_version": "1.0",
                "ownership": "SAGE_MANAGED",
                "pid": self._managed_process.pid,
                "executable": str(executable),
                "endpoint": current.endpoint,
                "started_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        for _ in range(40):
            if self._managed_process.poll() is not None:
                break
            running, _ = self._api_rows(current.endpoint)
            if running:
                return self.status()
            time.sleep(0.25)
        raise ValidationError(
            "Ollama did not start its local API",
            code="OLLAMA_START_FAILED",
            next_action=f"Review {self.log_path}",
        )

    def stop(self) -> OllamaAdminStatus:
        """Stop only an Ollama process owned by this SAGE control-center session."""
        current = self.status()
        if not current.service_running:
            self.runtime_receipt.unlink(missing_ok=True)
            return current
        process = self._managed_process
        if process is None or process.poll() is not None:
            raise ValidationError(
                "The running Ollama service was not started by this SAGE session",
                code="OLLAMA_EXTERNAL_SERVICE_RUNNING",
                next_action="Stop the external Ollama tray application or system service, then refresh status.",
            )
        if platform.system() == "Windows":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise ValidationError(
                "Ollama did not stop within 10 seconds",
                code="OLLAMA_STOP_TIMEOUT",
                next_action=f"Review {self.log_path} and stop the exact recorded process manually.",
            ) from exc
        self.runtime_receipt.unlink(missing_ok=True)
        self._managed_process = None
        return self.status()

    def install_model(self, progress: ProgressCallback | None = None) -> OllamaAdminStatus:
        """Download, hash-verify, and import the fixed Q5_K_M GGUF into Ollama."""
        current = self.status()
        if not current.service_running:
            current = self.start()
        executable = self.executable()
        if executable is None:
            raise ValidationError("Ollama is not installed", code="OLLAMA_NOT_INSTALLED")
        free = shutil.disk_usage(self.root).free
        if free < SAGE_LOCAL_ADMIN_INSTALL_FREE_BYTES:
            raise ValidationError(
                "At least 10 GiB free disk space is required while importing the SAGE model",
                code="OLLAMA_MODEL_DISK_SPACE_INSUFFICIENT",
                details={"free_bytes": free, "required_bytes": SAGE_LOCAL_ADMIN_INSTALL_FREE_BYTES},
            )
        with tempfile.TemporaryDirectory(prefix="sage-ollama-model-") as temporary:
            directory = Path(temporary)
            gguf = directory / SAGE_LOCAL_ADMIN_SOURCE_FILENAME
            self._download(SAGE_LOCAL_ADMIN_SOURCE_URL, gguf, progress)
            hasher = hashlib.sha256()
            with gguf.open("rb") as source:
                while block := source.read(1024 * 1024):
                    hasher.update(block)
            digest = hasher.hexdigest()
            if digest != SAGE_LOCAL_ADMIN_SOURCE_SHA256:
                raise ValidationError(
                    "The downloaded GGUF failed its governed SHA-256 check",
                    code="OLLAMA_MODEL_HASH_MISMATCH",
                    details={"expected": SAGE_LOCAL_ADMIN_SOURCE_SHA256, "actual": digest},
                )
            modelfile = directory / "Modelfile"
            atomic_write_text(modelfile, f"FROM {gguf}\n")
            result = subprocess.run(
                [str(executable), "create", SAGE_LOCAL_ADMIN_MODEL, "-f", str(modelfile)],
                text=True,
                capture_output=True,
                check=False,
                timeout=1800,
            )
            if result.returncode != 0:
                raise ValidationError(
                    result.stderr.strip() or "Ollama could not import the governed GGUF",
                    code="OLLAMA_MODEL_IMPORT_FAILED",
                )
        running, rows = self._api_rows(current.endpoint)
        row = next(
            (
                item
                for item in rows
                if str(item.get("name") or item.get("model") or "").removesuffix(":latest")
                == SAGE_LOCAL_ADMIN_MODEL.removesuffix(":latest")
            ),
            {},
        )
        if not running or not row:
            raise ValidationError("Imported Ollama model was not discoverable", code="OLLAMA_MODEL_NOT_READY")
        atomic_write_json(
            self.model_receipt,
            {
                "schema_version": "1.0",
                "model": SAGE_LOCAL_ADMIN_MODEL,
                "ollama_digest": row.get("digest"),
                "quantization": "Q5_K_M",
                "source_repository": SAGE_LOCAL_ADMIN_SOURCE_REPOSITORY,
                "source_revision": SAGE_LOCAL_ADMIN_SOURCE_REVISION,
                "source_filename": SAGE_LOCAL_ADMIN_SOURCE_FILENAME,
                "source_sha256": SAGE_LOCAL_ADMIN_SOURCE_SHA256,
                "source_bytes": SAGE_LOCAL_ADMIN_SOURCE_BYTES,
                "installed_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        return self.status()

    def enable(self, enabled: bool) -> OllamaAdminStatus:
        """Change admin-assistant enablement only after RAM and model checks."""
        current = self.status()
        if enabled and not current.ram_ready:
            raise ValidationError(
                "The local admin assistant requires at least 16 GiB system RAM",
                code="LOCAL_LLM_INSUFFICIENT_MEMORY",
            )
        if enabled and not current.model_installed:
            raise ValidationError("The governed local model is not installed", code="OLLAMA_MODEL_NOT_READY")
        set_local_admin_enabled(self.root, enabled)
        return self.status()

    def test(self) -> dict[str, Any]:
        """Run one schema-constrained local response without enabling workflow execution."""
        current = self.status()
        if not current.ready:
            raise ValidationError(current.diagnostic, code="OLLAMA_ADMIN_ASSISTANT_NOT_READY")
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["status"],
            "properties": {"status": {"type": "string", "const": "OK"}},
        }
        response = OllamaExecutor(
            current.endpoint,
            context_window=SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
            keep_alive=SAGE_LOCAL_ADMIN_KEEP_ALIVE,
        ).execute(
            ProviderRequest(
                prompt="Return exactly one JSON object with status set to OK.",
                schema=schema,
                model=SAGE_LOCAL_ADMIN_MODEL,
                timeout_seconds=120,
            )
        )
        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as exc:
            raise ValidationError("Local assistant returned invalid JSON", code="OLLAMA_TEST_FAILED") from exc
        if payload != {"status": "OK"}:
            raise ValidationError("Local assistant returned an invalid test result", code="OLLAMA_TEST_FAILED")
        return {"status": "READY", "model": response.model, "metadata": response.metadata}
