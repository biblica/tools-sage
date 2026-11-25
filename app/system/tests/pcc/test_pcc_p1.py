"""PCC phase P1: contracts, identifiers, strict storage, decision journal, Job contract and empty Run."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sage.errors import ConfigurationError, SageError, ValidationError
from sage.jobs import JobStore, pcc_default_settings
from sage.pcc import ids
from sage.pcc.contracts import CONTRACTS, contract_errors, validate_record
from sage.pcc.journal import append_review_event, decision_snapshot_sha256, journal_path, materialize, read_journal
from sage.pcc.jsonl import read_json, read_jsonl, write_jsonl
from sage.pcc.run import SNAPSHOT_FILE, execute_pcc_run, load_run_snapshot, run_initializer
from sage.registry import load_ecosystem

HANDOVER = Path(__file__).resolve().parent / "fixtures" / "handover"
SHA = "a" * 64

# Handover contracts SAGE keeps unchanged: SAGE kind -> (handover schema, sample file).
UNCHANGED = {
    "expression": ("expression", "expressions.example.jsonl"),
    "occurrence": ("occurrence", "occurrences.example.jsonl"),
    "alignment": ("alignment", "alignments.example.jsonl"),
    "variant_rule": ("variant_rule", "variant-rules.example.jsonl"),
    "exception": ("exception", "exceptions.example.jsonl"),
    "finding": ("finding", "findings.example.jsonl"),
    "occurrence_audit": ("occurrence_audit", "occurrence-audit.example.jsonl"),
    "language_profile": ("language_profile", "language-profile.example.json"),
    "index_manifest": ("corpus_manifest", "corpus-manifest.example.json"),
}


def _samples(name: str) -> list[dict]:
    """Return the records of one handover sample file."""
    path = HANDOVER / "samples" / name
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(path.read_text(encoding="utf-8"))]


def _mutations(record: dict) -> list[dict]:
    """Drop each field, add an unknown field, and give each field a wrongly typed value."""
    variants = [{**record, "unexpected_field": 1}]
    for key in record:
        dropped = dict(record)
        dropped.pop(key)
        variants.append(dropped)
        for wrong in (None, 7, "", [], {}, True):
            variants.append({**record, key: wrong})
    return variants


@pytest.mark.parametrize("kind", sorted(UNCHANGED))
def test_handover_samples_satisfy_the_sage_contracts(kind: str) -> None:
    """Verify that the handover samples satisfy the SAGE contracts."""
    _, sample = UNCHANGED[kind]
    for record in _samples(sample):
        assert contract_errors(kind, record) == []


@pytest.mark.parametrize("kind", sorted(UNCHANGED))
def test_sage_validator_agrees_with_the_handover_json_schema(kind: str) -> None:
    """Verify that the SAGE validator agrees with the handover JSON Schema on every mutation."""
    jsonschema = pytest.importorskip("jsonschema")
    schema_name, sample = UNCHANGED[kind]
    schema = json.loads((HANDOVER / "contracts" / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for record in _samples(sample):
        for variant in _mutations(record):
            expected = validator.is_valid(variant)
            assert (contract_errors(kind, variant) == []) is expected, (kind, variant)


def test_adapted_contracts_accept_the_handover_samples_after_the_recorded_mapping() -> None:
    """Verify that adapted contracts accept the handover samples after the recorded mapping."""
    event = _samples("review-events.example.jsonl")[0]
    event["job_id"] = event.pop("brief_id")
    event.update(target_language="en", policy_version="pcc-decisions-1", previous_event_id=None)
    validate_record("review_event", event)

    manifest = _samples("run-manifest.example.json")[0]
    manifest["job_id"] = manifest.pop("brief_id")
    manifest["operation"] = "check"
    validate_record("run_manifest", manifest)

    summary = _samples("summary.example.json")[0]
    summary["operation"] = "check"
    validate_record("summary", summary)
    summary.update(operation="terms", target_corpus_id=None)
    validate_record("summary", summary)


def test_validator_rejects_booleans_as_integers_and_lists_every_problem() -> None:
    """Verify that validator rejects booleans as integers and lists every problem."""
    summary = _samples("summary.example.json")[0]
    summary.update(operation="check", eligible_groups=True, blocked_groups=-1)
    with pytest.raises(ValidationError) as caught:
        validate_record("summary", summary)
    assert caught.value.code == "PCC_CONTRACT_INVALID"
    assert len(caught.value.details["errors"]) == 2


def test_ids_are_deterministic_namespaced_and_order_independent() -> None:
    """Verify that IDs are deterministic namespaced and order independent."""
    first = ids.finding_id(SHA, "PC10", ["OCC-2", "OCC-1"], "x")
    assert first == ids.finding_id(SHA, "PC10", ["OCC-1", "OCC-2"], "x")
    assert first.startswith("PCF-") and len(first) == 4 + ids.DIGEST_HEX
    assert ids.expression_id(SHA, "stand firm") != ids.expression_id(SHA, "stand  firm")
    registry = ids.IdRegistry()
    assert registry.mint("group", {"a": 1}) == registry.mint("group", {"a": 1})


def test_strict_jsonl_reports_file_and_line_and_never_skips(tmp_path: Path) -> None:
    """Verify that strict JSONL reports file and line and never skips."""
    path = tmp_path / "findings.jsonl"
    path.write_text('{"a": 1}\n\n{"a": 1, "a": 2}\n', encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        read_jsonl(path)
    assert caught.value.code == "PCC_FILE_MALFORMED" and caught.value.details["line"] == 3
    path.write_bytes(b'{"a": "\xff"}\n')
    with pytest.raises(ValidationError) as caught:
        read_jsonl(path)
    assert caught.value.code == "PCC_FILE_ENCODING_INVALID"
    path.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        read_jsonl(path)
    path.write_text('{"x": NaN}\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        read_jsonl(path)


def test_jsonl_writes_are_sorted_validated_and_byte_stable(tmp_path: Path) -> None:
    """Verify that JSONL writes are sorted validated and byte stable."""
    rows = _samples("findings.example.jsonl")
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_jsonl(first, rows, kind="finding", sort_key="finding_id")
    write_jsonl(second, list(reversed(rows)), kind="finding", sort_key="finding_id")
    assert first.read_bytes() == second.read_bytes()
    assert read_jsonl(first, kind="finding")[0]["finding_id"] == "PCF-SYN-PC10-001"
    broken = copy.deepcopy(rows[0])
    broken["code"] = "PC99"
    with pytest.raises(ValidationError):
        write_jsonl(tmp_path / "c.jsonl", [broken], kind="finding")
    assert not (tmp_path / "c.jsonl").exists()


def _event(job_root: Path, tmp_path: Path, operation: str = "APPROVE", subject: str = "RULE-1") -> dict:
    """Append one fixture decision event to the Job journal."""
    return append_review_event(
        job_root,
        lock_path=tmp_path / "locks" / "journal.lock",
        actor_id="operator",
        operation=operation,
        subject_type="VARIANT_RULE",
        subject_id=subject,
        rationale="Team chose this rendering.",
        scope={"level": "SECG", "identifier": "SECG-1"},
        job_id="PCC_SRC-en",
        source_corpus_sha256=SHA,
        target_language="en",
        evidence_refs=["OCC-2", "OCC-1", "OCC-1"],
    )


def test_journal_is_append_only_chained_and_materialized(tmp_path: Path) -> None:
    """Verify that journal is append only chained and materialized."""
    job_root = tmp_path / "job"
    assert read_journal(job_root) == [] and decision_snapshot_sha256([]) == decision_snapshot_sha256([])
    first = _event(job_root, tmp_path)
    second = _event(job_root, tmp_path, operation="REVOKE")
    events = read_journal(job_root)
    assert [event["event_id"] for event in events] == [first["event_id"], second["event_id"]]
    assert second["previous_event_id"] == first["event_id"]
    assert first["evidence_refs"] == ["OCC-1", "OCC-2"]
    assert materialize(events)[("VARIANT_RULE", "RULE-1")]["operation"] == "REVOKE"
    assert decision_snapshot_sha256(events) != decision_snapshot_sha256(events[:1])


def test_journal_fails_closed_when_history_is_edited_or_reordered(tmp_path: Path) -> None:
    """Verify that journal fails closed when history is edited or reordered."""
    job_root = tmp_path / "job"
    _event(job_root, tmp_path)
    _event(job_root, tmp_path, subject="RULE-2")
    path = journal_path(job_root)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        read_journal(job_root)
    assert caught.value.code == "PCC_JOURNAL_CHAIN_BROKEN"
    edited = json.loads(lines[0])
    edited["rationale"] = "Rewritten later."
    path.write_text(json.dumps(edited) + "\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        read_journal(job_root)
    assert caught.value.code == "PCC_JOURNAL_EVENT_INVALID"


def _store(make_workspace) -> tuple[JobStore, object]:
    """Return a JobStore and configuration for a fresh validated workspace."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    return JobStore(config.root, config.settings_path), config


def test_pcc_job_binds_source_without_wip_and_needs_no_grammar_profile(make_workspace) -> None:
    """Verify that PCC job binds source without WIP and needs no grammar profile."""
    store, _ = _store(make_workspace)
    job = store.create_job(
        tool="pcc", job_id="", display_name="Terms list",
        bindings={"source": "usNIVv2"}, defaults=pcc_default_settings("sw"),
    )
    assert job.job_id == "PCC_usNIVv2-sw"
    assert job.profiles == {} and job.output_project == "usNIVv2" and job.contemporary_source == "usNIVv2"
    runtime = load_ecosystem(job.runtime_settings_path)
    assert runtime.project("usNIVv2").content_state == "LOCKED"
    assert runtime.project("usNIVv2").scope.roles == ("REFERENCE",)
    assert "usWIP" not in {key for key, value in runtime.projects.items() if value.enabled}
    reloaded = store.load_job(job.job_id, tool="pcc")
    assert reloaded.defaults == pcc_default_settings("sw")
    assert "Decision journal" in (job.root / "README.md").read_text(encoding="utf-8")


def test_pcc_job_with_wip_and_secondary_source(make_workspace) -> None:
    """Verify that PCC job with WIP and secondary source."""
    store, _ = _store(make_workspace)
    job = store.create_job(
        tool="pcc", job_id="PCC_usNIVv2-usWIP", display_name="Check",
        bindings={"source": "usNIVv2", "secondary_source": "usNIRVv2", "wip": "usWIP"},
        defaults=pcc_default_settings("en"),
    )
    runtime = load_ecosystem(job.runtime_settings_path)
    assert runtime.project("usWIP").content_state == "UNDER_REVIEW"
    assert runtime.project("usNIRVv2").scope.roles == ("AUXILIARY_SCRIPTURE",)


@pytest.mark.parametrize(
    ("bindings", "defaults", "code"),
    [
        ({"source": "usNIVv2", "wip": "usNIVv2"}, pcc_default_settings("en"), "PROJECT_ROLE_CONFLICT"),
        ({"source": "usNIVv2", "wip": "usWIP"}, pcc_default_settings("sw"), "PCC_TARGET_LANGUAGE_MISMATCH"),
        ({"source": "usNIVv2"}, {"target_language": "sw"}, "PCC_JOB_DEFAULTS_INVALID"),
        ({"source": "usWIP"}, pcc_default_settings("sw"), "PROJECT_BINDING_MISMATCH"),
        ({"wip": "usWIP"}, pcc_default_settings("en"), "PROJECT_BINDING_MISMATCH"),
    ],
)
def test_pcc_job_creation_rejects_invalid_contracts(make_workspace, bindings, defaults, code) -> None:
    """Verify that PCC job creation rejects invalid contracts."""
    store, _ = _store(make_workspace)
    with pytest.raises(SageError) as caught:
        store.create_job(tool="pcc", job_id="", display_name="x", bindings=bindings, defaults=defaults)
    assert caught.value.code == code


def test_pcc_defaults_reject_advisory_model_use_and_inverted_ngram_window(make_workspace) -> None:
    """Verify that PCC defaults reject advisory model use and inverted ngram window."""
    store, _ = _store(make_workspace)
    advisory = pcc_default_settings("sw")
    advisory["analysis"]["semantic_assistance"] = "ADVISORY"
    inverted = pcc_default_settings("sw")
    inverted["discovery"].update(min_ngram_tokens=4, max_ngram_tokens=2)
    for defaults in (advisory, inverted):
        with pytest.raises(ValidationError) as caught:
            store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"},
                             defaults=defaults)
        assert caught.value.code == "PCC_JOB_DEFAULTS_INVALID"


def test_pcc_target_language_is_immutable(make_workspace) -> None:
    """Verify that PCC target language is immutable."""
    store, _ = _store(make_workspace)
    job = store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"},
                           defaults=pcc_default_settings("sw"))
    with pytest.raises(ValidationError) as caught:
        store.revise_job(job, defaults=pcc_default_settings("fr"))
    assert caught.value.code == "PCC_TARGET_LANGUAGE_IMMUTABLE"


def test_tampered_pcc_identity_fails_to_load(make_workspace) -> None:
    """Verify that tampered PCC identity fails to load."""
    store, _ = _store(make_workspace)
    job = store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"},
                           defaults=pcc_default_settings("sw"))
    manifest = job.manifest_path.read_text(encoding="utf-8").replace("target_language: sw", "target_language: fr")
    job.manifest_path.write_text(manifest, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        store.load_job(job.job_id, tool="pcc")


def _run(store: JobStore, job, operation: str = "terms"):
    """Create one PCC Run with its sealed snapshot."""
    config = load_ecosystem(store.ensure_runtime_files(job))
    run = store.create_run(
        job, operation=operation, scope="MAT 1",
        initialize_run=run_initializer(config, job, operation=operation, scope="MAT 1"),
    )
    return config, run


def test_terms_run_seals_inputs_and_discovers_without_assessing_senses(make_workspace) -> None:
    """Verify that a terms Run seals inputs, writes discovery outputs and claims no sense assessment."""
    store, _ = _store(make_workspace)
    job = store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"},
                           defaults=pcc_default_settings("sw"))
    (job.root / "input").mkdir(parents=True, exist_ok=True)
    (job.root / "input" / "phrases.txt").write_text("zzqx never occurs\n!!!\n", encoding="utf-8")
    config, run = _run(store, job)
    snapshot = load_run_snapshot(run.root)
    assert snapshot["source"]["project_id"] == "usNIVv2" and snapshot["target"] is None
    assert snapshot["source_authority"] == "SINGLE_SOURCE"
    summary = execute_pcc_run(store, config, job, run)
    assert summary["evaluated_occurrences"] == 0 and "sense evidence" in summary["limitations"][0]
    output = run.root / "validation" / "pcc"
    read_json(output / "run-manifest.json", kind="run_manifest")
    read_json(output / "summary.json", kind="summary")
    assert read_jsonl(output / "findings.jsonl", kind="finding") == []
    expressions = read_jsonl(output / "expressions.jsonl", kind="expression")
    occurrences = read_jsonl(output / "occurrences.jsonl", kind="occurrence")
    assert summary["eligible_groups"] == len(expressions) and summary["eligible_occurrences"] == len(occurrences)
    assert read_json(output / "source-traits.json")["units"] > 0
    exceptions = (run.root / "diagnostics" / "EXCEPTION-REPORTS.jsonl").read_text(encoding="utf-8")
    assert "PCC_PHRASE_NOT_IN_SOURCE" in exceptions and "phrases.txt line 1" in exceptions
    assert "PCC_SENSE_NOT_ASSESSED" in exceptions or (output / "groups.jsonl").is_file()
    assert "PCC_PHRASE_LINE_INVALID" in exceptions and "phrases.txt line 2" in exceptions
    assert store.load_run(job, run.run_id).status == "COMPLETE_WITH_EXCEPTIONS"


def test_check_run_on_a_tiny_text_claims_no_pass(make_workspace) -> None:
    """A check over three placeholder verses runs, writes contract outputs and claims nothing it did not check."""
    store, _ = _store(make_workspace)
    job = store.create_job(tool="pcc", job_id="", display_name="x",
                           bindings={"source": "usNIVv2", "wip": "usWIP"},
                           defaults=pcc_default_settings("en"))
    config, run = _run(store, job, operation="check")
    summary = execute_pcc_run(store, config, job, run)
    assert summary["fully_resolved_groups"] == 0 and "Forward consistency check" in summary["limitations"][0]
    exceptions = (run.root / "diagnostics" / "EXCEPTION-REPORTS.jsonl").read_text(encoding="utf-8")
    assert "PCC_KIND_BEST_EFFORT" in exceptions and "PCC_NEGATION_NOT_CHECKED" in exceptions
    output = run.root / "validation" / "pcc"
    read_json(output / "summary.json", kind="summary")
    read_jsonl(output / "occurrence-audit.jsonl", kind="occurrence_audit")


def test_run_outputs_are_identical_for_identical_inputs(make_workspace) -> None:
    """Verify that run outputs are identical for identical inputs."""
    store, _ = _store(make_workspace)
    job = store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"},
                           defaults=pcc_default_settings("sw"))
    outputs = []
    for _ in range(2):
        config, run = _run(store, job)
        execute_pcc_run(store, config, job, run)
        summary = json.loads((run.root / "validation" / "pcc" / "summary.json").read_text(encoding="utf-8"))
        summary.pop("run_id")
        outputs.append(summary)
    assert outputs[0] == outputs[1]


def test_run_stops_when_the_source_changes_after_sealing(make_workspace) -> None:
    """Verify that run stops when the source changes after sealing."""
    store, config = _store(make_workspace)
    job = store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"},
                           defaults=pcc_default_settings("sw"))
    runtime, run = _run(store, job)
    source_file = runtime.project("usNIVv2").path / "41MAT.SFM"
    source_file.write_text(source_file.read_text(encoding="utf-8") + "\\v 9 Added later.\n", encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        execute_pcc_run(store, runtime, job, run)
    assert caught.value.code == "PCC_RUN_INPUT_STALE"


def test_check_run_requires_a_wip_and_only_one_active_run(make_workspace) -> None:
    """Verify that check run requires a WIP and only one active run."""
    store, _ = _store(make_workspace)
    terms_only = store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"},
                                  defaults=pcc_default_settings("sw"))
    with pytest.raises(ValidationError) as caught:
        _run(store, terms_only, operation="check")
    assert caught.value.code == "PCC_WIP_REQUIRED"
    job = store.create_job(tool="pcc", job_id="", display_name="x",
                           bindings={"source": "usNIVv2", "wip": "usWIP"}, defaults=pcc_default_settings("en"))
    _, run = _run(store, job, operation="check")
    assert load_run_snapshot(run.root)["target"]["project_id"] == "usWIP"
    with pytest.raises(ValidationError) as caught:
        _run(store, job)
    assert caught.value.code == "PCC_RUN_ALREADY_ACTIVE"
    with pytest.raises(ValidationError) as caught:
        store.create_run(job, operation="numbers", scope="MAT 1")
    assert caught.value.code == "JOB_OPERATION_MISMATCH"


def test_reference_resources_stay_byte_identical(make_workspace) -> None:
    """Verify that reference resources stay byte identical."""
    store, _ = _store(make_workspace)
    job = store.create_job(tool="pcc", job_id="", display_name="x",
                           bindings={"source": "usNIVv2", "wip": "usWIP"}, defaults=pcc_default_settings("en"))
    config = load_ecosystem(store.ensure_runtime_files(job))
    files = sorted(config.project("usNIVv2").path.rglob("*")) + sorted(config.project("usWIP").path.rglob("*"))
    before = {path: path.read_bytes() for path in files if path.is_file()}
    runtime, run = _run(store, job, operation="check")
    execute_pcc_run(store, runtime, job, run)
    assert {path: path.read_bytes() for path in before} == before


def test_every_contract_kind_has_a_spec_and_the_snapshot_file_is_documented() -> None:
    """Verify that every contract kind has a spec and the snapshot file is documented."""
    assert {"job_defaults", "run_snapshot", "review_event"} <= set(CONTRACTS)
    schema = Path(__file__).resolve().parents[2] / "config" / "schemas" / "pcc-run-snapshot.schema.yml"
    assert SNAPSHOT_FILE in schema.read_text(encoding="utf-8")
