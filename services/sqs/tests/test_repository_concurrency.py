"""Concurrent-write safety for Repository methods that key on a table's own PRIMARY KEY.

Database.open() sets check_same_thread=False and WAL mode specifically so the
connection can be shared across FastAPI's threadpool -- these are not
hypothetical races. Each test opens a second, independent connection to the
same on-disk database (mirroring two real concurrent requests) and drives
both from real threads, not just calling the method twice sequentially.
"""
from __future__ import annotations

import threading

from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification
from sage_sqs.repository import Repository


def _qualification(**overrides) -> Qualification:
    base = dict(
        provider_family="openai", execution_channel="codex_workspace", model_id="gpt-x",
        model_capability_fingerprint="a" * 64, profile_id="en-US", profile_identity_sha256="c" * 64,
        capability="GRAMMAR_ANALYSIS", status="QUALIFIED", minimum_reasoning="medium",
        quality_score=.96, reliability_score=.98, confidence="HIGH", value="HIGH", evidence_basis="MEASURED",
        estimated_unit_cost_usd=.004, evaluated_at="2026-09-26T00:00:00Z", evidence_sha256="b" * 64,
    )
    return Qualification(**{**base, **overrides})


def _run_concurrently(*actions) -> list[Exception | None]:
    """Run each callable on its own thread, starting all together; return each thread's exception, if any."""
    errors: list[Exception | None] = [None] * len(actions)

    def wrap(index: int, action) -> None:
        try:
            action()
        except Exception as exc:  # captured, not raised, so every thread still runs to completion
            errors[index] = exc

    threads = [threading.Thread(target=wrap, args=(index, action)) for index, action in enumerate(actions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return errors


def test_concurrent_save_qualification_for_the_same_key_never_duplicates_or_raises(tmp_path):
    """Two threads saving the same (provider_family, model_id, profile_id, capability) key never race."""
    db_path = tmp_path / "sqs.db"
    repo_a = Repository(Database.open(db_path))
    repo_b = Repository(Database.open(db_path))

    errors = _run_concurrently(
        lambda: repo_a.save_qualification(_qualification(quality_score=.90)),
        lambda: repo_b.save_qualification(_qualification(quality_score=.91)),
    )

    assert errors == [None, None]
    rows = repo_a.db.connection.execute(
        "SELECT COUNT(*) FROM qualifications WHERE provider_family='openai' AND model_id='gpt-x' "
        "AND profile_id='en-US' AND capability='GRAMMAR_ANALYSIS'"
    ).fetchone()
    assert rows[0] == 1


def test_concurrent_record_discovery_for_the_same_fingerprint_never_raises(tmp_path):
    """Two threads recording the identical discovery payload never hit a PRIMARY KEY collision."""
    db_path = tmp_path / "sqs.db"
    repo_a = Repository(Database.open(db_path))
    repo_b = Repository(Database.open(db_path))
    payload = {"kind": "MODEL", "sage_version": "0.02a3", "observed": {"model_id": "gpt-x"}}

    digests: list[str | None] = [None, None]

    def record(index: int, repo: Repository) -> None:
        digests[index] = repo.record_discovery(payload)

    errors = _run_concurrently(lambda: record(0, repo_a), lambda: record(1, repo_b))

    assert errors == [None, None]
    assert digests[0] == digests[1]
    row = repo_a.db.connection.execute(
        "SELECT observation_count FROM discoveries WHERE fingerprint=?", (digests[0],)
    ).fetchone()
    assert row[0] == 2


def test_concurrent_upsert_attention_for_the_same_key_never_raises(tmp_path):
    """Two threads upserting the same attention_key never hit a PRIMARY KEY collision."""
    db_path = tmp_path / "sqs.db"
    repo_a = Repository(Database.open(db_path))
    repo_b = Repository(Database.open(db_path))

    errors = _run_concurrently(
        lambda: repo_a.upsert_attention(
            attention_key="DISCOVERY:same", category="DISCOVERY", severity="INFO",
            summary="first", payload={"n": 1},
        ),
        lambda: repo_b.upsert_attention(
            attention_key="DISCOVERY:same", category="DISCOVERY", severity="INFO",
            summary="second", payload={"n": 2},
        ),
    )

    assert errors == [None, None]
    row = repo_a.db.connection.execute(
        "SELECT observation_count FROM attention_items WHERE attention_key='DISCOVERY:same'"
    ).fetchone()
    assert row[0] == 2
