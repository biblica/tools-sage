"""End-to-end `sage model sqs-sync` CLI behavior (integration plan Task 4)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def _run_sqs_sync(package_root: Path, root: Path, *, env_overrides: dict | None = None) -> dict:
    """Invoke `sage --json model sqs-sync` through the real public CLI and parse its output."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("SAGE_SQS_URLS", None)
    env.pop("SAGE_SQS_URL", None)
    env.update(env_overrides or {})
    result = subprocess.run(
        [sys.executable, "-m", "sage.cli", "--settings", str(root / "ecosystem.yml"), "--json", "model", "sqs-sync"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def test_sqs_sync_with_no_endpoint_configured_reports_none_and_stays_safe(package_root: Path, make_workspace):
    """With no SQS endpoint configured, sync succeeds, reports NONE, and never raises."""
    root = make_workspace()
    result = _run_sqs_sync(package_root, root)
    assert result["source"] == "NONE"
    assert result["discoveries_sent"] == 0
    assert result["discoveries_remaining"] == 0
    assert "No SQS endpoint configured" in result["error"]


class _BundleHandler(BaseHTTPRequestHandler):
    """Test SQS server that always serves the same scripted, digest-correct bundle."""

    def log_message(self, *args):
        """Suppress default request logging noise during tests."""
        return

    def do_GET(self):
        """Serve the server's scripted bundle for /bundle."""
        payload = json.dumps(self.server.bundle).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


def _bundle_server(bundle: dict) -> HTTPServer:
    """Start a real loopback HTTP server bound to an ephemeral port, serving one bundle."""
    httpd = HTTPServer(("127.0.0.1", 0), _BundleHandler)
    httpd.bundle = bundle
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def test_sqs_sync_against_a_real_local_server_reports_remote_and_caches_the_bundle(package_root: Path, make_workspace):
    """A real end-to-end sync against a live loopback SQS server validates and caches the bundle."""
    from sage.sqs_cache import canonical_bundle_sha256

    bundle = {
        "schema_version": "1.1",
        "service_version": "0.02a1",
        "authority_id": "biblica-sqs-production",
        "publication_epoch": 1,
        "bundle_revision": 7,
        "generated_at": "2026-09-18T00:00:00Z",
        "profiles": [],
        "models": [],
        "qualifications": [],
        "bundle_sha256": "",
    }
    bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)

    root = make_workspace()
    httpd = _bundle_server(bundle)
    try:
        result = _run_sqs_sync(package_root, root, env_overrides={"SAGE_SQS_URL": f"http://127.0.0.1:{httpd.server_port}"})
        assert result["source"] == "REMOTE"
        assert result["bundle_revision"] == 7
        assert result["error"] is None
    finally:
        httpd.shutdown()


def test_sqs_sync_falls_back_to_cache_when_endpoint_is_unreachable(package_root: Path, make_workspace):
    """A second sync with an unreachable endpoint still reports CACHE from the prior sync, not a crash."""
    from sage.sqs_cache import canonical_bundle_sha256

    bundle = {
        "schema_version": "1.1",
        "service_version": "0.02a1",
        "authority_id": "biblica-sqs-production",
        "publication_epoch": 1,
        "bundle_revision": 1,
        "generated_at": "2026-09-18T00:00:00Z",
        "profiles": [],
        "models": [],
        "qualifications": [],
        "bundle_sha256": "",
    }
    bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)

    root = make_workspace()
    httpd = _bundle_server(bundle)
    try:
        first = _run_sqs_sync(package_root, root, env_overrides={"SAGE_SQS_URL": f"http://127.0.0.1:{httpd.server_port}"})
        assert first["source"] == "REMOTE"
    finally:
        httpd.shutdown()

    second = _run_sqs_sync(package_root, root, env_overrides={"SAGE_SQS_URL": "http://127.0.0.1:1"})
    assert second["source"] == "CACHE"
    assert second["bundle_revision"] == 1
    assert second["error"] is not None
