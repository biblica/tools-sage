"""SQLite WAL persistence for SQS."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles(
  profile_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(profile_id, revision)
);
CREATE TABLE IF NOT EXISTS models(
  provider_family TEXT NOT NULL,
  model_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(provider_family, model_id, revision)
);
CREATE TABLE IF NOT EXISTS qualifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_family TEXT NOT NULL,
  model_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  capability TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_predecessors(
  provider_family TEXT NOT NULL,
  model_id TEXT NOT NULL,
  predecessor_model_id TEXT NOT NULL,
  PRIMARY KEY(provider_family, model_id)
);
CREATE TABLE IF NOT EXISTS evaluation_runs(
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  claimed_utc TEXT,
  completed_utc TEXT,
  error_text TEXT
);
CREATE TABLE IF NOT EXISTS evaluation_attempts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_utc TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES evaluation_runs(id)
);
CREATE TABLE IF NOT EXISTS planner_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_utc TEXT NOT NULL,
  disposition TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bundles(
  revision INTEGER PRIMARY KEY,
  created_utc TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discoveries(
  fingerprint TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS audit_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_utc TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attention_items(
  attention_key TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  observation_count INTEGER NOT NULL DEFAULT 1,
  first_seen_utc TEXT NOT NULL,
  last_seen_utc TEXT NOT NULL
);
"""


class Database:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @classmethod
    def open(cls, path: Path) -> "Database":
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        return cls(conn)
