"""SQS transport hardening: ordered endpoint failover, loopback/HTTPS exception,
and proxy bypass (integration plan Task 3/4)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sage.sqs_client import (
    SqsTransportError,
    fetch_bundle,
    fetch_health,
    fetch_language_request_status,
    fetch_planned_evaluations,
    post_discovery,
    resolve_endpoints,
    validate_sqs_endpoint,
)


class _Handler(BaseHTTPRequestHandler):
    """Minimal test HTTP handler driven by a per-server response script."""

    def log_message(self, *args):
        """Suppress default request logging noise during tests."""
        return

    def _respond(self):
        """Serve the next scripted (status, body) response for this path."""
        status, body = self.server.script.get(self.path, (200, {"ok": True}))
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        """Handle a scripted GET request."""
        self._respond()

    def do_POST(self):
        """Consume the request body, then handle a scripted POST response."""
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self._respond()


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


def test_validate_sqs_endpoint_accepts_loopback_http():
    """Loopback HTTP is accepted as the documented local-test exception."""
    assert validate_sqs_endpoint("http://127.0.0.1:8787") == "http://127.0.0.1:8787"
    assert validate_sqs_endpoint("http://localhost:8787/") == "http://localhost:8787"


def test_validate_sqs_endpoint_rejects_non_loopback_http():
    """A non-loopback endpoint must use HTTPS, never plain HTTP."""
    with pytest.raises(SqsTransportError) as excinfo:
        validate_sqs_endpoint("http://sqs.example.org")
    assert excinfo.value.code == "SQS_ENDPOINT_INSECURE"


def test_validate_sqs_endpoint_accepts_non_loopback_https():
    """A non-loopback HTTPS endpoint is accepted."""
    assert validate_sqs_endpoint("https://sqs.example.org") == "https://sqs.example.org"


def test_validate_sqs_endpoint_rejects_embedded_credentials():
    """An endpoint URL must not carry credentials, a query, or a fragment."""
    with pytest.raises(SqsTransportError):
        validate_sqs_endpoint("https://user:pass@sqs.example.org")


def test_resolve_endpoints_prefers_ordered_urls_list():
    """SAGE_SQS_URLS, when set, wins over the single-endpoint SAGE_SQS_URL override."""
    endpoints = resolve_endpoints(
        urls_env="http://127.0.0.1:1, http://127.0.0.1:2",
        url_env="http://127.0.0.1:9",
    )
    assert endpoints == ["http://127.0.0.1:1", "http://127.0.0.1:2"]


def test_resolve_endpoints_falls_back_to_single_url():
    """With no SAGE_SQS_URLS, the single-endpoint SAGE_SQS_URL override is used."""
    assert resolve_endpoints(urls_env=None, url_env="http://127.0.0.1:9") == ["http://127.0.0.1:9"]


def test_resolve_endpoints_empty_when_neither_configured():
    """With neither variable set, no endpoints are configured."""
    assert resolve_endpoints(urls_env=None, url_env=None) == []


def test_fetch_health_and_bundle_succeed_against_a_real_local_server():
    """A real request against a live loopback server succeeds end to end."""
    httpd = _server({"/health": (200, {"status": "OK"}), "/bundle": (200, {"bundle_revision": 1})})
    try:
        assert fetch_health([_url(httpd)])["status"] == "OK"
        assert fetch_bundle([_url(httpd)])["bundle_revision"] == 1
    finally:
        httpd.shutdown()


def test_fetch_planned_evaluations_succeeds_against_a_real_local_server():
    """The work-queue list endpoint reaches the server and returns its scripted response."""
    httpd = _server({"/planned-evaluations": (200, [{"id": "run-1", "model_id": "gpt-x"}])})
    try:
        assert fetch_planned_evaluations([_url(httpd)])[0]["id"] == "run-1"
    finally:
        httpd.shutdown()


def test_fetch_language_request_status_succeeds_against_a_real_local_server():
    """The language-request status endpoint reaches the server with the capability query param."""
    httpd = _server({
        "/language-requests/sw-CD?capability=GRAMMAR_ANALYSIS": (200, {
            "profile_id": "sw-CD", "capability": "GRAMMAR_ANALYSIS", "status": "REQUESTED",
        }),
    })
    try:
        result = fetch_language_request_status([_url(httpd)], profile_id="sw-CD", capability="GRAMMAR_ANALYSIS")
        assert result["status"] == "REQUESTED"
    finally:
        httpd.shutdown()


def test_post_discovery_succeeds_against_a_real_local_server():
    """A discovery POST reaches the server and returns its scripted response."""
    httpd = _server({"/discoveries": (202, {"status": "ACCEPTED"})})
    try:
        assert post_discovery([_url(httpd)], {"kind": "MODEL"})["status"] == "ACCEPTED"
    finally:
        httpd.shutdown()


def test_failover_skips_an_unreachable_first_endpoint():
    """A connection failure on the first endpoint fails over to the next one."""
    httpd = _server({"/health": (200, {"status": "OK", "source": "second"})})
    try:
        unreachable = "http://127.0.0.1:1"  # nothing listens on port 1
        result = fetch_health([unreachable, _url(httpd)], timeout=2)
        assert result["source"] == "second"
    finally:
        httpd.shutdown()


def test_failover_skips_a_5xx_endpoint():
    """A 5xx response from the first endpoint fails over to the next one."""
    first = _server({"/health": (503, {"status": "DEGRADED"})})
    second = _server({"/health": (200, {"status": "OK", "source": "second"})})
    try:
        result = fetch_health([_url(first), _url(second)])
        assert result["source"] == "second"
    finally:
        first.shutdown()
        second.shutdown()


def test_no_failover_on_4xx_even_with_a_healthy_second_endpoint():
    """A 4xx response must stop immediately, never silently try another endpoint."""
    first = _server({"/health": (404, {"error": "not found"})})
    second = _server({"/health": (200, {"status": "OK", "source": "second"})})
    try:
        with pytest.raises(SqsTransportError) as excinfo:
            fetch_health([_url(first), _url(second)])
        assert excinfo.value.code == "SQS_REQUEST_REJECTED"
    finally:
        first.shutdown()
        second.shutdown()


def test_all_endpoints_failing_raises_with_a_clear_error():
    """When every configured endpoint is unreachable, a clear terminal error is raised."""
    with pytest.raises(SqsTransportError) as excinfo:
        fetch_health(["http://127.0.0.1:1", "http://127.0.0.1:2"], timeout=1)
    assert excinfo.value.code == "SQS_ALL_ENDPOINTS_FAILED"


def test_no_endpoint_configured_raises_immediately():
    """Calling with an empty endpoint list raises rather than silently no-op-ing."""
    with pytest.raises(SqsTransportError) as excinfo:
        fetch_health([])
    assert excinfo.value.code == "SQS_NO_ENDPOINT_CONFIGURED"


def test_loopback_request_bypasses_a_configured_proxy(monkeypatch):
    """A bogus, unreachable proxy must not break a loopback request -- it's bypassed entirely."""
    httpd = _server({"/health": (200, {"status": "OK"})})
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")  # nothing listens here
        monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
        assert fetch_health([_url(httpd)])["status"] == "OK"
    finally:
        httpd.shutdown()
