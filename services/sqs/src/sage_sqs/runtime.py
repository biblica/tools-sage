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


_db_path = Path(os.environ.get("SQS_DB_PATH", "/var/lib/sage-sqs/sqs.db"))
_config_root = Path(os.environ.get("SQS_CONFIG_ROOT", "/etc/sage-sqs"))
app = create_runtime_app(db_path=_db_path, config_root=_config_root)
