from pathlib import Path


def test_worker_is_timer_driven_oneshot():
    service = Path("deploy/systemd/sqs-worker.service").read_text(encoding="utf-8")
    timer = Path("deploy/systemd/sqs-worker.timer").read_text(encoding="utf-8")
    assert "Type=oneshot" in service
    assert "sqs-worker --drain" in service
    assert "Restart=on-failure" not in service
    assert "OnUnitActiveSec=60s" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer


def test_api_unit_has_no_openai_secret():
    service = Path("deploy/systemd/sqs-api.service").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in service
    assert "sqs-api.env" in service


def test_worker_unit_uses_separate_secret_environment():
    service = Path("deploy/systemd/sqs-worker.service").read_text(encoding="utf-8")
    assert "sqs-worker.env" in service
