import pytest

from sage_sqs.attention import attention_items
from sage_sqs.db import Database
from sage_sqs.discoveries import DiscoveryValidationError, accept_discovery, validate_discovery
from sage_sqs.repository import Repository


def repo(tmp_path):
    return Repository(Database.open(tmp_path / "sqs.db"))


def language_payload():
    return {
        "kind": "LANGUAGE_PROFILE", "sage_version": "0.02a1",
        "observed": {"profile_id": "sw-CD", "language_code": "sw", "script": "Latn", "region": "CD"},
    }


def test_discovery_rejects_content_fields():
    payload = {**language_payload(), "scripture": "prohibited"}
    with pytest.raises(DiscoveryValidationError):
        validate_discovery(payload)


def test_duplicate_discovery_is_one_attention_item(tmp_path):
    store = repo(tmp_path)
    first = accept_discovery(store, language_payload())
    second = accept_discovery(store, language_payload())
    assert first.discovery_id == second.discovery_id
    rows = attention_items(store)
    assert len(rows) == 1
    assert rows[0]["category"] == "DISCOVERY"
    assert rows[0]["observation_count"] == 2


def test_different_discoveries_remain_distinct(tmp_path):
    store = repo(tmp_path)
    accept_discovery(store, language_payload())
    other = language_payload()
    other["observed"] = {**other["observed"], "profile_id": "sw-KE", "region": "KE"}
    accept_discovery(store, other)
    assert len(attention_items(store)) == 2
