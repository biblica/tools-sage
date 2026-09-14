"""NCA governed task creation, execution, submission, and finalization contracts."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from sage.act_tasks import create_act_task, submit_act_task
from sage.errors import LockError, ValidationError
from sage.jobs import JobStore
from sage.llm_tasks import execute_task
from sage.nca import create_nca_job, create_nca_run, create_nca_task, finalize_nca_run
from sage.numbers.models import Extraction, NumericExpression
from sage.storage import storage_layout

from .test_nca_jobs import _prepare_nca_workspace, _route


class _Receipt:
    """Provide one JSON-compatible phase receipt for offline execution tests."""

    def __init__(self, phase: str) -> None:
        """Record the phase whose provider evidence this receipt represents."""
        self.phase = phase

    def to_dict(self) -> dict[str, object]:
        """Return the exact fields required by the NCA result validator."""
        versions = {
            "EXTRACTION": "nca-extraction-1.0",
            "CORRESPONDENCE": "nca-correspondence-1.0",
            "FOOTNOTE": "nca-footnote-1.0",
        }
        return {
            "phase": self.phase,
            "task_version": versions[self.phase],
            "provider": "codex",
            "model": "gpt-test",
            "reasoning_effort": "high",
            "route_id": "nca-route-fixture",
            "routing_mode": "AUTOMATIC",
            "qualification_status": "QUALIFIED",
            "prompt_sha256": "3" * 64,
            "input_sha256": "4" * 64,
            "response_sha256": "5" * 64,
            "provider_metadata": {"request_id": "offline"},
        }


from sage.numbers.model_tasks import NcaModelTasks as _RealModelTasks


class _OfflineTasks(_RealModelTasks):
    """Return conservative typed extraction without contacting a model provider."""

    route_snapshot = {
        "route_id": "nca-route-fixture",
        "provider": "codex",
        "model": "gpt-test",
        "reasoning_effort": "high",
        "capability_fingerprint": "1" * 64,
        "qualification_status": "QUALIFIED",
        "qualification_evidence_sha256": "2" * 64,
        "routing_policy_version": "fixture-1",
    }
    route_identity = {
        "route_id": "nca-route-fixture",
        "provider": "codex",
        "model_id": "gpt-test",
        "reasoning_id": "high",
        "capability_fingerprint": "1" * 64,
        "policy_version": "fixture-1",
        "routing_mode": "QUALIFIED",
        "qualification": "QUALIFIED",
        "evidence_sha256": "2" * 64,
        "routing_basis_sha256": "6" * 64,
        "selection_mode": "QUALIFIED_BEST",
        "provider_runtime_version": "fixture",
        "model_identity_strength": "EXACT",
    }

    def __init__(self, *_args, expected_route_id: str | None = None, **_kwargs) -> None:
        """Require execution to reopen the exact route sealed by the Run."""
        self._config = _args[0]
        self._timeout_seconds = 600
        self._attempts = []
        self._route = SimpleNamespace(identity=SimpleNamespace(provider='codex', model_id='gpt-test', reasoning_id='high', route_id='nca-route-fixture'),
            routing_mode='AUTOMATIC', qualification='QUALIFIED')
        self._provider_status = None
        self._executor = _EmptyTransport()
        if expected_route_id != "nca-route-fixture":
            raise AssertionError("execution did not pin the sealed route")

    def extract(self, _unit, *, language: str, style_profile):
        """Return complete empty extraction for fixture text with no numeric surface."""
        assert language == "en"
        assert style_profile
        return SimpleNamespace(value=Extraction((), "COMPLETE"), receipt=_Receipt("EXTRACTION"))

    def correspond(self, *_args, **_kwargs):
        """Leave correspondence unresolved so output reports limited evidence."""
        if getattr(self, '_phase_executor', None) is not None:
            return super().correspond(*_args, **_kwargs)
        raise ValidationError("offline fixture has no correspondence", code="NCA_MODEL_PROVIDER_FAILED")


class _EmptyTransport:
    """Return recorded no-number extraction at the physical provider boundary."""

    def execute(self, request):
        """Keep canonical tests provider-free while producing real bytes and measurements."""
        from sage.executors.base import ProviderResponse
        payload = json.loads(request.prompt)['input']
        if payload['phase'] != 'EXTRACTION':
            raise ValidationError('offline fixture has no correspondence', code='NCA_MODEL_PROVIDER_FAILED')
        raw = {'schema_version': '2.0', 'phase': 'EXTRACTION', 'batch_id': payload['batch_id'],
            'work_units': [{'input_id': x['input_id'], 'status': 'COMPLETE', 'limitations': [], 'expressions': []} for x in payload['work_units']]}
        return ProviderResponse(provider='codex', content=json.dumps(raw), model='gpt-test', reasoning_effort='high', metadata={})


def _run(make_workspace, monkeypatch: pytest.MonkeyPatch):
    """Create one fully sealed NCA Job and Run with an offline route."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(
        config,
        wip="usWIP",
        package_id="SYNTHETIC_NCA_REFERENCE_1",
        style_selector="fixture-style/1",
    )
    run = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")
    return root, config, job, run


def test_create_nca_task_is_idempotent_and_registers_exact_sealed_coverage(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated creation returns one immutable manifest and one Run ledger entry."""
    _root, config, job, run = _run(make_workspace, monkeypatch)

    first = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1")
    second = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1")

    assert first["task_manifest_path"] == second["task_manifest_path"]
    path = Path(str(first["task_manifest_path"]))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["workflow"] == "nca"
    assert manifest["operation"] == "numbers"
    assert manifest["allowed_writes"] == ["output/model-evidence.json"]
    assert manifest["expected_unit_ids"]
    assert len(manifest["expected_unit_ids"]) == len(set(manifest["expected_unit_ids"]))
    reopened = JobStore(config.root, config.settings_path).load_run(job, run.run_id)
    assert reopened.task_manifests == (str(path.resolve()),)


def test_nca_task_creation_rejects_scope_or_sealed_input_drift(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task creation never broadens the Run request or reads a damaged Run snapshot."""
    _root, config, job, run = _run(make_workspace, monkeypatch)

    with pytest.raises(ValidationError) as scope_error:
        create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1:1")
    assert scope_error.value.code == "NCA_TASK_SCOPE_MISMATCH"

    policy = run.root / "check-policy.json"
    policy.write_bytes(policy.read_bytes() + b" ")
    with pytest.raises(ValidationError):
        create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1")


def test_shared_task_creation_dispatches_nca_before_analysis_project_rules(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The low-level ACT route accepts NCA without a REFERENCE or RTC semantics."""
    _root, config, job, run = _run(make_workspace, monkeypatch)

    created = create_act_task(
        config,
        workflow="nca",
        operation="numbers",
        output_project_id="usWIP",
        contemporary_source_id=None,
        scope_value="MAT 1",
        job_id=job.job_id,
        run_id=run.run_id,
    )

    assert created["workflow"] == "nca"
    assert created["contemporary_source"] is None
    assert created["original_language_sources"] == []


def test_shared_execute_submit_and_finalize_use_nca_result_contract(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shared ACT dispatch produces, validates, and publishes one NCA machine result."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1")
    path = Path(str(created["task_manifest_path"]))
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)

    executed = execute_task(config, task_manifest=path)
    submitted = submit_act_task(config, path)
    finalized = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)

    assert executed["status"] == "EXECUTED"
    assert executed["provider"] == "codex"
    assert submitted["status"] == "FINALIZED"
    assert submitted["validation"]["format"] == "NCA_NUMBERS_RESULT_2.0"
    resumed = execute_task(config, task_manifest=path)
    assert resumed["status"] == "EXECUTED"
    result = Path(str(finalized["result_path"]))
    report = Path(str(finalized["report_path"]))
    assert result.is_file() and report.is_file()
    assert "SQS confidence checks have not been applied" in report.read_text(encoding="utf-8")
    reopened = JobStore(config.root, config.settings_path).load_run(job, run.run_id)
    assert reopened.status == "COMPLETE"
    assert reopened.result == "DONE"


def test_execution_replays_sealed_style_and_policy_after_live_job_changes(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live editable Job defaults and style bytes cannot alter an already sealed Run."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope
    )
    live_style = storage_layout(config.root).styleguides_root / "numbers/fixture-style/1.yml"
    live_style.unlink()
    store = JobStore(config.root, config.settings_path)
    store.revise_job(
        job,
        defaults={
            "checks": {
                "number_accuracy": True,
                "presentation_consistency": True,
                "footnote_review": False,
            }
        },
    )
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)

    executed = execute_task(config, task_manifest=Path(str(created["task_manifest_path"])))
    output = json.loads(
        (Path(str(created["task_manifest_path"])).parent / "output/model-evidence.json").read_text(
            encoding="utf-8"
        )
    )

    assert executed["status"] == "EXECUTED"
    assert output["check_policy"]["checks"] == {
        "number_accuracy": True,
        "presentation_consistency": True,
        "footnote_review": True,
    }


def test_submit_rejects_model_evidence_or_execution_receipt_tamper(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NCA submission retains shared output and execution receipt integrity checks."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1")
    path = Path(str(created["task_manifest_path"]))
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    execute_task(config, task_manifest=path)
    evidence = path.parent / "output/model-evidence.json"
    evidence.write_bytes(evidence.read_bytes() + b" ")

    with pytest.raises(ValidationError) as caught:
        submit_act_task(config, path)
    assert caught.value.code == "EXECUTION_RECEIPT_OUTPUT_MISMATCH"


def test_execute_rejects_full_route_drift_before_any_model_phase(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching route ID cannot conceal changed provider-model route fields."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )

    class DriftedTasks(_OfflineTasks):
        """Expose an adversarial live snapshot with one changed model field."""

        route_snapshot = {**_OfflineTasks.route_snapshot, "model": "different-model"}
        calls = 0

        def extract(self, *args, **kwargs):
            """Record any forbidden phase call after route drift."""
            type(self).calls += 1
            return super().extract(*args, **kwargs)

    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", DriftedTasks)

    with pytest.raises(ValidationError) as caught:
        execute_task(config, task_manifest=Path(str(created["task_manifest_path"])))

    assert caught.value.code == "NCA_MODEL_ROUTE_CHANGED"
    assert DriftedTasks.calls == 0


def test_unindexed_target_number_remains_in_lifecycle_coverage(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scoped target numbers outside the package index produce visible evidence findings."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )

    class NumberTransport(_EmptyTransport):
        """Supply literal numeral evidence at the actual extraction transport boundary."""

        def execute(self, request):
            """Bind the observed numeral in the unindexed fixture to its exact local span."""
            from dataclasses import replace
            response = super().execute(request)
            payload = json.loads(request.prompt)['input']
            raw = json.loads(response.content)
            for supplied, returned in zip(payload['work_units'], raw['work_units']):
                if 'Verse 2.' in supplied['text']:
                    start = supplied['text'].index('2')
                    returned['expressions'] = [{'expression_id': 'target-2', 'stream_id': supplied['stream_id'],
                        'surface': '2', 'span': {'start': start, 'end': start + 1}, 'values': ['2'],
                        'kind': 'CARDINAL', 'unit': None, 'qualifier': 'EXACT', 'role': None,
                        'role_spans': [], 'representations': []}]
            return replace(response, content=json.dumps(raw))

    class UnindexedTasks(_OfflineTasks):
        """Use the real phase validator for an unindexed numeral."""

        def __init__(self, *args, **kwargs):
            """Replace only the external transport with recorded literal evidence."""
            super().__init__(*args, **kwargs)
            self._executor = NumberTransport()

    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", UnindexedTasks)
    path = Path(str(created["task_manifest_path"]))
    execute_task(config, task_manifest=path)
    submitted = submit_act_task(config, path)
    document = json.loads(Path(str(submitted["result_path"])).read_text(encoding="utf-8"))

    verse_two = next(
        unit for unit in document["groups"] if unit["projection"]["target_references"] == ["MAT 1:2"]
    )
    verse_two = verse_two["components"][0]
    assert verse_two["final_outcome"] == "REFERENCE_NOT_INDEXED"
    assert any(finding["code"] == "NCA_REFERENCE_NOT_INDEXED" for finding in document["findings"])


def test_unindexed_empty_target_is_screened_without_a_finding(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A complete empty extraction needs no reference row and does not reduce coverage."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )
    path = Path(str(created["task_manifest_path"]))
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)

    execute_task(config, task_manifest=path)
    submitted = submit_act_task(config, path)
    document = json.loads(Path(str(submitted["result_path"])).read_text(encoding="utf-8"))

    verse_two = next(
        unit for unit in document["groups"] if unit["projection"]["target_references"] == ["MAT 1:2"]
    )
    verse_two = verse_two["components"][0]
    assert verse_two["final_outcome"] == "NOT_ASSESSED"
    assert verse_two["reading"]["semantic"]["outcome"] == "NOT_ASSESSED"
    assert verse_two["footnote"]["status"] == "NOT_REQUIRED"
    assert not any(
        finding["target_reference"] == "MAT 1:2" for finding in document["findings"]
    )


def test_concurrent_execution_invokes_one_provider_pipeline(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task-scoped lock prevents two callers from consuming model evidence twice."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )
    path = Path(str(created["task_manifest_path"]))
    entered = Event()
    release = Event()

    class BlockingTasks(_OfflineTasks):
        """Pause the first phase so another executor reaches the same task lock."""

        instances = 0

        def __init__(self, *args, **kwargs) -> None:
            """Count provider pipelines constructed inside the execution lock."""
            type(self).instances += 1
            super().__init__(*args, **kwargs)

        def _execute_physical(self, *args, **kwargs):
            """Hold the provider boundary open until the competing call is rejected."""
            entered.set()
            assert release.wait(timeout=10)
            return super()._execute_physical(*args, **kwargs)

    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", BlockingTasks)
    completed: list[object] = []
    failures: list[BaseException] = []

    def execute_first() -> None:
        """Capture the first executor result without hiding thread failures."""
        try:
            completed.append(execute_task(config, task_manifest=path))
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    worker = Thread(target=execute_first)
    worker.start()
    assert entered.wait(timeout=10)
    try:
        with pytest.raises(LockError):
            execute_task(config, task_manifest=path)
    finally:
        release.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    assert failures == []
    assert len(completed) == 1
    assert BlockingTasks.instances == 1


def test_finalize_rejects_changed_task_result_after_submission(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A report retry cannot publish a schema-valid replacement of accepted evidence."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )
    path = Path(str(created["task_manifest_path"]))
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    execute_task(config, task_manifest=path)

    import sage.nca_reporting as reporting

    renderer = reporting.render_nca_report

    def fail_render(*_args, **_kwargs):
        """Leave the finalized task intact while simulating report publication failure."""
        raise RuntimeError("fixture report failure")

    monkeypatch.setattr(reporting, "render_nca_report", fail_render)
    with pytest.raises(RuntimeError, match="fixture report failure"):
        submit_act_task(config, path)

    accepted_path = path.parent / "validation/numbers-result.json"
    accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
    accepted["provenance"]["job_id"] = "NCA-tampered"
    accepted_path.write_text(json.dumps(accepted), encoding="utf-8")
    monkeypatch.setattr(reporting, "render_nca_report", renderer)

    with pytest.raises(ValidationError) as caught:
        finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    assert caught.value.code == "ACT_INPUT_STALE"


def test_finalize_repairs_changed_published_result_and_report(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Completed Run retries regenerate publication from receipt-bound task evidence."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )
    path = Path(str(created["task_manifest_path"]))
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    execute_task(config, task_manifest=path)
    submitted = submit_act_task(config, path)
    result_path = Path(str(submitted["result_path"]))
    report_path = Path(str(submitted["report_path"]))
    original_result = result_path.read_bytes()
    original_report = report_path.read_bytes()
    JobStore(config.root, config.settings_path).revise_job(
        job,
        reporting={"primary_language": "fr", "secondary_language": None},
    )
    changed = json.loads(original_result)
    changed["provenance"]["job_id"] = "NCA-tampered"
    result_path.write_text(json.dumps(changed), encoding="utf-8")
    report_path.write_text("tampered report", encoding="utf-8")

    finalized = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)

    assert finalized["status"] == "COMPLETE"
    assert result_path.read_bytes() == original_result
    assert report_path.read_bytes() == original_report


def test_abandoned_run_task_cannot_execute_after_restart(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit stale manifest cannot execute beside its replacement Run."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )
    store = JobStore(config.root, config.settings_path)
    store.restart_run(job, run)

    class CountingTasks(_OfflineTasks):
        """Detect any provider construction for the abandoned task."""

        instances = 0

        def __init__(self, *args, **kwargs) -> None:
            """Count forbidden task router construction."""
            type(self).instances += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", CountingTasks)

    with pytest.raises(ValidationError) as caught:
        execute_task(config, task_manifest=Path(str(created["task_manifest_path"])))

    assert caught.value.code == "NCA_RUN_NOT_ACTIVE"
    assert CountingTasks.instances == 0


def test_abandoned_run_without_task_cannot_create_or_publish_one(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task creation cannot revive an abandoned Run that never owned a task."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    store = JobStore(config.root, config.settings_path)
    replacement = store.restart_run(job, run)
    runtime = config.workflow("nca")

    with pytest.raises(ValidationError) as caught:
        create_nca_task(
            config,
            job_id=job.job_id,
            run_id=run.run_id,
            scope_value=run.scope,
        )

    assert caught.value.code == "NCA_RUN_NOT_ACTIVE"
    assert store.load_run(job, run.run_id).status == "ABANDONED"
    assert store.active_run(job).run_id == replacement.run_id
    assert list(runtime.output_root.rglob("task-manifest.json")) == []


def test_restart_cannot_overtake_inflight_task_execution(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restart fails while the old task holds its provider-to-publication lock."""
    root, config, job, run = _run(make_workspace, monkeypatch)
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value=run.scope
    )
    path = Path(str(created["task_manifest_path"]))
    entered = Event()
    release = Event()

    class BlockingTasks(_OfflineTasks):
        """Hold the provider phase open across the restart attempt."""

        def _execute_physical(self, *args, **kwargs):
            """Signal execution ownership and wait for the restart assertion."""
            entered.set()
            assert release.wait(timeout=10)
            return super()._execute_physical(*args, **kwargs)

    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", BlockingTasks)
    completed: list[object] = []
    failures: list[BaseException] = []

    def execute_old() -> None:
        """Capture the old task result after restart is denied."""
        try:
            completed.append(execute_task(config, task_manifest=path))
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    worker = Thread(target=execute_old)
    worker.start()
    assert entered.wait(timeout=10)
    store = JobStore(root, root / "ecosystem.yml")
    try:
        with pytest.raises(LockError):
            store.restart_run(job, run)
    finally:
        release.set()
        worker.join(timeout=10)

    assert not worker.is_alive()
    assert failures == []
    assert len(completed) == 1
    assert [item.run_id for item in store.list_runs(job)] == [run.run_id]
    assert store.active_run(job).run_id == run.run_id


def test_finalize_publishes_both_sealed_report_languages(
    make_workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bilingual Job produces primary and secondary reports from task-sealed settings."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(
        config,
        wip="usWIP",
        package_id="SYNTHETIC_NCA_REFERENCE_1",
        style_selector="fixture-style/1",
    )
    store = JobStore(config.root, config.settings_path)
    job = store.revise_job(
        job,
        reporting={"primary_language": "en", "secondary_language": "fr"},
    )
    run = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")
    created = create_nca_task(
        config, job_id=job.job_id, run_id=run.run_id, scope_value="MAT 1"
    )
    path = Path(str(created["task_manifest_path"]))
    monkeypatch.setattr("sage.numbers.model_tasks.NcaModelTasks", _OfflineTasks)
    execute_task(config, task_manifest=path)

    submitted = submit_act_task(config, path)

    primary_path = Path(str(submitted["report_path"]))
    secondary_path = Path(str(submitted["secondary_report_path"]))
    assert submitted["secondary_report_language"] == "fr"
    assert secondary_path.name == "NUMBER-CONSISTENCY-ACCURACY.fr.md"
    assert primary_path.read_bytes() != secondary_path.read_bytes()
    sealed_secondary = secondary_path.read_bytes()
    current = store.load_job(job.job_id, tool="nca")
    store.revise_job(
        current,
        reporting={"primary_language": "en", "secondary_language": "ru"},
    )
    retried = finalize_nca_run(config, job_id=job.job_id, run_id=run.run_id)
    assert retried["secondary_report_language"] == "fr"
    assert Path(str(retried["secondary_report_path"])).read_bytes() == sealed_secondary


def test_nca_controller_checkpoint_declarations_do_not_expand_model_authority(make_workspace, monkeypatch):
    """New task controls declare private persistence while model writes stay bounded."""
    _root, config, job, run = _run(make_workspace, monkeypatch)
    task = create_nca_task(config, job_id=job.job_id, run_id=run.run_id, scope_value='MAT 1')
    manifest = json.loads(Path(task['task_manifest_path']).read_text())
    assert manifest['allowed_writes'] == ['output/model-evidence.json']
    assert set(manifest['controller_allowed_writes']) == {
        'validation/nca-phases/attempts/*.json', 'validation/nca-phases/ledger.json',
        'validation/nca-phases/publication/output.json', 'validation/nca-phases/publication/receipt.json',
        'validation/nca-phases/publication/manifest.json', 'validation/llm-execution-receipt.json',
        'validation/nca-phases/abandoned-publications/*/output.json',
        'validation/nca-phases/abandoned-publications/*/receipt.json',
        'validation/nca-phases/abandoned-publications/*/.output.json.*.tmp',
        'validation/nca-phases/abandoned-publications/*/.receipt.json.*.tmp',
        'validation/nca-phases/abandoned-publications/*/.manifest.json.*.tmp',
        'locks/nca-phases.lock', 'locks/nca-phases.lock.guard', 'locks/execution.lock.guard',
        'output/model-evidence.json', 'validation/nca-execution-failure.json'}
    assert not (Path(task['task_manifest_path']).parent / 'validation/nca-phases').exists()
