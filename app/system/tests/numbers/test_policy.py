"""NCA toggle validation and immutable Run policy replay contracts."""
from __future__ import annotations

import itertools
import json

import pytest
import yaml

from sage.errors import ValidationError
from sage.jobs import JobStore
from sage.nca import create_nca_job, create_nca_run
from sage.numbers.policy import load_nca_run_snapshot
from sage.storage import storage_layout

from .test_nca_jobs import _prepare_nca_workspace, _route


@pytest.mark.parametrize(
    "values",
    list(itertools.product((False, True), repeat=3)),
)
def test_all_toggle_combinations_require_at_least_one_enabled(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
    values: tuple[bool, bool, bool],
) -> None:
    """Every exact NCA toggle combination is accepted except all OFF."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip="usWIP", package_id="SYNTHETIC_NCA_REFERENCE_1", style_selector="fixture-style/1")
    checks = dict(zip(("number_accuracy", "presentation_consistency", "footnote_review"), values))

    if any(values):
        run = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1", checks=checks)
        assert load_nca_run_snapshot(run.root)["checks"] == checks
    else:
        with pytest.raises(ValidationError) as caught:
            create_nca_run(config, job_id=job.job_id, scope_value="MAT 1", checks=checks)
        assert caught.value.code == "NCA_CHECK_POLICY_ALL_OFF"


@pytest.mark.parametrize("presentation", (False, True))
def test_selected_style_binding_remains_validated_when_presentation_is_off(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
    presentation: bool,
) -> None:
    """Disabling presentation never bypasses validation of an explicitly bound guide."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip="usWIP", package_id="SYNTHETIC_NCA_REFERENCE_1", style_selector="fixture-style/1")
    profile = storage_layout(root).styleguides_root / "numbers/fixture-style/1.yml"
    profile.unlink()

    with pytest.raises(Exception) as caught:
        create_nca_run(
            config,
            job_id=job.job_id,
            scope_value="MAT 1",
            checks={"presentation_consistency": presentation},
        )
    assert getattr(caught.value, "code", "") in {
        "NCA_STYLE_PROFILE_INVALID",
        "NCA_STYLE_PROFILE_NOT_CONFIGURED",
    }


def test_run_policy_replay_uses_sealed_style_and_ignores_job_default_changes(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resumed Run keeps its policy and exact style after Job-owned sources change."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip="usWIP", package_id="SYNTHETIC_NCA_REFERENCE_1", style_selector="fixture-style/1")
    run = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1", checks={"footnote_review": False})
    before = load_nca_run_snapshot(run.root)

    raw = yaml.safe_load(job.manifest_path.read_text(encoding="utf-8"))
    raw["defaults"]["checks"]["footnote_review"] = True
    job.manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    live_style = storage_layout(root).styleguides_root / "numbers/fixture-style/1.yml"
    live_style.write_bytes(live_style.read_bytes() + b"\n# changed after Run sealing\n")

    assert load_nca_run_snapshot(run.root) == before
    with pytest.raises(ValidationError) as caught:
        JobStore(root, root / "ecosystem.yml").revise_job(job, profiles={"number_style": "fixture-style/1"})
    assert caught.value.code == "NCA_STYLE_PROFILE_RUN_OPEN"


def test_missing_or_mutated_run_policy_fails_closed(
    make_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NCA never falls back to current defaults when its Run policy is absent or changed."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config, _style_bytes = _prepare_nca_workspace(root)
    _route(monkeypatch)
    job = create_nca_job(config, wip="usWIP", package_id="SYNTHETIC_NCA_REFERENCE_1", style_selector="fixture-style/1")
    run = create_nca_run(config, job_id=job.job_id, scope_value="MAT 1")
    policy_path = run.root / "check-policy.json"
    original = policy_path.read_bytes()
    policy_path.unlink()
    with pytest.raises(ValidationError) as absent:
        load_nca_run_snapshot(run.root)
    assert absent.value.code == "NCA_RUN_SNAPSHOT_INVALID"

    policy_path.write_bytes(original)
    document = json.loads(original)
    document["checks"] = {key: False for key in document["checks"]}
    policy_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationError) as changed:
        load_nca_run_snapshot(run.root)
    assert changed.value.code == "NCA_CHECK_POLICY_ALL_OFF"


def test_optimization_policy_is_versioned_and_preserves_hard_limits(package_root):
    """New optimization settings remain separate from sealed historical Runs and SFM limits."""
    import yaml
    from sage.numbers.policy import validate_optimization_policy
    raw = yaml.safe_load((package_root / 'system/config/workflows/nca/profile.yml').read_text())
    assert validate_optimization_policy(raw['optimization_policy']) == {
        'contract_version': 'nca-optimization-2.0', 'extraction_batch_max_units': 8,
        'request_concurrency': 1, 'transient_retries': 1, 'reuse_scope': 'TASK'}
    assert raw['evidence_policies']['default']['maximum_primary_verse_units'] == 220
    for field in ('extraction_batch_max_units', 'request_concurrency', 'transient_retries'):
        for value in ((True, -1, 1.5, '8', 2) if field == 'transient_retries' else (True, 0, -1, 1.5, '8')):
            with pytest.raises(ValidationError):
                validate_optimization_policy(dict(raw['optimization_policy'], **{field: value}))


def test_v2_policy_can_explicitly_disable_transient_retry(package_root):
    """Exact zero disables transport retry consistently with the bounded batch helper."""
    import yaml
    from sage.numbers.policy import validate_optimization_policy
    raw = yaml.safe_load((package_root / 'system/config/workflows/nca/profile.yml').read_text())['optimization_policy']
    assert validate_optimization_policy(dict(raw, transient_retries=0))['transient_retries'] == 0
