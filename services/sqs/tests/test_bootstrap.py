from pathlib import Path

from sage_sqs.bootstrap import bootstrap_catalog
from sage_sqs.db import Database
from sage_sqs.repository import Repository


def root():
    return Path(__file__).resolve().parents[1]


def test_first_run_bootstrap_creates_review_catalog_and_attention(tmp_path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    result = bootstrap_catalog(
        repo,
        language_dir=root() / "seed" / "languages",
        provider_catalog=root() / "seed" / "openai-provider.yml",
    )
    assert result.profiles_created == 20
    assert result.models_created == 3
    assert repo.db.connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 20
    assert repo.db.connection.execute("SELECT COUNT(*) FROM models").fetchone()[0] == 3
    assert repo.db.connection.execute("SELECT COUNT(*) FROM profiles WHERE status='REVIEW_REQUIRED'").fetchone()[0] == 20
    assert repo.db.connection.execute("SELECT COUNT(*) FROM models WHERE status='REVIEW_REQUIRED'").fetchone()[0] == 3
    assert len(repo.list_attention()) >= 23


def test_bootstrap_is_idempotent(tmp_path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    kwargs = {"language_dir": root() / "seed" / "languages", "provider_catalog": root() / "seed" / "openai-provider.yml"}
    first = bootstrap_catalog(repo, **kwargs)
    second = bootstrap_catalog(repo, **kwargs)
    assert first.profiles_created == 20
    assert second.profiles_created == 0
    assert second.models_created == 0
    assert repo.db.connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 20
    assert repo.db.connection.execute("SELECT COUNT(*) FROM models").fetchone()[0] == 3


def test_bootstrap_from_config_root_uses_runtime_catalog_layout(tmp_path):
    from sage_sqs.bootstrap import bootstrap_from_config
    repo = Repository(Database.open(tmp_path / "runtime.db"))
    result = bootstrap_from_config(repo, root() / "config")
    assert result.profiles_created == 20
    assert result.models_created == 3
