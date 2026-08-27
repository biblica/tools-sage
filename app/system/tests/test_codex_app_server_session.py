"""Codex App Server sequencing and readiness separation contracts."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

from sage.executors.codex_cli import CodexCLIExecutor


def test_app_server_waits_for_initialisation_before_capability_requests(tmp_path: Path) -> None:
    """Verify that SAGE waits for the initialize response before account and model requests."""
    log = tmp_path / "methods.log"
    fake = tmp_path / "codex-fake"
    script = "\n".join(
        [
            f"#!{sys.executable}",
            "import json",
            "import sys",
            f"LOG = {str(log)!r}",
            "def record(method):",
            "    with open(LOG, 'a', encoding='utf-8') as handle:",
            "        handle.write(method + '\\n')",
            "first = json.loads(sys.stdin.readline())",
            "record(first.get('method', ''))",
            "if first.get('method') != 'initialize':",
            "    raise SystemExit(7)",
            "print(json.dumps({'id': first['id'], 'result': {'serverInfo': {'name': 'fake'}}}), flush=True)",
            "second = json.loads(sys.stdin.readline())",
            "record(second.get('method', ''))",
            "if second.get('method') != 'initialized':",
            "    raise SystemExit(8)",
            "for line in sys.stdin:",
            "    msg = json.loads(line)",
            "    method = msg.get('method', '')",
            "    record(method)",
            "    if method == 'account/read':",
            "        result = {'account': {'type': 'chatgpt', 'planType': 'plus'}}",
            "    elif method == 'model/list':",
            "        result = {'data': [{'id': 'codex-test', 'model': 'codex-test', 'isDefault': True, 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}], 'nextCursor': None}",
            "    else:",
            "        result = {}",
            "    print(json.dumps({'id': msg['id'], 'result': result}), flush=True)",
            "",
        ]
    )
    fake.write_text(script, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    auth_mode, plan, models = CodexCLIExecutor(command=str(fake)).query_catalog()
    assert auth_mode == "CHATGPT"
    assert plan == "plus"
    assert [model.model for model in models] == ["codex-test"]
    assert log.read_text(encoding="utf-8").splitlines() == [
        "initialize",
        "initialized",
        "account/read",
        "model/list",
    ]
