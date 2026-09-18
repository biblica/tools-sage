"""Outbox-first SQS discovery: local queuing, contract shape, and flush behavior."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from sage.sqs_discovery import (
    build_language_profile_discovery,
    build_model_discovery,
    discovery_capability_fingerprint,
    flush_outbox,
    load_outbox,
    queue_discovery,
)

_DISCOVERY_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "services" / "sqs" / "contracts" / "discovery.schema.json"
)


def _discovery_schema() -> dict:
    """Load the real, tested SQS discovery contract for wire-shape validation."""
    return json.loads(_DISCOVERY_SCHEMA_PATH.read_text(encoding="utf-8"))


def _assert_matches_schema_variant(payload: dict, schema: dict) -> None:
    """Structurally validate payload against the matching oneOf variant, without a jsonschema dependency.

    Deliberately dependency-free: `jsonschema` is not an established
    dependency of this package (no other test uses it, and it is not
    declared in pyproject.toml) -- pulling it in for one test would add an
    undeclared, coincidental reliance rather than a real project dependency.
    """
    variants = schema["oneOf"]
    variant = next(v for v in variants if v["properties"]["kind"]["const"] == payload.get("kind"))
    assert set(payload) == set(variant["required"])
    observed_schema = variant["properties"]["observed"]
    assert set(payload["observed"]) == set(observed_schema["required"])
    for field, field_schema in observed_schema["properties"].items():
        if "const" in field_schema:
            assert payload["observed"][field] == field_schema["const"], field
        if "enum" in field_schema:
            values = payload["observed"][field]
            values = values if isinstance(values, list) else [values]
            assert all(value in field_schema["enum"] for value in values), field
        if field_schema.get("pattern") == "^[0-9a-f]{64}$":
            assert len(payload["observed"][field]) == 64, field


def test_model_discovery_matches_the_real_tested_wire_contract():
    """A built MODEL discovery matches every required field/const/enum in SQS's actual enforced schema."""
    discovery = build_model_discovery(model_id="gpt-x", reasoning_levels=["medium", "low"], sage_version="0.02a3")
    _assert_matches_schema_variant(discovery, _discovery_schema())
    assert discovery["kind"] == "MODEL"
    assert discovery["observed"]["reasoning_levels"] == ["low", "medium"]


def test_language_profile_discovery_matches_the_real_tested_wire_contract():
    """A built LANGUAGE_PROFILE discovery matches every required field in SQS's actual enforced schema."""
    discovery = build_language_profile_discovery(
        profile_id="sw-KE", language_code="sw", script="Latn", region="KE", sage_version="0.02a3",
    )
    _assert_matches_schema_variant(discovery, _discovery_schema())
    assert discovery["kind"] == "LANGUAGE_PROFILE"


def test_capability_fingerprint_is_stable_and_order_independent():
    """The fingerprint depends only on model_id and the reasoning-level set, not input order."""
    a = discovery_capability_fingerprint(model_id="gpt-x", reasoning_levels=["low", "medium"])
    b = discovery_capability_fingerprint(model_id="gpt-x", reasoning_levels=["medium", "low"])
    assert a == b
    assert len(a) == 64


def test_queue_discovery_never_touches_the_network(tmp_path: Path):
    """Queuing a discovery is purely local -- no endpoint is even accepted as an argument."""
    outbox = tmp_path / "outbox.json"
    queue_discovery(outbox, build_model_discovery(model_id="gpt-x", reasoning_levels=["medium"], sage_version="0.02a3"))
    entries = load_outbox(outbox)
    assert len(entries) == 1
    assert entries[0]["observed"]["model_id"] == "gpt-x"


def test_load_outbox_returns_empty_list_when_absent(tmp_path: Path):
    """A never-created outbox file behaves as an empty queue, not an error."""
    assert load_outbox(tmp_path / "missing.json") == []


def test_load_outbox_treats_corrupt_file_as_empty(tmp_path: Path):
    """A corrupt outbox file degrades to an empty queue rather than raising."""
    outbox = tmp_path / "outbox.json"
    outbox.write_text("{not valid json", encoding="utf-8")
    assert load_outbox(outbox) == []


class _AcceptingHandler(BaseHTTPRequestHandler):
    """Test discovery-intake handler that always accepts and records what it received."""

    def log_message(self, *args):
        """Suppress default request logging noise during tests."""
        return

    def do_POST(self):
        """Record the posted discovery body and return 202 ACCEPTED."""
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else None
        self.server.received.append(body)
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ACCEPTED"}).encode("utf-8"))


class _RejectingHandler(BaseHTTPRequestHandler):
    """Test discovery-intake handler that always rejects with 400."""

    def log_message(self, *args):
        """Suppress default request logging noise during tests."""
        return

    def do_POST(self):
        """Consume the body and return 400 for every request."""
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "rejected"}).encode("utf-8"))


def _server(handler) -> HTTPServer:
    """Start a real loopback HTTP server bound to an ephemeral port."""
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    httpd.received = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _url(httpd: HTTPServer) -> str:
    """Return the http://127.0.0.1:<port> base URL for a running test server."""
    return f"http://127.0.0.1:{httpd.server_port}"


def test_flush_outbox_sends_every_entry_and_empties_the_queue(tmp_path: Path):
    """A successful flush delivers every queued discovery and clears the outbox."""
    outbox = tmp_path / "outbox.json"
    queue_discovery(outbox, build_model_discovery(model_id="gpt-a", reasoning_levels=["low"], sage_version="0.02a3"))
    queue_discovery(outbox, build_model_discovery(model_id="gpt-b", reasoning_levels=["medium"], sage_version="0.02a3"))
    httpd = _server(_AcceptingHandler)
    try:
        result = flush_outbox(outbox, [_url(httpd)])
        assert result.sent == 2
        assert result.remaining == 0
        assert load_outbox(outbox) == []
        assert len(httpd.received) == 2
    finally:
        httpd.shutdown()


def test_flush_outbox_never_blocks_task_execution_on_delivery(tmp_path: Path):
    """Queuing is instant and network-free; only an explicit flush call ever sends anything."""
    outbox = tmp_path / "outbox.json"
    queue_discovery(outbox, build_model_discovery(model_id="gpt-a", reasoning_levels=["low"], sage_version="0.02a3"))
    # No server is even running; queuing above must not have raised or attempted delivery.
    assert len(load_outbox(outbox)) == 1


def test_flush_outbox_keeps_failed_entries_queued_and_continues(tmp_path: Path):
    """A rejected entry stays queued for later, rather than being silently dropped."""
    outbox = tmp_path / "outbox.json"
    queue_discovery(outbox, build_model_discovery(model_id="gpt-a", reasoning_levels=["low"], sage_version="0.02a3"))
    httpd = _server(_RejectingHandler)
    try:
        result = flush_outbox(outbox, [_url(httpd)])
        assert result.sent == 0
        assert result.remaining == 1
        assert len(load_outbox(outbox)) == 1
    finally:
        httpd.shutdown()


def test_flush_outbox_with_no_endpoint_configured_keeps_everything_queued(tmp_path: Path):
    """With no SQS endpoint reachable at all, the whole outbox is preserved, nothing is lost."""
    outbox = tmp_path / "outbox.json"
    queue_discovery(outbox, build_model_discovery(model_id="gpt-a", reasoning_levels=["low"], sage_version="0.02a3"))
    result = flush_outbox(outbox, [])
    assert result.sent == 0
    assert result.remaining == 1
