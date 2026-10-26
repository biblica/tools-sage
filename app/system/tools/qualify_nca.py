#!/usr/bin/env python3
"""NCA release gate: an LLM-built gold set and a live benchmark for one reference package.

No hand labelling. Every label is deterministic code or LLM-built:

1. select  -- deterministic, seeded selection of indexed coordinates, stratified across the
              hard classes a typed package records (fractions, large numbers, dates, measures,
              NIV-only and OL-only rows, apparatus variants, "one", long lists, ...).
2. sut     -- the production NCA extraction route (the Skill route SAGE resolves today) runs once
              per WIP over the selected verses, through the same projection, batching, extraction
              and local comparison code a Run uses.
3. judge   -- two independent judge models (not the model under test) label each verse:
              (a) the values the counting convention counts in the WIP verse; a gold value list
                  exists only where both judges agree, and disputed verses are reported, never
                  silently resolved;
              (b) for every FAIL, one call per FAIL so a verdict never depends on its batch
                  neighbours: the cause, judged against the product policy (only a changed
                  quantity is a FAIL; omissions, additions, conversions and restructurings are
                  review). VALUE_CHANGED is GENUINE; every other cause is a FALSE_ALARM.
4. gate    -- deterministic metrics and the release-gate receipt:
              * FAIL precision = FAILs both judges call GENUINE / all FAILs (a split verdict
                counts against precision);
              * false-FAIL rate = FAILs not called GENUINE / assessed verses: unlike precision it
                does not depend on how many real errors the WIPs happen to contain;
              * each FAIL is also marked, by code, READ_CORRECTLY (the extracted values equal the
                gold values, so the comparison or convention made the call) or MISREAD;
              * extraction recall = verses whose extracted values equal the gold values;
              * planted-error detection = verses that PASS are compared again against the index
                with one expected value changed, which must FAIL.
5. plant   -- end-to-end planted errors in real WIP text: for verses that PASS with gold values,
              one judge rewrites the verse with one counted number raised by one; every judge
              must then count exactly the planned values in the rewritten verse. The edit is
              applied inside that verse of the book's USFM (kept only when recompiling changes
              that verse alone, as planned) and the production route runs on it; it must FAIL.
              Every ratio carries a Wilson 95% interval. A check FAILs when the whole interval is
              on the wrong side of its bar, PASSes when the measured value is on the right side on
              enough evidence, and is otherwise INSUFFICIENT_EVIDENCE. The gate checks the
              false-FAIL rate, extraction recall, both planted-error measures and two languages;
              FAIL precision is reported beside them.
              A verse the provider never answered is left out of every measure and makes the
              receipt INCOMPLETE; rerun the sut step for that WIP once the provider is available.

The receipt holds coordinates, values and verdict labels only -- never WIP text or judge
reasons -- so it can be committed to the public repository. WIP text, judge reasons and raw
responses stay in the local work directory under runtime_state_root/nca-benchmarks.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable, Iterable, Mapping, Sequence


APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT / "system" / "src"))

GATE_SCHEMA = "1.2"
# FAIL precision is reported, not gated: it depends on how many real errors the WIPs happen to
# contain (about 0.3% of verses), so a run of a few hundred verses cannot show it. The gate bounds
# the false-FAIL rate per verse instead, which is what a reviewer pays for.
FALSE_FAIL_RATE_MAX = Fraction(1, 200)
EXTRACTION_RECALL_MIN = Fraction(19, 20)
PLANTED_DETECTION_MIN = Fraction(19, 20)
TEXT_PLANT_DETECTION_MIN = Fraction(19, 20)
# Fewest measured cases on which a ratio may PASS; below this a check can only FAIL or be
# INSUFFICIENT_EVIDENCE.
MIN_EVIDENCE = {"false_fail_rate": 300, "extraction_recall": 100, "planted_detection": 100,
                "text_plant_detection": 60}
WILSON_Z = 1.96
# Hard classes, filled rarest first so every class is represented before common ones.
CLASS_ORDER = ("APPARATUS", "FRACTION", "NIV_ONLY", "OL_ONLY", "DATE", "LARGE", "MEASURE",
               "COMPOUND", "MULTI", "ONE", "TIME", "PLAIN")
JUDGE_BATCH = 20
PROVIDER_FAILURE = "NCA_MODEL_PROVIDER_FAILED"
CONVENTION = APP_ROOT / "system/skills/nca-numbers/references/COUNTING-CONVENTION.md"


def _sha256(payload: bytes) -> str:
    """Return the lowercase SHA-256 of exact bytes."""
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: object) -> bytes:
    """Encode one JSON value with stable ordering for identities."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    """Publish one JSON document atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    staging.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(staging, path)


def _fraction(raw: object) -> Fraction | None:
    """Read one judge or SAGE value ("12", "3/2", "0.5"); None when it is not a number."""
    try:
        return Fraction(str(raw).strip())
    except (ValueError, ZeroDivisionError):
        return None


# --- 1. deterministic selection -------------------------------------------------------------

def row_classes(row) -> tuple[str, ...]:
    """Name the hard classes one typed reference row belongs to."""
    values = tuple(row.ol_values) or tuple(row.niv_values)
    items = tuple(row.ol_items) or tuple(row.niv_items)
    kinds = {str(item.get("KIND") or "") for item in items}
    roles = {str(item.get("ROLE") or "") for item in items}
    found = []
    if not row.ol_values:
        found.append("NIV_ONLY")
    elif not row.niv_values:
        found.append("OL_ONLY")
    if any(value.denominator != 1 for value in values) or "FRACTION" in kinds:
        found.append("FRACTION")
    if any(value >= 1000 for value in values):
        found.append("LARGE")
    if any(20 < value < 1000 and value.denominator == 1 and value % 10 for value in values):
        found.append("COMPOUND")
    if "DATE" in roles or "ORDINAL" in kinds:
        found.append("DATE")
    if "MEASURE" in roles:
        found.append("MEASURE")
    if "TIME" in roles:
        found.append("TIME")
    if len(values) >= 4:
        found.append("MULTI")
    if Fraction(1) in values:
        found.append("ONE")
    if str(row.metadata.get("TC_STATUS") or "NONE") not in {"", "NONE"}:
        found.append("APPARATUS")
    return tuple(found) or ("PLAIN",)


def select_gold(rows: Mapping[object, object], *, per_class: int, seed: str,
                exclude: frozenset[str] = frozenset()) -> list[dict[str, object]]:
    """Pick up to ``per_class`` rows per hard class in a seeded, reproducible order.

    ``exclude`` holds coordinates of an earlier (development) selection, so a held-out set
    shares no verse with the cases any fix was derived from.
    """
    eligible = [(ref, row) for ref, row in rows.items()
                if row.ol_reference is not None and (row.ol_values or row.niv_values)
                and ref.label() not in exclude]
    eligible.sort(key=lambda pair: rank_label(pair[0].label(), seed))
    chosen: dict[str, dict[str, object]] = {}
    for name in CLASS_ORDER:
        taken = sum(1 for case in chosen.values() if name in case["classes"])
        for ref, row in eligible:
            if taken >= per_class:
                break
            classes = row_classes(row)
            if name in classes and ref.label() not in chosen:
                chosen[ref.label()] = {"reference": ref.label(), "classes": list(classes)}
                taken += 1
    return sorted(chosen.values(), key=lambda case: rank_label(case["reference"], seed))


def rank_label(label: str, seed: str) -> str:
    """Seeded order key for one coordinate label."""
    return _sha256(f"{seed}:{label}".encode("utf-8"))


# --- 2. production extraction over the selected verses ---------------------------------------

def _book_files(project_path: Path, book: str) -> list[Path]:
    """Return the Paratext SFM file(s) for one book of a project."""
    return sorted(path for path in project_path.iterdir()
                  if path.is_file() and path.suffix.upper() in {".SFM", ".USFM"} and book in path.stem[:6])


def build_inputs(config, project_id: str, policy: Mapping[str, object], bundle, selected: Sequence[str],
                 texts: Mapping[str, str] | None = None):
    """Project the WIP books holding the selected verses and keep only their units.

    ``texts`` replaces the USFM of a book (by book code), for text plants. Returns the inputs and
    the books that could not be projected, with the reason code.
    """
    from sage.numbers.execution import ExecutionInputs, package_root
    from sage.numbers.scope import project_scope
    from sage.numbers.style import validate_style_profile
    from sage.numbers.target import target_units
    from sage.references import parse_scope
    from sage.usj import compile_usfm_text
    from sage.versification_service import VersificationService
    import yaml

    from sage.errors import ValidationError

    wanted = set(selected)
    excluded: dict[str, str] = {}
    project = config.project(project_id)
    service = VersificationService(config)
    target_schema = service.project_schema(project_id)
    western_schema = service.base_schema("eng.vrs")
    mapping = package_root(config, bundle.package_id) / "reference/eng_org_map_rules.txt"
    documents: dict[str, Mapping[str, object]] = {}
    projected = []
    for book in sorted({label.split(" ", 1)[0] for label in wanted}):
        files = _book_files(Path(project.path), book)
        if not files:
            continue
        text = (texts or {}).get(book) or files[0].read_bytes().decode("utf-8-sig")
        usj = compile_usfm_text(text, files[0].name)
        digest = _sha256(_canonical(usj))
        documents[digest] = usj
        try:
            units, _refs = project_scope(target_units(usj, source_sha256=digest), scope=parse_scope(book),
                                         target_schema=target_schema, western_schema=western_schema,
                                         bundle=bundle, mapping_path=mapping)
        except ValidationError as exc:
            # A book a Run could not project either; report it instead of measuring around it.
            excluded[book] = exc.code
            continue
        projected.extend(unit for unit in units
                         if unit.target.target_references
                         and {ref.label() for ref in unit.western_references} & wanted)
    projected = tuple(projected)
    references = tuple(dict.fromkeys(ref for unit in projected for ref in unit.western_references))
    used = {unit.target.source_sha256 for unit in projected}
    contracts = {relative: (config.root / relative).read_bytes()
                 for relative in policy["phase_contracts"]["files"]}
    limits = yaml.safe_load((config.root / "system/config/workflows/nca/profile.yml").read_text())[
        "evidence_policies"]["default"]
    inputs = ExecutionInputs(bundle, validate_style_profile(None), policy, projected, (),
                             tuple(unit.target.unit_id for unit in projected), references,
                             {key: value for key, value in documents.items() if key in used}, "GOLD",
                             _canonical(policy), contracts, limits)
    return inputs, excluded


def gate_policy(config, bundle, route: Mapping[str, object], project_id: str, language: str,
                script: str) -> dict[str, object]:
    """Build the check policy a Run would seal, for verses chosen outside any Run scope."""
    from sage.numbers.policy import (CAPABILITY_LIMITATION_CODE, POLICY_SCHEMA_VERSION, _plain,
                                     phase_contract_manifest, validate_checks, validate_numeric_comparison_mode,
                                     validate_optimization_policy)
    from sage.numbers.reference import REFERENCE_PARSER_VERSION
    import yaml

    profile = yaml.safe_load((config.root / "system/config/workflows/nca/profile.yml").read_text(encoding="utf-8"))
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "checks": validate_checks({"number_accuracy": True, "footnote_review": True}),
        "wip": {"project_id": project_id, "language": language, "script": script},
        "reference_package": {"package_id": bundle.package_id, "sha256": bundle.sha256,
                              "parser_version": REFERENCE_PARSER_VERSION,
                              "qualification_status": bundle.qualification_status,
                              "diagnostics": _plain(bundle.diagnostics)},
        "number_style": {"selector": None, "sha256": None, "profile_id": None, "version": None,
                         "language": language, "script": script},
        "model_contract": {
            "skill_id": "nca-numbers",
            "skill_sha256": _sha256((config.root / "system/skills/nca-numbers/SKILL.md").read_bytes()),
            "prompt_task_contract_version": "nca-model-phases-1.0",
            "structured_response_schema_sha256": _sha256(
                (config.root / "system/config/schemas/nca-extraction.schema.yml").read_bytes()),
        },
        "model_route": dict(route),
        "optimization": validate_optimization_policy(profile.get("optimization_policy")),
        "numeric_comparison_mode": validate_numeric_comparison_mode(profile.get("default_numeric_comparison_mode")),
        "phase_contracts": phase_contract_manifest(config.root, route),
        "sqs_checks_applied": False,
        "capability_limitation_code": CAPABILITY_LIMITATION_CODE,
    }


def replay_tasks(route: Mapping[str, object]):
    """Model tasks that only replay sealed phases under a recorded route and never call a provider.

    Rescoring after a comparison change needs no model, so it must also work when the provider is
    unavailable (no credits, no route).
    """
    from types import MappingProxyType
    from sage.errors import ValidationError
    from sage.numbers.model_tasks import NcaModelTasks

    class ReplayModelTasks(NcaModelTasks):
        """Replay-only NCA model tasks pinned to one recorded route."""

        phase_resume_only = True

        def __init__(self) -> None:
            """Pin the recorded route and start with no physical attempts."""
            self._attempts = []

        @property
        def route_snapshot(self):
            """Return the recorded route the sealed phases were made with."""
            return MappingProxyType(dict(route))

        def _execute_physical(self, *args, **kwargs):
            """Refuse every provider call: replay must find a sealed phase or a recorded failure."""
            raise ValidationError("Offline replay never calls a provider", code="NCA_REPLAY_ONLY")

    return ReplayModelTasks()


PROBE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}}}


def provider_probe(tasks) -> str | None:
    """Send one tiny request on the route under test: the provider's error, or None when it answers.

    A provider that is signed in can still refuse every call (a workspace out of credits); only a
    real request shows it, and finding out halfway through a run leaves an INCOMPLETE receipt. This
    reads the task object's route and executor directly, because a public method on NcaModelTasks
    would change a sealed phase-contract module and void every sealed phase.
    """
    from sage.executors import ProviderRequest

    identity = tasks._route.identity
    request = ProviderRequest(prompt='Reply with {"ok": true}.', schema=PROBE_SCHEMA, model=identity.model_id,
                              reasoning_effort=None if identity.reasoning_id == "provider-default"
                              else identity.reasoning_id, timeout_seconds=120)
    execute = getattr(tasks._executor, "execute_prevalidated", None)
    try:
        if callable(execute):
            execute(request, tasks._provider_status)
        else:
            tasks._executor.execute(request)
    except Exception as exc:  # any refusal means the run would fail; report it, do not start
        return str(exc).strip() or type(exc).__name__
    return None


def provider_needed(step: str, work: Path, projects: Sequence[str], plants: int, replaying: bool) -> bool:
    """True when this invocation will call the route under test (a missing, non-replayed SUT result)."""
    if replaying:
        return False
    missing = [work / project / name for project in projects
               for name, steps in (("sut.json", {"sut", "all"}), ("plants-sut.json", {"plant", "all"}))
               if step in steps and (name == "sut.json" or plants > 0)]
    return any(not path.exists() for path in missing)


def run_sut(config, project_id: str, language: str, script: str, bundle, selected: Sequence[str],
            session: Path, replay_route: Mapping[str, object] | None = None,
            texts: Mapping[str, str] | None = None) -> dict[str, object]:
    """Run the production extraction route once (or replay it) and serialize every indexed group."""
    from sage.numbers.engine import evaluate_optimized_run
    from sage.numbers.model_tasks import NcaModelTasks
    from sage.numbers.replay import PhaseStore
    from sage.numbers.results import _group_document

    tasks = replay_tasks(replay_route) if replay_route is not None else NcaModelTasks(config)
    policy = gate_policy(config, bundle, tasks.route_snapshot, project_id, language, script)
    inputs, excluded = build_inputs(config, project_id, policy, bundle, selected, texts)
    session.mkdir(parents=True, exist_ok=True)
    fingerprint = _sha256(_canonical({"policy": policy, "units": list(inputs.expected_unit_ids)}))
    result = evaluate_optimized_run(inputs, model_tasks=tasks, run_id=f"gate-{project_id}",
                                    phase_store=PhaseStore(session, task_fingerprint=fingerprint))
    groups = [_group_document(group) for group in result.groups
              if group.comparison.outcome != "NOT_INDEXED"]
    return {"project_id": project_id, "language": language, "route": dict(tasks.route_snapshot),
            "comparison_mode": policy["numeric_comparison_mode"], "excluded_books": excluded,
            "groups": groups, "provider_calls": len(tasks.attempts)}


# --- 3. judges -------------------------------------------------------------------------------

EXTRACT_INSTRUCTIONS = """You build reference labels for a benchmark of an automatic number check of Bible translations.
For each verse (written in the language named in the input), list every number the counting convention below counts,
in reading order and keeping repeats. Give each value as an integer or an exact fraction "n/d", plus its kind.
Follow the convention exactly: it decides what counts, including what does NOT count.
Return an item for every input id, with empty lists when nothing counts.

"""

VERDICT_INSTRUCTIONS = """You audit a FAIL finding from an automatic number check of a Bible translation (the WIP).
Each case gives the WIP verse, the original-language verse, an English reference translation (BSB), the kind of FAIL,
the numbers the checker expected from the original language (counted by the convention below), and the numbers it
read from the WIP with what the checker took each one to count.

A FAIL is reserved for one thing: the WIP states a different quantity for the same thing than the original does (a
reader of the WIP learns a different number of people, a different date, a different size), or, for a
WRONG_ASSOCIATION FAIL, attaches the original's numbers to the wrong things. By product decision every other
difference is reported for review, not as a FAIL: a number left out, a number added from context, an implied
singular made explicit, a unit or time-of-day conversion (talents as coins, the ninth hour as three in the afternoon),
and the same quantities in another construction (a repeated number stated once, "the two" for "one ... the second",
"twelve times a year" for "twelve crops").

Give one cause per case:
- VALUE_CHANGED: the FAIL is right: the WIP states a different quantity, or attaches numbers to the wrong things.
- CHECKER_MISREAD: the checker missed a number in the WIP or read one with the wrong value.
- NOT_A_QUANTITY: the checker counted a number word that states no quantity here (an idiom such as "the next day"
  written with "second", a title or a name, "another", a pronoun).
- RESTRUCTURED: the WIP states the same quantities in another construction.
- REVIEW_CLASS: an omission, an addition from context, an implied singular made explicit, or a conversion.
- EXPECTED_WRONG: the expected numbers are not what the convention counts in the original.

Give a short reason in English. Do not quote more than three words of any text.

"""

FAIL_CAUSES = ("VALUE_CHANGED", "CHECKER_MISREAD", "NOT_A_QUANTITY", "RESTRUCTURED", "REVIEW_CLASS",
               "EXPECTED_WRONG")

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "values", "kinds"],
        "properties": {"id": {"type": "string"}, "values": {"type": "array", "items": {"type": "string"}},
                       "kinds": {"type": "array", "items": {"type": "string"}}}}}},
}

VERDICT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "cause", "reason"],
        "properties": {"id": {"type": "string"}, "cause": {"enum": list(FAIL_CAUSES)},
                       "reason": {"type": "string"}}}}},
}


def claude_judge(model: str) -> Callable[[str, str, Mapping[str, object]], Mapping[str, object]]:
    """Return a judge that calls one Claude model through the claude CLI, tools disabled."""
    def call(system: str, prompt: str, schema: Mapping[str, object]) -> Mapping[str, object]:
        """Run one judge prompt and return its structured output and cost."""
        command = ["claude", "-p", prompt, "--model", model, "--system-prompt", system, "--tools", "",
                   "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
                   "--output-format", "json", "--json-schema", json.dumps(schema)]
        with tempfile.TemporaryDirectory() as empty:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=900, cwd=empty)
        if completed.returncode != 0:
            raise RuntimeError(f"judge {model} failed: {completed.stderr[-500:] or completed.stdout[-500:]}")
        document = json.loads(completed.stdout)
        output = document.get("structured_output")
        if not isinstance(output, Mapping):
            raise RuntimeError(f"judge {model} returned no structured output")
        return {"output": output, "cost_usd": document.get("total_cost_usd")}
    return call


def _cached_call(cache: Path, judge_id: str, judge, system: str, prompt: str,
                 schema: Mapping[str, object]) -> Mapping[str, object]:
    """Call a judge once per exact (judge, system, prompt) and keep the response locally."""
    key = _sha256(_canonical({"judge": judge_id, "system": system, "prompt": prompt, "schema": schema}))
    path = cache / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    response = judge(system, prompt, schema)
    _write_json(path, {"judge": judge_id, **response})
    return response


def _batches(items: Sequence[Mapping[str, object]], size: int = JUDGE_BATCH) -> Iterable[list[Mapping[str, object]]]:
    """Split judge cases into fixed-size batches in stable order."""
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


def judge_cases(groups: Sequence[Mapping[str, object]], language: str, judges: Mapping[str, object],
                cache: Path, bundle) -> dict[str, object]:
    """Collect both judges' value labels for every group and verdicts for every FAIL."""
    convention = CONVENTION.read_text(encoding="utf-8")
    verses = [{"id": f"c{index}", "text": group["evidence"]["wip_text"]} for index, group in enumerate(groups)]
    fails = []
    for index, group in enumerate(groups):
        if group["comparison"]["outcome"] != "FAIL":
            continue
        refs = [_verse(label) for label in group["western_references"]]
        rows = [bundle.lookup(ref) for ref in refs if bundle.lookup(ref) is not None]
        extraction = group["extraction"]
        fails.append({"id": f"c{index}", "wip_text": group["evidence"]["wip_text"],
                      "original_text": " ".join(row.ol_text for row in rows),
                      "bsb_text": " ".join(row.bsb_text for row in rows),
                      "fail_kind": (group["comparison"]["review_context"] or {}).get("kind") or "VALUE_DIFFERENCE",
                      "expected_values": group["comparison"]["expected_values"],
                      "wip_values_read_by_checker": [
                          {"value": value, "counts": counts}
                          for value, counts in zip(extraction["values"], extraction["counts_en"])]})
    jobs = []
    for judge_id, judge in judges.items():
        for batch in _batches(verses):
            jobs.append(("values", judge_id, judge, EXTRACT_INSTRUCTIONS + convention,
                         json.dumps({"language": language, "verses": batch}, ensure_ascii=False), EXTRACT_SCHEMA))
        # One FAIL per call: a verdict must not change with the other FAILs of a rescore.
        for batch in _batches(fails, 1):
            jobs.append(("verdicts", judge_id, judge, VERDICT_INSTRUCTIONS + convention,
                         json.dumps({"wip_language": language, "cases": batch}, ensure_ascii=False), VERDICT_SCHEMA))
    return _ask(jobs, cache, ("values", "verdicts"))


def _ask(jobs: Sequence[tuple], cache: Path, kinds: Sequence[str]) -> dict[str, dict[str, dict[str, object]]]:
    """Run (kind, judge_id, judge, system, prompt, schema) jobs and key every item by kind, id, judge."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda job: (job[0], job[1], _cached_call(cache, job[1], *job[2:])), jobs))
    labels: dict[str, dict[str, dict[str, object]]] = {kind: {} for kind in kinds}
    for kind, judge_id, response in responses:
        for item in response["output"].get("items", []):
            labels[kind].setdefault(str(item.get("id")), {})[judge_id] = dict(item)
    return labels


def _verse(label: str):
    """Parse one "BOOK C:V" coordinate label."""
    from sage.vrs import VerseRef
    book, coordinate = label.split(" ", 1)
    chapter, verse = coordinate.split(":", 1)
    return VerseRef(book, int(chapter), int(verse))


# --- 4. deterministic gate metrics -----------------------------------------------------------

def consensus_values(by_judge: Mapping[str, Mapping[str, object]], judge_ids: Sequence[str]) -> list[Fraction] | None:
    """Return the gold value list when every judge returned the same values (as a multiset)."""
    lists = []
    for judge_id in judge_ids:
        item = by_judge.get(judge_id)
        if item is None:
            return None
        values = [_fraction(value) for value in item.get("values", [])]
        if any(value is None for value in values):
            return None
        lists.append(values)
    if not lists or any(Counter(values) != Counter(lists[0]) for values in lists[1:]):
        return None
    return lists[0]


def judge_verdict(item: Mapping[str, object] | None) -> str:
    """One judge's GENUINE/FALSE_ALARM, from its cause (or the verdict of a 1.0 label file)."""
    item = item or {}
    if item.get("cause") in FAIL_CAUSES:
        return "GENUINE" if item["cause"] == "VALUE_CHANGED" else "FALSE_ALARM"
    return str(item.get("verdict") or "MISSING")


def verdict(by_judge: Mapping[str, Mapping[str, object]], judge_ids: Sequence[str]) -> str:
    """GENUINE or FALSE_ALARM when the judges agree, SPLIT otherwise."""
    found = {judge_verdict(by_judge.get(judge_id)) for judge_id in judge_ids}
    return found.pop() if len(found) == 1 and found <= {"GENUINE", "FALSE_ALARM"} else "SPLIT"


def fail_cause(by_judge: Mapping[str, Mapping[str, object]], judge_ids: Sequence[str]) -> str:
    """The cause every judge gave, MIXED when they differ, or UNKNOWN for a 1.0 label file."""
    found = {str((by_judge.get(judge_id) or {}).get("cause") or "UNKNOWN") for judge_id in judge_ids}
    return found.pop() if len(found) == 1 else "MIXED"


def fail_reading(gold: Sequence[Fraction] | None, extracted: Sequence[Fraction], complete: bool) -> str:
    """Whether a FAIL rests on a correct reading of the WIP, by code from the gold values.

    READ_CORRECTLY: the checker read what the judges read, so the comparison, the convention or the
    index made the call. MISREAD: extraction differs from gold. DISPUTED: no gold values.
    """
    if gold is None:
        return "DISPUTED"
    return "READ_CORRECTLY" if complete and Counter(extracted) == Counter(gold) else "MISREAD"


def planted_rows(rows: Sequence[object]) -> list[object] | None:
    """Change the last expected value of a group by one, in both authority layers, or None."""
    for position in range(len(rows) - 1, -1, -1):
        row = rows[position]
        if row.ol_values:
            values = list(row.ol_values)
            values[-1] = values[-1] + 1
            items = [dict(item) for item in row.ol_items]
            for item in reversed(items):  # the item that carried the changed value keeps its unit and referent
                if Fraction(item["VALUE"]) == row.ol_values[-1]:
                    item["VALUE"] = str(values[-1])
                    break
            changed = replace(row, ol_values=tuple(values), niv_values=tuple(values),
                              ol_normalizations=(), ol_items=tuple(items), niv_items=())
            return [*rows[:position], changed, *rows[position + 1:]]
    return None


def plantable_rows(group: Mapping[str, object], bundle) -> list[object] | None:
    """The index rows of a group, or None when they only ever review (provisional or apparatus)."""
    rows = [bundle.lookup(_verse(label)) for label in group["western_references"]]
    rows = [row for row in rows if row is not None]
    if (not rows or any(row.metadata.get("OL_REVIEW_STATUS") == "PROVISIONAL"
                        or str(row.metadata.get("TC_STATUS") or "NONE") not in {"", "NONE"} for row in rows)):
        return None
    return rows


def planted_outcome(group: Mapping[str, object], bundle, mode: str) -> str | None:
    """Compare one PASS group's real extraction against its index with one value changed."""
    from sage.numbers.compare import compare_group

    rows = plantable_rows(group, bundle)
    if rows is None:
        return None
    changed = planted_rows(rows)
    if changed is None:
        return None
    extraction = group["extraction"]
    return compare_group(tuple(Fraction(value) for value in extraction["values"]), changed, mode=mode,
                         wip_kinds=tuple(extraction["kinds"]), wip_counts_en=tuple(extraction["counts_en"]),
                         wip_issues=tuple(extraction["issues"])).outcome


def wilson_interval(numerator: int, denominator: int) -> tuple[float, float] | None:
    """Wilson score 95% interval of one proportion, or None without evidence."""
    if denominator == 0:
        return None
    p, z2 = numerator / denominator, WILSON_Z ** 2
    centre = (p + z2 / (2 * denominator)) / (1 + z2 / denominator)
    spread = (WILSON_Z / (1 + z2 / denominator)) * (p * (1 - p) / denominator + z2 / (4 * denominator ** 2)) ** 0.5
    return max(0.0, centre - spread), min(1.0, centre + spread)


def _ratio(numerator: int, denominator: int) -> dict[str, object]:
    """Express one measured ratio exactly, as a rounded percentage and with its 95% interval."""
    interval = wilson_interval(numerator, denominator)
    return {"numerator": numerator, "denominator": denominator,
            "percent": None if denominator == 0 else round(100 * numerator / denominator, 1),
            "wilson95_percent": None if interval is None else [round(100 * bound, 1) for bound in interval]}


def language_metrics(sut: Mapping[str, object], labels: Mapping[str, object], judge_ids: Sequence[str],
                     bundle, mode: str, classes: Mapping[str, Sequence[str]],
                     plants: Mapping[str, object] | None = None,
                     plants_sut: Mapping[str, object] | None = None) -> dict[str, object]:
    """Score one WIP's extraction, FAILs and planted errors against the LLM-built labels."""
    cases, provider_failed = [], []
    for index, group in enumerate(sut["groups"]):
        case_id = f"c{index}"
        if any(PROVIDER_FAILURE in item for item in group["extraction"]["limitations"]):
            # The model never answered: not an extraction error, and not evidence either way.
            provider_failed.extend(group["western_references"])
            continue
        gold = consensus_values(labels["values"].get(case_id, {}), judge_ids)
        extracted = [Fraction(value) for value in group["extraction"]["values"]]
        complete = group["extraction"]["status"] == "COMPLETE"
        outcome = group["comparison"]["outcome"]
        case = {
            "western_references": group["western_references"],
            "classes": sorted({name for label in group["western_references"] for name in classes.get(label, ())}),
            "outcome": outcome, "review_kind": (group["comparison"]["review_context"] or {}).get("kind"),
            "expected_values": group["comparison"]["expected_values"],
            "extracted_values": group["extraction"]["values"],
            "gold_values": None if gold is None else [str(value) for value in gold],
            "extraction_correct": None if gold is None else (complete and Counter(extracted) == Counter(gold)),
        }
        if outcome == "FAIL":
            by_judge = labels["verdicts"].get(case_id, {})
            case["fail_verdict"] = verdict(by_judge, judge_ids)
            case["fail_verdicts_by_judge"] = {judge_id: judge_verdict(by_judge.get(judge_id))
                                              for judge_id in judge_ids}
            case["fail_cause"] = fail_cause(by_judge, judge_ids)
            case["fail_causes_by_judge"] = {judge_id: (by_judge.get(judge_id) or {}).get("cause")
                                            for judge_id in judge_ids}
            case["fail_reading"] = fail_reading(gold, extracted, complete)
        if outcome == "PASS" and case["extraction_correct"]:
            case["planted_outcome"] = planted_outcome(group, bundle, mode)
        cases.append(case)
    fails = [case for case in cases if case["outcome"] == "FAIL"]
    false_fails = [case for case in fails if case["fail_verdict"] != "GENUINE"]
    assessed = sum(1 for case in cases if case["outcome"] != "NOT_ASSESSED")
    labelled = [case for case in cases if case["extraction_correct"] is not None]
    planted = [case for case in cases if case.get("planted_outcome") is not None]
    per_class = {}
    for name in CLASS_ORDER:
        members = [case for case in labelled if name in case["classes"]]
        per_class[name] = _ratio(sum(1 for case in members if case["extraction_correct"]), len(members))
    text_plants = plant_metrics(plants, plants_sut) if plants is not None and plants_sut is not None else {}
    return {
        **text_plants,
        "project_id": sut["project_id"], "language": sut["language"],
        "excluded_books": sut.get("excluded_books", {}), "indexed_groups": len(cases),
        "provider_failed": provider_failed + list(text_plants.get("text_plant_provider_failed", [])),
        "outcomes": dict(sorted(Counter(case["outcome"] for case in cases).items())),
        "fail_precision": _ratio(sum(1 for case in fails if case["fail_verdict"] == "GENUINE"), len(fails)),
        "fail_verdicts": dict(sorted(Counter(case["fail_verdict"] for case in fails).items())),
        "false_fail_rate": _ratio(len(false_fails), assessed),
        "genuine_fail_rate": _ratio(len(fails) - len(false_fails), assessed),
        "false_fails_by_cause": dict(sorted(Counter(case["fail_cause"] for case in false_fails).items())),
        "false_fails_by_reading": dict(sorted(Counter(case["fail_reading"] for case in false_fails).items())),
        "extraction_recall": _ratio(sum(1 for case in labelled if case["extraction_correct"]), len(labelled)),
        "gold_disputed": len(cases) - len(labelled),
        "extraction_recall_by_class": per_class,
        "planted_detection": _ratio(sum(1 for case in planted if case["planted_outcome"] == "FAIL"), len(planted)),
        "cases": cases,
    }


def check_ratio(ratio: Mapping[str, int], minimum: Fraction, min_evidence: int) -> str:
    """PASS on enough evidence at or above the bar, FAIL when the whole 95% interval is below it.

    Anything in between, including no evidence at all, is INSUFFICIENT_EVIDENCE.
    """
    numerator, denominator = ratio["numerator"], ratio["denominator"]
    if denominator == 0:
        return "INSUFFICIENT_EVIDENCE"
    if wilson_interval(numerator, denominator)[1] < minimum:
        return "FAIL"
    if denominator >= min_evidence and Fraction(numerator, denominator) >= minimum:
        return "PASS"
    return "INSUFFICIENT_EVIDENCE"


def check_rate(ratio: Mapping[str, int], maximum: Fraction, min_evidence: int) -> str:
    """The mirror of check_ratio for a rate that must stay at or below its bar."""
    flipped = {"numerator": ratio["denominator"] - ratio["numerator"], "denominator": ratio["denominator"]}
    return check_ratio(flipped, 1 - maximum, min_evidence)


def gate_status(languages: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Pool every WIP's counts and apply the release thresholds."""
    def pooled(name: str) -> dict[str, object]:
        """Sum one ratio across every WIP; a WIP that did not measure it adds nothing."""
        empty = {"numerator": 0, "denominator": 0}
        return _ratio(sum(item.get(name, empty)["numerator"] for item in languages),
                      sum(item.get(name, empty)["denominator"] for item in languages))

    maximums = {"false_fail_rate": FALSE_FAIL_RATE_MAX}
    minimums = {"extraction_recall": EXTRACTION_RECALL_MIN, "planted_detection": PLANTED_DETECTION_MIN,
                "text_plant_detection": TEXT_PLANT_DETECTION_MIN}
    totals = {name: pooled(name) for name in (*maximums, *minimums, "fail_precision", "genuine_fail_rate")}
    checks = {name: check_rate(totals[name], maximum, MIN_EVIDENCE[name]) for name, maximum in maximums.items()}
    checks.update({name: check_ratio(totals[name], minimum, MIN_EVIDENCE[name])
                   for name, minimum in minimums.items()})
    checks["two_languages"] = "PASS" if len({item["language"] for item in languages}) >= 2 else "FAIL"
    incomplete = any(item.get("provider_failed") for item in languages)
    found = set(checks.values())
    status = ("INCOMPLETE" if incomplete else "FAIL" if "FAIL" in found
              else "INSUFFICIENT_EVIDENCE" if "INSUFFICIENT_EVIDENCE" in found else "PASS")
    return {"totals": totals, "checks": checks, "status": status,
            "thresholds": {**{name: f"<= {maximum}" for name, maximum in maximums.items()},
                           **{name: f">= {minimum}" for name, minimum in minimums.items()}},
            "min_evidence": dict(MIN_EVIDENCE)}


# --- 5. text plants: end-to-end planted errors in real WIP text ------------------------------

PLANT_INSTRUCTIONS = """You build test cases for a benchmark of an automatic number check of Bible translations.
For each verse (written in the language named in the input), change the number at the given position of its listed
values (counted in reading order by the convention below) from its value to the new value. Edit as few words as
possible, keep the grammar correct (agreement, case, word order) and the style of the verse, and change nothing else.
Write the new number the way the verse writes the old one (in words or in digits).
Return "old": the shortest exact substring of the verse that contains the whole change, copied character for
character, and "new": its replacement.

"""

PLANT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "old", "new"],
        "properties": {"id": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}}}},
}


def unit_key(group: Mapping[str, object]) -> str:
    """BOOK:chapter:number of a group's verse, independent of the book text's hash."""
    return str(group["unit_id"]).split(":", 1)[1]


def plant_candidates(groups: Sequence[Mapping[str, object]], labels: Mapping[str, object], judge_ids: Sequence[str],
                     bundle, *, seed: str, limit: int) -> list[dict[str, object]]:
    """Seeded choice of PASS verses read exactly as the judges read them, with one value to raise by one.

    Only whole-number gold values on rows that can FAIL are used, so the planted verse must FAIL.
    """
    found = []
    for index, group in enumerate(groups):
        if group["comparison"]["outcome"] != "PASS" or group["extraction"]["status"] != "COMPLETE":
            continue
        gold = consensus_values(labels["values"].get(f"c{index}", {}), judge_ids)
        extracted = [Fraction(value) for value in group["extraction"]["values"]]
        if (not gold or any(value.denominator != 1 for value in gold) or Counter(extracted) != Counter(gold)
                or plantable_rows(group, bundle) is None):
            continue
        key = unit_key(group)
        position = int(rank_label(key, f"{seed}:plant"), 16) % len(gold)
        planned = list(gold)
        planned[position] += 1
        found.append({"id": f"p{index}", "key": key, "western_references": group["western_references"],
                      "text": group["evidence"]["wip_text"], "values": [str(value) for value in gold],
                      "position": position + 1, "from": str(gold[position]), "to": str(planned[position]),
                      "planned_values": [str(value) for value in planned]})
    found.sort(key=lambda plant: rank_label(plant["key"], f"{seed}:plant"))
    return found[:limit]


def make_plants(candidates: Sequence[Mapping[str, object]], language: str, judges: Mapping[str, object],
                cache: Path) -> list[dict[str, object]]:
    """Have the first judge write each plant and keep it only when every judge counts the planned values."""
    convention = CONVENTION.read_text(encoding="utf-8")
    judge_ids = list(judges)
    planter = judge_ids[0]
    requests = [{"id": plant["id"], "text": plant["text"], "values": plant["values"],
                 "change": {"position": plant["position"], "from": plant["from"], "to": plant["to"]}}
                for plant in candidates]
    edits = _ask([("plants", planter, judges[planter], PLANT_INSTRUCTIONS + convention,
                   json.dumps({"language": language, "verses": batch}, ensure_ascii=False), PLANT_SCHEMA)
                  for batch in _batches(requests)], cache, ("plants",))["plants"]
    plants = []
    for plant in candidates:
        edit = edits.get(plant["id"], {}).get(planter) or {}
        old, new = str(edit.get("old") or ""), str(edit.get("new") or "")
        usable = bool(old) and old != new and plant["text"].count(old) == 1
        plants.append({**plant, "old": old, "new": new, "usable_edit": usable,
                       "planted_text": plant["text"].replace(old, new, 1) if usable else None})
    usable = [{"id": plant["id"], "text": plant["planted_text"]} for plant in plants if plant["usable_edit"]]
    counted = _ask([("values", judge_id, judge, EXTRACT_INSTRUCTIONS + convention,
                     json.dumps({"language": language, "verses": batch}, ensure_ascii=False), EXTRACT_SCHEMA)
                    for judge_id, judge in judges.items() for batch in _batches(usable)], cache, ("values",))["values"]
    for plant in plants:
        values = consensus_values(counted.get(plant["id"], {}), judge_ids) if plant["usable_edit"] else None
        plant["verified"] = (values is not None
                             and Counter(values) == Counter(Fraction(value) for value in plant["planned_values"]))
    return plants


def _verse_span(text: str, chapter: str, number: str) -> tuple[int, int] | None:
    """Character span of one verse's USFM after its \\v marker, up to the next verse or chapter."""
    import re
    chapter_at = re.search(rf"\\c\s+{re.escape(chapter)}(?!\d)", text)
    if chapter_at is None:
        return None
    verse = re.compile(rf"\\v\s+{re.escape(number)}(?=\s)").search(text, chapter_at.end())
    next_chapter = re.compile(r"\\c\s").search(text, chapter_at.end())
    if verse is None or (next_chapter is not None and next_chapter.start() < verse.start()):
        return None
    following = re.compile(r"\\[cv]\s").search(text, verse.end())
    return verse.end(), following.start() if following else len(text)


def plant_book_text(text: str, name: str, edits: Mapping[str, tuple[str, str]]) -> tuple[str, list[str]]:
    """Apply (old, new) edits keyed BOOK:chapter:number inside their verses of one USFM book.

    An edit is kept only when recompiling changes that verse's text exactly as planned and no
    other verse; otherwise it is left out. Returns the new text and the keys applied.
    """
    from sage.numbers.target import target_units
    from sage.usj import compile_usfm_text

    def verses(source: str) -> dict[str, str]:
        """Compiled main text per verse key."""
        usj = compile_usfm_text(source, name)
        return {unit.unit_id.split(":", 1)[1]: unit.main_text
                for unit in target_units(usj, source_sha256=_sha256(_canonical(usj)))}

    before, applied = verses(text), []
    for key, (old, new) in sorted(edits.items()):
        _book, chapter, number = key.split(":", 2)
        span = _verse_span(text, chapter, number)
        if (not old or old == new or before.get(key, "").count(old) != 1 or span is None
                or text[span[0]:span[1]].count(old) != 1):
            continue
        at = text.index(old, span[0], span[1])
        candidate = text[:at] + new + text[at + len(old):]
        after = verses(candidate)
        if after == {**before, key: before[key].replace(old, new, 1)}:
            text, before = candidate, after
            applied.append(key)
    return text, applied


def plant_metrics(plants: Mapping[str, object], plants_sut: Mapping[str, object]) -> dict[str, object]:
    """Score the production route on planted verses: each must FAIL."""
    groups = {unit_key(group): group for group in plants_sut["groups"]}
    applied = set(plants_sut.get("applied", ()))
    cases, provider_failed = [], []
    for plant in plants["plants"]:
        group = groups.get(plant["key"]) if plant["key"] in applied else None
        if group is None:
            continue
        if any(PROVIDER_FAILURE in item for item in group["extraction"]["limitations"]):
            provider_failed.extend(group["western_references"])
            continue
        extracted = Counter(Fraction(value) for value in group["extraction"]["values"])
        cases.append({"western_references": group["western_references"], "from": plant["from"], "to": plant["to"],
                      "outcome": group["comparison"]["outcome"],
                      "review_kind": (group["comparison"]["review_context"] or {}).get("kind"),
                      "read_exactly": extracted == Counter(Fraction(value) for value in plant["planned_values"])})
    return {
        "text_plant_detection": _ratio(sum(1 for case in cases if case["outcome"] == "FAIL"), len(cases)),
        "text_plants": {"candidates": len(plants["plants"]),
                        "verified": sum(1 for plant in plants["plants"] if plant["verified"]),
                        "applied": len(applied), "measured": len(cases),
                        "outcomes": dict(sorted(Counter(case["outcome"] for case in cases).items())),
                        "read_exactly": _ratio(sum(1 for case in cases if case["read_exactly"]), len(cases))},
        "text_plant_cases": cases,
        "text_plant_provider_failed": provider_failed,
    }


def run_plants(config, project: str, language: str, script: str, bundle, plants: Sequence[Mapping[str, object]],
               session: Path, replay_route: Mapping[str, object] | None) -> dict[str, object]:
    """Apply the verified plants to the WIP's books and run the production route on those verses."""
    root = Path(config.project(project).path)
    by_book: dict[str, dict[str, tuple[str, str]]] = {}
    for plant in plants:
        if plant["verified"]:
            by_book.setdefault(plant["key"].split(":", 1)[0], {})[plant["key"]] = (plant["old"], plant["new"])
    texts, applied = {}, []
    for book, edits in sorted(by_book.items()):
        files = _book_files(root, book)
        if not files:
            continue
        texts[book], keys = plant_book_text(files[0].read_bytes().decode("utf-8-sig"), files[0].name, edits)
        applied.extend(keys)
    selected = sorted({label for plant in plants if plant["key"] in applied for label in plant["western_references"]})
    result = (run_sut(config, project, language, script, bundle, selected, session, replay_route=replay_route,
                      texts=texts) if selected else {"groups": []})
    return {**result, "applied": applied}


# --- orchestration ---------------------------------------------------------------------------

def _code_identity() -> str:
    """Hash the NCA implementation, Skill, workflow configuration and this tool."""
    paths = sorted(set(list((APP_ROOT / "system/src/sage/numbers").rglob("*.py"))
                       + list((APP_ROOT / "system/skills/nca-numbers").rglob("*.md"))
                       + list((APP_ROOT / "system/config/workflows/nca").rglob("*.yml"))
                       + [Path(__file__).resolve()]))
    return _sha256(b"".join(path.relative_to(APP_ROOT).as_posix().encode("utf-8") + b"\0"
                            + _sha256(path.read_bytes()).encode("ascii") + b"\n" for path in paths))


def _wip(spec: str) -> tuple[str, Path, str, str]:
    """Parse PROJECT=SETTINGS:LANGUAGE:SCRIPT."""
    project, rest = spec.split("=", 1)
    settings, language, script = rest.rsplit(":", 2)
    return project, Path(settings), language, script


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected gate steps; every step reuses cached evidence from earlier steps."""
    from sage.numbers.resources import resolve_reference_package
    from sage.registry import load_ecosystem

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package", required=True)
    parser.add_argument("--wip", action="append", required=True, help="PROJECT=SETTINGS:LANGUAGE:SCRIPT (repeat)")
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--per-class", type=int, default=20)
    parser.add_argument("--seed", default="nca-gate-1")
    parser.add_argument("--exclude", type=Path, action="append", default=[],
                        help="an earlier selection.json whose coordinates the new selection must avoid")
    parser.add_argument("--judge", action="append", default=None, help="Claude model id (repeat; default opus+sonnet)")
    parser.add_argument("--replay-route", type=Path,
                        help="an earlier receipt.json: rescore from sealed phases under its route, with no provider calls")
    parser.add_argument("--plants", type=int, default=50, help="text plants per WIP (0 skips the plant step)")
    parser.add_argument("--step", choices=("select", "sut", "judge", "plant", "gate", "all"), default="all")
    args = parser.parse_args(argv)
    judge_ids = args.judge or ["claude-opus-5-5", "claude-sonnet-5-5"]
    replay_route = (json.loads(args.replay_route.read_text(encoding="utf-8"))["route"]
                    if args.replay_route else None)
    wips = [_wip(spec) for spec in args.wip]
    work = args.work.expanduser().resolve()
    config0 = load_ecosystem(wips[0][1])
    bundle = resolve_reference_package(config0, args.package)
    if provider_needed(args.step, work, [wip[0] for wip in wips], args.plants, replay_route is not None):
        from sage.numbers.model_tasks import NcaModelTasks
        refused = provider_probe(NcaModelTasks(config0))
        if refused:
            print(f"NCA route under test is not answering; nothing was run: {refused}", file=sys.stderr)
            return 2

    selection_path = work / "selection.json"
    excluded = frozenset(case["reference"] for path in args.exclude
                         for case in json.loads(path.read_text(encoding="utf-8"))["cases"])
    if args.step in {"select", "all"} and not selection_path.exists():
        _write_json(selection_path, {"package_id": bundle.package_id, "package_sha256": bundle.sha256,
                                     "seed": args.seed, "per_class": args.per_class,
                                     "excluded_selections": [_sha256(path.read_bytes()) for path in args.exclude],
                                     "cases": select_gold(bundle.rows, per_class=args.per_class, seed=args.seed,
                                                          exclude=excluded)})
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection["package_sha256"] != bundle.sha256:
        raise SystemExit("selection was made for a different package")
    selected = [case["reference"] for case in selection["cases"]]
    classes = {case["reference"]: case["classes"] for case in selection["cases"]}

    languages = []
    for project, settings, language, script in wips:
        config = load_ecosystem(settings)
        sut_path = work / project / "sut.json"
        if args.step in {"sut", "all"} and not sut_path.exists():
            _write_json(sut_path, run_sut(config, project, language, script, bundle, selected,
                                          work / project / "phases", replay_route=replay_route))
        if args.step == "select" or not sut_path.exists():
            continue
        sut = json.loads(sut_path.read_text(encoding="utf-8"))
        labels_path = work / project / "labels.json"
        judges = {judge_id: claude_judge(judge_id) for judge_id in judge_ids}
        if args.step in {"judge", "all"}:
            _write_json(labels_path, judge_cases(sut["groups"], language, judges, work / "judge-cache", bundle))
        if not labels_path.exists():
            continue
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        plants_path, plants_sut_path = work / project / "plants.json", work / project / "plants-sut.json"
        if args.step in {"plant", "all"} and args.plants > 0 and not plants_path.exists():
            candidates = plant_candidates(sut["groups"], labels, judge_ids, bundle,
                                          seed=selection["seed"], limit=args.plants)
            _write_json(plants_path, {"seed": selection["seed"], "planter": judge_ids[0],
                                      "plants": make_plants(candidates, language, judges, work / "judge-cache")})
        if args.step in {"plant", "all"} and plants_path.exists() and not plants_sut_path.exists():
            plants = json.loads(plants_path.read_text(encoding="utf-8"))["plants"]
            _write_json(plants_sut_path, run_plants(config, project, language, script, bundle, plants,
                                                    work / project / "plants-phases", replay_route))
        planted = [json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
                   for path in (plants_path, plants_sut_path)]
        languages.append((sut, labels, *planted))

    if args.step not in {"gate", "all"} or len(languages) != len(wips):
        return 0
    mode = languages[0][0]["comparison_mode"]
    measured = [language_metrics(sut, labels, judge_ids, bundle, mode, classes, plants, plants_sut)
                for sut, labels, plants, plants_sut in languages]
    receipt = {
        "schema_version": GATE_SCHEMA, "gate": "NCA_RELEASE_GATE",
        "recorded_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "package": {"package_id": bundle.package_id, "sha256": bundle.sha256,
                    "qualification_status": bundle.qualification_status},
        "route": languages[0][0]["route"], "comparison_mode": mode,
        "judges": judge_ids,
        "judge_rule": ("gold values only where all judges agree; FAIL is GENUINE only when every judge gives "
                       "cause VALUE_CHANGED (only a changed quantity is a FAIL; other differences are review)"),
        "selection": {"seed": selection["seed"], "per_class": selection["per_class"],
                      "excluded_selections": selection.get("excluded_selections", []),
                      "coordinates": len(selected), "sha256": _sha256(_canonical(selection["cases"]))},
        "text_plants": {"per_wip": args.plants, "planter": judge_ids[0],
                        "rule": "one counted value raised by one; kept only when every judge counts the planned values "
                                "and recompiling changes that verse alone"},
        "code_sha256": _code_identity(),
        **gate_status(measured),
        "languages": measured,
        "sqs_status": "NOT_APPLIED",
        "limits": ("Measured on the selected coordinates and WIPs only. Labels are LLM-built (no hand labelling); "
                   "judge agreement is not proof of correctness. WIP text is kept out of this receipt."),
    }
    _write_json(work / "receipt.json", receipt)
    if args.receipt:
        _write_json(args.receipt.expanduser().resolve(), receipt)
    print(json.dumps({key: receipt[key] for key in ("status", "checks", "totals")}, indent=2))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
