"""Local Ollama admin-assistant lifecycle and provisioning contracts."""

from __future__ import annotations

import hashlib
import io
import json
import ssl
import subprocess
import urllib.error
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sage.errors import ValidationError
from sage.ollama_admin import OllamaAdminService, OllamaAdminStatus
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.ollama_policy import (
    SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
    SAGE_LOCAL_ADMIN_MIN_RAM_BYTES,
    SAGE_LOCAL_ADMIN_MODEL,
    SAGE_LOCAL_ADMIN_SOURCE_REVISION,
    SAGE_LOCAL_ADMIN_SOURCE_URL,
)


def _app_root(tmp_path: Path) -> Path:
    """Return a disposable app root whose localdata remains in its bundle."""
    root = tmp_path / "SAGE" / "app"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _status(*, running: bool, installed: bool = True, model_installed: bool = False) -> OllamaAdminStatus:
    """Return a concise test status row."""
    return OllamaAdminStatus(
        installed=installed,
        executable="/fixture/ollama" if installed else None,
        version="0.32.5" if installed else None,
        service_running=running,
        service_ownership="SAGE_MANAGED" if running else "STOPPED",
        endpoint="http://127.0.0.1:11434",
        model=SAGE_LOCAL_ADMIN_MODEL,
        model_installed=model_installed,
        context_window=SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
        total_ram_bytes=SAGE_LOCAL_ADMIN_MIN_RAM_BYTES,
        available_ram_bytes=8 * 1024**3,
        ram_ready=True,
        enabled=False,
        ready=False,
        diagnostic="fixture",
    )


def test_status_detects_existing_host_runtime_model_and_ram(tmp_path: Path, monkeypatch) -> None:
    """Host detection runs before installation and reports every readiness component."""
    executable = tmp_path / "ollama"
    executable.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("SAGE_OLLAMA_COMMAND", str(executable))
    service = OllamaAdminService(_app_root(tmp_path))
    monkeypatch.setattr(service, "_version", lambda _path: "0.32.5")
    monkeypatch.setattr(
        service,
        "_api_rows",
        lambda _endpoint: (
            True,
            ({"name": SAGE_LOCAL_ADMIN_MODEL, "digest": "fixture-digest"},),
        ),
    )
    monkeypatch.setattr(
        service,
        "_memory_bytes",
        lambda: (SAGE_LOCAL_ADMIN_MIN_RAM_BYTES, 8 * 1024**3),
    )

    status = service.status()

    assert status.installed is True
    assert status.service_running is True
    assert status.service_ownership == "EXTERNAL"
    assert status.model_installed is True
    assert status.ram_ready is True
    assert status.enabled is False
    assert status.diagnostic == "Ollama is running with the governed SAGE model."

    monkeypatch.setattr(service, "_api_rows", lambda _endpoint: (True, ()))
    missing_model = service.status()
    assert missing_model.diagnostic == "Ollama running; governed SAGE model not installed."


def test_local_admin_menu_hides_runtime_install_when_ollama_is_running(make_workspace) -> None:
    """A detected running Ollama service exposes model setup without a redundant host installer."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.ollama_admin = SimpleNamespace(status=lambda: _status(running=True))

    center.local_admin_assistant_menu()

    rendered = output.getvalue()
    assert rendered.index("Configure Local AI") < rendered.index("Local AI")
    assert rendered.index("Model") < rendered.index("Local AI actions")
    assert "Model                 sage-gemma4-e2b:q5_k_m - NOT INSTALLED" in rendered
    assert "Ollama                INSTALLED" not in rendered
    assert "Service               RUNNING" not in rendered
    assert "Governed model" not in rendered
    assert "Enablement" not in rendered
    assert "Binary:" not in rendered
    assert "Context:" not in rendered
    assert "Authority:" not in rendered
    assert "Reporting:" not in rendered
    assert "Refresh status" not in rendered
    assert "Install Ollama on this host" not in rendered
    assert "1. Enable Local AI" in rendered
    assert "2. Stop Ollama" in rendered
    assert "3. Manage Local AI models" in rendered
    assert "4. Test Local AI" in rendered
    assert "Model source and integrity" not in rendered


def test_local_admin_menu_offers_runtime_install_only_when_ollama_is_absent(make_workspace) -> None:
    """A host without an Ollama runtime retains the official installation action."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.ollama_admin = SimpleNamespace(status=lambda: _status(running=False, installed=False))

    center.local_admin_assistant_menu()

    rendered = output.getvalue()
    assert "> Local AI actions" in rendered
    assert "1. Enable Local AI" in rendered
    assert "2. Install Ollama on this host" in rendered
    assert "3. Manage Local AI models" in rendered
    assert "4. Test Local AI" in rendered


def test_local_model_management_owns_model_source_and_integrity_information(make_workspace) -> None:
    """Model metadata is information in the extensible model menu, not a parent-menu action."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["3", "a", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.ollama_admin = SimpleNamespace(status=lambda: _status(running=True))

    center.local_admin_assistant_menu()

    rendered = output.getvalue()
    assert "Configure Local AI models" in rendered
    assert rendered.index("Configured model") < rendered.index("Model actions")
    assert rendered.index("Source") < rendered.index("Model actions")
    assert rendered.index("Integrity") < rendered.index("Model actions")
    assert "1. Install configured model" in rendered


def test_local_admin_actions_refresh_state_without_a_refresh_option(make_workspace) -> None:
    """Completing a toggle immediately rerenders the newly persisted Local AI state."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()

    class FakeAdmin:
        """Provide one mutable Local AI switch for menu refresh coverage."""

        enabled = False

        def status(self):
            """Return the current switch state."""
            return replace(_status(running=True, model_installed=True), enabled=self.enabled)

        def enable(self, value):
            """Persist the requested fixture switch state."""
            self.enabled = value

    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.ollama_admin = FakeAdmin()

    center.local_admin_assistant_menu()

    rendered = output.getvalue()
    assert rendered.index("Local AI              DISABLED") < rendered.index(
        "Local AI              ENABLED"
    )
    assert "Refresh status" not in rendered


def test_local_admin_service_action_cycles_start_and_stop(make_workspace) -> None:
    """One fixed action position cycles between starting and stopping Ollama."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()

    class FakeAdmin:
        """Provide mutable service state for the cycle-action contract."""

        running = False

        def status(self):
            """Return the current service state."""
            return _status(running=self.running)

        def start(self):
            """Start the fixture service."""
            self.running = True

        def stop(self):
            """Stop the fixture service."""
            self.running = False

    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["2", "2", "y", "a"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.ollama_admin = FakeAdmin()

    center.local_admin_assistant_menu()

    rendered = output.getvalue()
    assert rendered.index("2. Start Ollama") < rendered.index("2. Stop Ollama")


def test_model_download_uses_verified_portable_ca_context(tmp_path: Path, monkeypatch) -> None:
    """Remote model downloads use a populated, hostname-checking CA context."""
    destination = tmp_path / "fixture.gguf"
    captured: dict[str, object] = {}

    class Response:
        """Provide one bounded HTTPS response without network access."""

        headers = {"Content-Length": "7"}

        def __init__(self) -> None:
            """Initialize one data block followed by an end-of-stream marker."""
            self.blocks = iter((b"fixture", b""))

        def __enter__(self):
            """Enter the response context used by the downloader."""
            return self

        def __exit__(self, *_args):
            """Leave the response context without suppressing exceptions."""
            return False

        def read(self, _size: int) -> bytes:
            """Return the next bounded response block."""
            return next(self.blocks)

    def fake_urlopen(request, *, timeout, context):
        """Capture the downloader's request controls and return the fixture response."""
        captured.update(request=request, timeout=timeout, context=context)
        return Response()

    monkeypatch.delenv("SAGE_CA_BUNDLE", raising=False)
    monkeypatch.setattr("sage.ollama_admin.urllib.request.urlopen", fake_urlopen)

    OllamaAdminService._download("https://example.test/model.gguf", destination)

    context = captured["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.get_ca_certs()
    assert destination.read_bytes() == b"fixture"


def test_certificate_failure_explains_authorised_ca_bundle_override(tmp_path: Path, monkeypatch) -> None:
    """TLS-chain failures point to a secure custom-CA route instead of disabling verification."""
    def fail_urlopen(_request, *, timeout, context):
        """Raise the certificate-chain failure produced by urllib on an untrusted host."""
        del timeout, context
        reason = ssl.SSLCertVerificationError(1, "certificate verify failed")
        raise urllib.error.URLError(reason)

    monkeypatch.delenv("SAGE_CA_BUNDLE", raising=False)
    monkeypatch.setattr("sage.ollama_admin.urllib.request.urlopen", fail_urlopen)

    with pytest.raises(ValidationError) as raised:
        OllamaAdminService._download("https://example.test/model.gguf", tmp_path / "fixture.gguf")

    error = raised.value
    assert error.code == "OLLAMA_DOWNLOAD_FAILED"
    assert "SAGE_CA_BUNDLE" in str(error.next_action)
    assert "Do not disable TLS verification" in str(error.next_action)


def test_start_and_stop_manage_only_the_process_started_by_sage(tmp_path: Path, monkeypatch) -> None:
    """SAGE starts and stops its exact Ollama child without broad process matching."""
    executable = tmp_path / "ollama"
    executable.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("SAGE_OLLAMA_COMMAND", str(executable))
    service = OllamaAdminService(_app_root(tmp_path))
    statuses = iter((_status(running=False), _status(running=True), _status(running=True), _status(running=False)))
    monkeypatch.setattr(service, "status", lambda: next(statuses))
    monkeypatch.setattr(service, "_api_rows", lambda _endpoint: (True, ()))

    class FakeProcess:
        """Provide the bounded process methods used by lifecycle start and stop."""

        pid = 321

        def __init__(self) -> None:
            """Create one initially running fake child process."""
            self.returncode = None
            self.terminated = False

        def poll(self):
            """Return the current fake child completion state."""
            return self.returncode

        def terminate(self):
            """Record a graceful POSIX-style termination request."""
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            """Complete the fake child within the requested bounded wait."""
            self.returncode = 0
            return 0

    process = FakeProcess()
    calls: list[list[str]] = []

    def fake_popen(args, **_kwargs):
        """Capture the exact child command while avoiding a real Ollama process."""
        calls.append([str(value) for value in args])
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    assert service.start().service_running is True
    assert calls == [[str(executable.resolve()), "serve"]]
    assert service.stop().service_running is False
    assert process.terminated is True


def test_governed_model_source_pins_immutable_revision() -> None:
    """A governed hash never follows the mutable upstream main branch."""
    assert SAGE_LOCAL_ADMIN_SOURCE_REVISION in SAGE_LOCAL_ADMIN_SOURCE_URL
    assert "/resolve/main/" not in SAGE_LOCAL_ADMIN_SOURCE_URL


def test_model_import_verifies_hash_and_records_provenance(tmp_path: Path, monkeypatch) -> None:
    """The community Q5_K_M artifact is hash-pinned before Ollama imports it."""
    executable = tmp_path / "ollama"
    executable.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("SAGE_OLLAMA_COMMAND", str(executable))
    service = OllamaAdminService(_app_root(tmp_path))
    fixture = b"governed-gguf-fixture"
    fixture_hash = hashlib.sha256(fixture).hexdigest()
    monkeypatch.setattr("sage.ollama_admin.SAGE_LOCAL_ADMIN_SOURCE_SHA256", fixture_hash)
    monkeypatch.setattr(service, "status", lambda: _status(running=True))
    monkeypatch.setattr(service, "_download", lambda _url, destination, _progress=None: destination.write_bytes(fixture))
    monkeypatch.setattr(
        "sage.ollama_admin.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=20 * 1024**3, used=0, free=20 * 1024**3),
    )
    monkeypatch.setattr(
        service,
        "_api_rows",
        lambda _endpoint: (True, ({"name": SAGE_LOCAL_ADMIN_MODEL, "digest": "ollama-digest"},)),
    )
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        """Capture model import without invoking the installed Ollama binary."""
        calls.append([str(value) for value in args])
        return subprocess.CompletedProcess(args, 0, stdout="created", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    service.install_model()

    assert calls[0][0:3] == [str(executable.resolve()), "create", SAGE_LOCAL_ADMIN_MODEL]
    receipt = json.loads(service.model_receipt.read_text(encoding="utf-8"))
    assert receipt["model"] == SAGE_LOCAL_ADMIN_MODEL
    assert receipt["quantization"] == "Q5_K_M"
    assert receipt["source_sha256"] == fixture_hash
    assert receipt["source_revision"] == SAGE_LOCAL_ADMIN_SOURCE_REVISION
    assert receipt["ollama_digest"] == "ollama-digest"


def test_external_ollama_service_is_not_stopped(tmp_path: Path, monkeypatch) -> None:
    """A running service not owned by this SAGE session fails closed."""
    from sage.errors import ValidationError

    service = OllamaAdminService(_app_root(tmp_path))
    monkeypatch.setattr(service, "status", lambda: _status(running=True))

    try:
        service.stop()
    except ValidationError as exc:
        assert exc.code == "OLLAMA_EXTERNAL_SERVICE_RUNNING"
    else:
        raise AssertionError("Expected an external-service ownership failure")


def test_macos_memory_probe_uses_sysctl_and_vm_stat(tmp_path: Path, monkeypatch) -> None:
    """macOS RAM detection uses native sysctl/vm_stat rather than Linux-only page counters."""
    service = OllamaAdminService(_app_root(tmp_path))
    monkeypatch.setattr("sage.ollama_admin.platform.system", lambda: "Darwin")

    def fake_run(args, **_kwargs):
        """Return deterministic macOS memory-tool output without invoking the host."""
        if list(args) == ["sysctl", "-n", "hw.memsize"]:
            return subprocess.CompletedProcess(args, 0, stdout=str(32 * 1024**3) + "\n", stderr="")
        if list(args) == ["vm_stat"]:
            stdout = "\n".join(
                (
                    "Mach Virtual Memory Statistics: (page size of 16384 bytes)",
                    "Pages free: 1000.",
                    "Pages inactive: 2000.",
                    "Pages speculative: 300.",
                    "Pages purgeable: 200.",
                )
            )
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(subprocess, "run", fake_run)
    total, available = service._memory_bytes()
    assert total == 32 * 1024**3
    assert available == 3500 * 16384


@pytest.mark.parametrize(
    ("system", "expected_name", "expected_command"),
    (
        ("Darwin", "Ollama.dmg", "open"),
        ("Windows", "OllamaSetup.exe", "OllamaSetup.exe"),
        ("Linux", "ollama-install.sh", "sh"),
    ),
)
def test_official_installer_dispatch_is_platform_specific(
    tmp_path: Path,
    monkeypatch,
    system: str,
    expected_name: str,
    expected_command: str,
) -> None:
    """Setup uses the official OS installer route and never downloads during tests."""
    service = OllamaAdminService(_app_root(tmp_path))
    monkeypatch.setattr("sage.ollama_admin.platform.system", lambda: system)
    monkeypatch.setattr(service, "executable", lambda: None)
    downloads: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        service,
        "_download",
        lambda url, destination, _progress=None: (
            downloads.append((url, destination)),
            destination.write_bytes(b"installer"),
        ),
    )
    commands: list[list[str]] = []

    def fake_run(args, **_kwargs):
        """Capture the selected platform installer command without executing it."""
        commands.append([str(value) for value in args])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = service.install_runtime()

    assert downloads[0][1].name == expected_name
    assert expected_command in Path(commands[0][0]).name
    assert result["status"] in {"INSTALLED", "OPERATOR_ACTION_REQUIRED"}
