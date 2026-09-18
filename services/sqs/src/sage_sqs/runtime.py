"""Environment-wired FastAPI runtime entrypoint with first-run catalog bootstrap."""
from __future__ import annotations

import os
from pathlib import Path

from .api import create_app
from .bootstrap import bootstrap_from_config
from .db import Database
from .repository import Repository


def create_runtime_app(*, db_path: Path, config_root: Path):
    repo = Repository(Database.open(Path(db_path)))
    bootstrap_from_config(repo, Path(config_root))
    return create_app(repo)


def create_app_from_env():
    """uvicorn factory entrypoint (`uvicorn sage_sqs.runtime:create_app_from_env --factory`).

    Deliberately not a module-level `app` global: opening the database and
    bootstrapping the catalog are side effects that must happen only when the
    app is actually being constructed, not on every import of this module.
    """
    db_path = Path(os.environ.get("SQS_DB_PATH", "/var/lib/sage-sqs/sqs.db"))
    config_root = Path(os.environ.get("SQS_CONFIG_ROOT", "/etc/sage-sqs"))
    return create_runtime_app(db_path=db_path, config_root=config_root)
