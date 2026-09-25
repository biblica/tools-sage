from pathlib import Path

from fastapi.testclient import TestClient

from sage_sqs.runtime import create_runtime_app


def test_runtime_bootstraps_catalog_from_config_root(tmp_path):
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "sqs.db"
    app = create_runtime_app(db_path=db_path, config_root=root / "config")
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "DEGRADED"
    import sqlite3
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 20
    assert conn.execute("SELECT COUNT(*) FROM models").fetchone()[0] == 3
