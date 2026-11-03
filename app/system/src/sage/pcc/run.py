"""PCC Run lifecycle: seal the policy snapshot, execute, and write the Run's machine outputs.

P1 executes no analysis. A Run still seals exactly what it would read (SOURCE, optional secondary
SOURCE and WIP identities, settings, decision history) and writes schema-valid, empty outputs whose
summary and exception report say plainly that nothing was assessed. Unknown is never a pass.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from ..exception_reports import NOT_ASSESSED, ExceptionRecord, record_exception
from ..hashing import sha256_paths
from ..registry import EcosystemConfig
from ..scripture import discover_usfm_files
from ..vrs import load_project_vrs
from ..references import parse_scope
from . import ENGINE_VERSION, OPERATIONS
from .discovery import Seed, discover
from .phrases import PHRASES_FILE, read_phrases
from .source_text import source_units
from .traits import measure_traits
from .contracts import SCHEMA_VERSION, validate_record
from .ids import full_digest
from .journal import decision_snapshot_sha256, read_journal
from .jsonl import read_json, write_json, write_jsonl

SNAPSHOT_FILE = "pcc-run-snapshot.json"
OUTPUT_DIRECTORY = "pcc"
STAGES = (
    "DETERMINISTIC_PREFLIGHT",
    "SOURCE_DISCOVERY",
    "CONSISTENCY_EVALUATION",
    "COVERAGE_RECONCILIATION",
    "DETERMINISTIC_FINALISATION",
)
NOT_IMPLEMENTED_LIMITATION = (
    "PCC analysis is not implemented in this build (plan phase P1): no SOURCE expression or "
    "occurrence was assessed. This Run is not a consistency result."
)


TERMS_LIMITATION = (
    "Terms list discovery only (plan phase P3): expressions and occurrences were located in the SOURCE, "
    "but no sense or consistency was assessed. Every occurrence sense is UNRESOLVED."
)


def _terms_analysis(config: EcosystemConfig, job: Any, snapshot: dict[str, Any], output: Path, run: Any) -> dict[str, int]:
    """Function A: discover and locate SOURCE expressions, write the machine outputs, report problems."""
    source = snapshot["source"]
    units = source_units(config.project(source["project_id"]).path, parse_scope(snapshot["scope"]))
    traits = measure_traits(unit.text for unit in units)
    phrases, problems = read_phrases(job.root / "input" / PHRASES_FILE, traits)
    seeds = [Seed(p.surface, p.tokens, "LOCAL_INPUT", "TERM" if len(p.tokens) == 1 else "FIXED_PHRASE", line=p.line)
             for p in phrases]
    settings = snapshot["discovery"]
    found = discover(
        units,
        source_corpus_id=source["project_id"],
        source_sha256=source["content_sha256"],
        traits=traits,
        seeds=seeds,
        min_occurrences=settings["min_confirmed_same_sense_occurrences"],
        min_tokens=settings["min_ngram_tokens"],
        max_tokens=settings["max_ngram_tokens"],
    )
    write_jsonl(output / "expressions.jsonl", found.expressions, kind="expression", sort_key="expression_id")
    write_jsonl(output / "occurrences.jsonl", found.occurrences, kind="occurrence", sort_key="occurrence_id")
    write_jsonl(output / "expression-stats.jsonl", found.stats)
    write_json(output / "source-traits.json", {**traits.as_record(), "auto_discovery": found.auto_discovery,
                                               "units": len(units)})
    notes = [(f"PCC_PHRASE_NOT_IN_SOURCE", f"{PHRASES_FILE} line {s.line}: '{s.surface}' does not occur in the SOURCE scope; "
              "kept on the list with zero occurrences.", f"{PHRASES_FILE}:{s.line}") for s in found.unfound]
    notes += [("PCC_PHRASE_LINE_INVALID", f"{PHRASES_FILE} line {p.line}: {p.reason}; the line was not used.",
               f"{PHRASES_FILE}:{p.line}") for p in problems]
    if found.auto_discovery != "RAN":
        notes.append(("PCC_DISCOVERY_PARTIAL", "The SOURCE script is written without spaces: automatic phrase "
                      "discovery was skipped; only listed phrases were located.", snapshot["scope"]))
    for code, message, coordinate in notes:
        record_exception(run.root, ExceptionRecord(
            tool="pcc", code=code, message=message, effect=NOT_ASSESSED, run_id=run.run_id, job_id=job.job_id,
            stage=STAGES[1], coordinates=(coordinate,), severity="WARNING"))
    return {"expressions": len(found.expressions), "occurrences": len(found.occurrences), "notes": len(notes)}


def _utc_now() -> str:
    """Return the current UTC time in SAGE's second-precision ISO form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def project_identity(config: EcosystemConfig, project_id: str) -> dict[str, Any]:
    """Return the content and versification fingerprint of one bound Scripture Project."""
    project = config.project(project_id)
    files = discover_usfm_files(project.path)
    if not files:
        raise ValidationError(
            f"PCC Project {project_id} has no Scripture files",
            code="PCC_PROJECT_EMPTY",
            next_action=f"Check that {project_id} is the intended Project and that its books are present.",
            details={"project_id": project_id},
        )
    schema = load_project_vrs(config, project)
    return {
        "project_id": project_id,
        "language_tag": project.language_code,
        "content_sha256": sha256_paths(files, relative_to=project.path),
        "versification_sha256": schema.to_dict()["effective_sha256"],
    }


def build_run_snapshot(
    config: EcosystemConfig,
    job: Any,
    *,
    run_id: str,
    operation: str,
    scope: str,
) -> dict[str, Any]:
    """Return the sealed, validated policy snapshot for one PCC Run."""
    if operation not in OPERATIONS:
        raise ValidationError(f"Unsupported PCC operation: {operation}", code="PCC_OPERATION_INVALID")
    wip = job.bindings.get("wip")
    if operation == "check" and not wip:
        raise ValidationError(
            "A PCC consistency check needs a WIP bound to the Job",
            code="PCC_WIP_REQUIRED",
            next_action="Create the PCC Job with the WIP Project, or run the terms list instead.",
        )
    secondary = job.bindings.get("secondary_source")
    defaults = job.defaults
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "job_id": job.job_id,
        "operation": operation,
        "scope": scope,
        "source": project_identity(config, job.bindings["source"]),
        "secondary_source": project_identity(config, secondary) if secondary else None,
        "target": project_identity(config, wip) if wip and operation == "check" else None,
        "target_language": defaults["target_language"],
        "source_authority": "PRIMARY_CONTROLS" if secondary else "SINGLE_SOURCE",
        "discovery": dict(defaults["discovery"]),
        "analysis": dict(defaults["analysis"]),
        "decision_snapshot_sha256": decision_snapshot_sha256(read_journal(job.root)),
        "engine_version": ENGINE_VERSION,
        "created_utc": _utc_now(),
    }
    return validate_record("run_snapshot", snapshot, where=SNAPSHOT_FILE)


def run_initializer(config: EcosystemConfig, job: Any, *, operation: str, scope: str) -> Callable[[Path], None]:
    """Return the ``JobStore.create_run`` initializer that seals the snapshot into a new Run root."""
    def initialize(run_root: Path) -> None:
        """Seal this Run's snapshot into its new root before the Run becomes current."""
        snapshot = build_run_snapshot(config, job, run_id=run_root.name, operation=operation, scope=scope)
        write_json(run_root / "validation" / SNAPSHOT_FILE, snapshot, kind="run_snapshot")

    return initialize


def load_run_snapshot(run_root: Path) -> dict[str, Any]:
    """Read and validate one Run's sealed snapshot."""
    return read_json(run_root / "validation" / SNAPSHOT_FILE, kind="run_snapshot")


def execute_pcc_run(store: Any, config: EcosystemConfig, job: Any, run: Any) -> dict[str, Any]:
    """Execute one PCC Run deterministically and return its summary.

    Integrity guards (a changed SOURCE, WIP or decision history) stop the Run; everything else is
    reported. In P1 the analysis stages assess nothing and say so.
    """
    snapshot = load_run_snapshot(run.root)
    if snapshot["run_id"] != run.run_id or snapshot["job_id"] != job.job_id:
        raise ValidationError("PCC Run snapshot belongs to another Run", code="PCC_RUN_SNAPSHOT_MISMATCH")
    current = build_run_snapshot(
        config, job, run_id=run.run_id, operation=snapshot["operation"], scope=snapshot["scope"],
    )
    for field in ("source", "secondary_source", "target", "decision_snapshot_sha256"):
        if current[field] != snapshot[field]:
            raise ValidationError(
                f"PCC Run input changed after the Run was created: {field}",
                code="PCC_RUN_INPUT_STALE",
                next_action="Abandon this Run and start a new one so it seals the current inputs.",
                details={"run_id": run.run_id, "field": field},
            )
    store._update_run_for_job(job, run, status="RUNNING", current_stage=STAGES[0])
    output = run.root / "validation" / OUTPUT_DIRECTORY
    target = snapshot["target"]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.run_id,
        "created_utc": snapshot["created_utc"],
        "job_id": job.job_id,
        "operation": snapshot["operation"],
        "source_corpus_id": snapshot["source"]["project_id"],
        "target_corpus_id": target["project_id"] if target else None,
        "source_corpus_sha256": snapshot["source"]["content_sha256"],
        "target_corpus_sha256": target["content_sha256"] if target else None,
        "reference_index_version": None,
        "profile_version": "measured-from-text-p1",
        "config_sha256": full_digest({key: snapshot[key] for key in ("discovery", "analysis", "scope")}),
        "decision_snapshot_sha256": snapshot["decision_snapshot_sha256"],
        "engine_version": ENGINE_VERSION,
        "semantic_review_mode": snapshot["analysis"]["semantic_assistance"],
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.run_id,
        "operation": snapshot["operation"],
        "source_corpus_id": snapshot["source"]["project_id"],
        "target_corpus_id": target["project_id"] if target else None,
        "eligible_groups": 0,
        "evaluated_groups": 0,
        "fully_resolved_groups": 0,
        "eligible_occurrences": 0,
        "evaluated_occurrences": 0,
        "review_groups": 0,
        "blocked_groups": 0,
        "findings_by_code": {},
        "limitations": [NOT_IMPLEMENTED_LIMITATION],
    }
    terms = snapshot["operation"] == "terms"
    counts = _terms_analysis(config, job, snapshot, output, run) if terms else None
    if counts:
        summary["eligible_groups"] = counts["expressions"]
        summary["eligible_occurrences"] = counts["occurrences"]
        summary["limitations"] = [TERMS_LIMITATION]
    write_json(output / "run-manifest.json", manifest, kind="run_manifest")
    write_jsonl(output / "findings.jsonl", [], kind="finding", sort_key="finding_id")
    write_jsonl(output / "occurrence-audit.jsonl", [], kind="occurrence_audit", sort_key="occurrence_id")
    write_json(output / "summary.json", summary, kind="summary")
    if not terms:
        record_exception(
            run.root,
            ExceptionRecord(
                tool="pcc",
                code="PCC_ANALYSIS_NOT_IMPLEMENTED",
                message=NOT_IMPLEMENTED_LIMITATION,
                effect=NOT_ASSESSED,
                run_id=run.run_id,
                job_id=job.job_id,
                stage=STAGES[1],
                coordinates=(snapshot["scope"],),
                severity="WARNING",
            ),
        )
    if terms and not counts["notes"]:
        store._update_run_for_job(job, run, status="COMPLETE", current_stage=STAGES[-1], result="DONE")
    else:
        store._update_run_for_job(
            job, run, status="COMPLETE_WITH_EXCEPTIONS", current_stage=STAGES[-1], result="DONE",
            result_reason="PCC_TERMS_NOTES" if terms else "PCC_ANALYSIS_NOT_IMPLEMENTED",
        )
    return summary
