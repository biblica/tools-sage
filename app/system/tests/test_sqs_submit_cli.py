"""End-to-end `sage sqs list`/`sage sqs submit` CLI behavior (Codex-workspace provider plan)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from sage.sqs_cache import SqsCache, canonical_bundle_sha256
from sage.sqs_submission_key import generate_submission_keypair
from sage.storage import storage_layout


def _run_cli(package_root: Path, root: Path, args: list[str], *, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke `sage --json <args>` through the real public CLI against one test workspace."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("SAGE_SQS_URLS", None)
    env.pop("SAGE_SQS_URL", None)
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "sage.cli", "--settings", str(root / "ecosystem.yml"), "--json", *args],
        text=True, capture_output=True, env=env, check=False, timeout=30,
    )


class _Handler(BaseHTTPRequestHandler):
    """Minimal test HTTP handler driven by a per-server response script."""

    def log_message(self, *args):
        """Suppress default request logging noise during tests."""
        return

    def do_GET(self):
        """Serve the next scripted (status, body) response for this path."""
        status, body = self.server.script.get(self.path, (200, {}))
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


def _server(script: dict) -> HTTPServer:
    """Start a real loopback HTTP server bound to an ephemeral port, scripted by path."""
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.script = script
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _url(httpd: HTTPServer) -> str:
    """Return the http://127.0.0.1:<port> base URL for a running test server."""
    return f"http://127.0.0.1:{httpd.server_port}"


def test_sqs_list_with_no_endpoint_configured_fails_closed(package_root: Path, make_workspace):
    """With no SQS endpoint configured, `sqs list` fails with a distinct, non-crashing error."""
    root = make_workspace()
    result = _run_cli(package_root, root, ["sqs", "list"])
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["reason_code"] == "SQS_NO_ENDPOINT_CONFIGURED"


def test_sqs_list_against_a_real_local_server_returns_the_scripted_queue(package_root: Path, make_workspace):
    """`sqs list` reaches a real loopback server and prints its scripted pending-work rows."""
    root = make_workspace()
    httpd = _server({"/planned-evaluations": (200, [
        {"id": "run-1", "provider_family": "openai", "profile_id": "en-US", "model_id": "gpt-x",
         "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium", "scope": "FULL"},
    ])})
    try:
        result = _run_cli(package_root, root, ["sqs", "list"], env_overrides={"SAGE_SQS_URL": _url(httpd)})
        assert result.returncode == 0, result.stderr + result.stdout
        rows = json.loads(result.stdout)
        assert rows[0]["id"] == "run-1"
    finally:
        httpd.shutdown()


def test_sqs_submit_without_an_endpoint_fails_closed(package_root: Path, make_workspace):
    """`sqs submit` with no SQS endpoint configured fails before touching anything else."""
    root = make_workspace()
    result = _run_cli(package_root, root, ["sqs", "submit", "--run-id", "run-1"])
    assert result.returncode != 0
    assert json.loads(result.stdout)["reason_code"] == "SQS_NO_ENDPOINT_CONFIGURED"


def test_sqs_submit_without_a_generated_key_fails_closed(package_root: Path, make_workspace):
    """`sqs submit` refuses to proceed until a local submission keypair has been generated."""
    root = make_workspace()
    httpd = _server({"/planned-evaluations": (200, [])})
    try:
        result = _run_cli(package_root, root, ["sqs", "submit", "--run-id", "run-1"], env_overrides={"SAGE_SQS_URL": _url(httpd)})
        assert result.returncode != 0
        assert json.loads(result.stdout)["reason_code"] == "SQS_SUBMISSION_KEY_MISSING"
    finally:
        httpd.shutdown()


def test_sqs_submit_without_a_cached_bundle_fails_closed(package_root: Path, make_workspace):
    """`sqs submit` refuses to proceed until `sage model sqs-sync` has cached a validated bundle."""
    root = make_workspace()
    state_dir = storage_layout(root).state_root / "sqs"
    generate_submission_keypair(state_dir)
    httpd = _server({"/planned-evaluations": (200, [])})
    try:
        result = _run_cli(package_root, root, ["sqs", "submit", "--run-id", "run-1"], env_overrides={"SAGE_SQS_URL": _url(httpd)})
        assert result.returncode != 0
        assert json.loads(result.stdout)["reason_code"] == "SQS_NO_CACHED_BUNDLE"
    finally:
        httpd.shutdown()


def test_sqs_submit_with_an_unknown_run_id_fails_closed(package_root: Path, make_workspace):
    """With a key and a cached bundle both present, an unrecognized run id still fails closed."""
    root = make_workspace()
    state_dir = storage_layout(root).state_root / "sqs"
    generate_submission_keypair(state_dir)

    bundle = {
        "schema_version": "1.1", "service_version": "0.02a1", "authority_id": "biblica-sqs-production",
        "publication_epoch": 1, "bundle_revision": 1, "generated_at": "2026-09-22T00:00:00Z",
        "profiles": [], "models": [], "qualifications": [], "bundle_sha256": "",
    }
    bundle["bundle_sha256"] = canonical_bundle_sha256(bundle)
    SqsCache(state_dir, trusted_authority_id="biblica-sqs-production").accept_bundle(bundle)

    httpd = _server({"/planned-evaluations": (200, [])})
    try:
        result = _run_cli(package_root, root, ["sqs", "submit", "--run-id", "run-missing"], env_overrides={"SAGE_SQS_URL": _url(httpd)})
        assert result.returncode != 0
        assert json.loads(result.stdout)["reason_code"] == "SQS_UNKNOWN_RUN_ID"
    finally:
        httpd.shutdown()
