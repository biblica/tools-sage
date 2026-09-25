"""SAGE-side offer to request SQS language validation for an UNASSESSED competency row."""
from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from sage.menu import MenuIO, SageControlCenter, ScriptedInput, _unassessed_competency_tags
from sage.sqs_discovery import load_outbox
from sage.storage import storage_layout


class _Handler(BaseHTTPRequestHandler):
    """Minimal test HTTP handler driven by a per-path response script."""

    def log_message(self, *args):
        """Suppress default request logging noise during tests."""
        return

    def do_GET(self):
        """Serve the next scripted (status, body) response for this exact path+query."""
        status, body = self.server.script.get(self.path, (200, {"status": "NOT_REQUESTED"}))
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


def _center(root, inputs):
    """Build a SageControlCenter fed a scripted sequence of menu-prompt responses."""
    return SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(inputs), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )


def _result(*, tier="UNASSESSED"):
    """Build a minimal lookup_language_competency-shaped result for one language row."""
    return {"status": "READY", "model": "codex", "assessments": [
        {"canonical_tag": "sw-CD", "language": "Swahili (DR Congo)", "tier": tier, "confidence": "LOW"},
    ]}


def _rows_by_tag():
    """Build the rows_by_tag identity map _check_configured_language_competency would pass through."""
    return {"sw-CD": {"canonical_tag": "sw-CD", "language": "Swahili (DR Congo)", "region": "CD", "script": "Latn", "language_code": "sw"}}


def test_unassessed_competency_tags_filters_to_only_unassessed_rows():
    """Only rows with tier UNASSESSED are returned, in canonical_tag/language pairs."""
    assessments = [
        {"canonical_tag": "en-GB", "language": "English (UK)", "tier": "GOOD"},
        {"canonical_tag": "sw-CD", "language": "Swahili (DR Congo)", "tier": "UNASSESSED"},
    ]
    assert _unassessed_competency_tags(assessments) == [("sw-CD", "Swahili (DR Congo)")]


def test_no_sqs_section_shown_when_no_endpoint_is_configured(make_workspace, monkeypatch):
    """With no SQS endpoint configured, the offer is skipped silently rather than erroring."""
    monkeypatch.delenv("SAGE_SQS_URL", raising=False)
    monkeypatch.delenv("SAGE_SQS_URLS", raising=False)
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    center = _center(root, [])
    center._offer_sqs_language_validation(_result(), _rows_by_tag())
    assert "SQS QUALIFICATION VALIDATION" not in center.io.output.getvalue()


def test_shows_status_and_declining_the_offer_queues_nothing(make_workspace, monkeypatch):
    """Declining the confirmation prompt shows the per-capability status but queues no request."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    httpd = _server({})
    monkeypatch.setenv("SAGE_SQS_URL", f"http://127.0.0.1:{httpd.server_port}")
    try:
        center = _center(root, ["n"])
        center._offer_sqs_language_validation(_result(), _rows_by_tag())
        rendered = center.io.output.getvalue()
        assert "SQS QUALIFICATION VALIDATION" in rendered
        assert "NOT_REQUESTED" in rendered
        outbox_path = storage_layout(root).state_root / "sqs" / "sqs-discovery-outbox.json"
        assert load_outbox(outbox_path) == []
    finally:
        httpd.shutdown()


def test_confirming_queues_a_language_validation_request_to_the_outbox(make_workspace, monkeypatch):
    """Confirming and picking one offered capability queues the exact discovery payload for it."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    httpd = _server({})
    monkeypatch.setenv("SAGE_SQS_URL", f"http://127.0.0.1:{httpd.server_port}")
    try:
        center = _center(root, ["y", "1"])
        center._offer_sqs_language_validation(_result(), _rows_by_tag())
        rendered = center.io.output.getvalue()
        assert "Queued SQS validation request" in rendered
        outbox_path = storage_layout(root).state_root / "sqs" / "sqs-discovery-outbox.json"
        queued = load_outbox(outbox_path)
        assert len(queued) == 1
        assert queued[0]["kind"] == "LANGUAGE_VALIDATION_REQUEST"
        assert queued[0]["observed"] == {
            "profile_id": "sw-CD", "language_code": "sw", "script": "Latn", "region": "CD",
            "capability": "GRAMMAR_ANALYSIS",
        }
    finally:
        httpd.shutdown()


def test_already_qualified_capability_is_not_offered(make_workspace, monkeypatch):
    """A capability that is already QUALIFIED or REQUESTED is never offered for a new request."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    httpd = _server({
        "/language-requests/sw-CD?capability=GRAMMAR_ANALYSIS": (200, {"status": "QUALIFIED"}),
        "/language-requests/sw-CD?capability=SEMANTIC_REWRITE": (200, {"status": "REQUESTED"}),
    })
    monkeypatch.setenv("SAGE_SQS_URL", f"http://127.0.0.1:{httpd.server_port}")
    try:
        center = _center(root, [])
        center._offer_sqs_language_validation(_result(), _rows_by_tag())
        rendered = center.io.output.getvalue()
        assert "QUALIFIED" in rendered
        assert "Request SQS validation" not in rendered
    finally:
        httpd.shutdown()
