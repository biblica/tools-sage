"""A PCC Job's pin of one reference-list version, and explicit re-pinning (plan D16, P5b-3).

A Job pins ``{rl_id, version, sha256}`` in its defaults; ``sha256`` is the SHA-256 of the package's
``CHECKSUMS.sha256``, so any change to a stored package is caught when a Run seals or executes (integrity:
``PCC_RL_CHANGED``). Re-pinning is an explicit Operator action. Glossary rules are keyed by group, and a group
is concept + sense (D13), so rules carry over to the new version wherever their concept and sense still
exist. A rule whose group is gone is marked ``STALE`` in the journal (never deleted, never accepting), and
the re-pin writes a carry-over report.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_text
from ..errors import ValidationError
from .glossary import _append_rule, current_rules
from .ids import group_id
from .reflist import CHECKSUMS, ReferenceListStore, load_entries, verify_reference_list

LIVE_RULE_STATES = ("PROPOSED", "APPROVED")


def package_sha256(folder: Path) -> str:
    """The pin hash of one package: SHA-256 of its checksum list."""
    return hashlib.sha256((Path(folder) / CHECKSUMS).read_bytes()).hexdigest()


def pin_for(store: ReferenceListStore, rl_id: str, version: int | None = None) -> dict[str, Any]:
    """A pin record for a stored version (the newest when ``version`` is None)."""
    versions = store.versions(rl_id)
    if not versions or (version is not None and version not in versions):
        raise ValidationError(f"No reference list {rl_id} version {version or 'any'}", code="PCC_RL_MISSING",
                              next_action="Choose a reference list from the list SAGE shows, or build one.")
    chosen = version or versions[-1]
    folder = store.path(rl_id, chosen)
    verify_reference_list(folder)
    return {"rl_id": rl_id, "version": chosen, "sha256": package_sha256(folder)}


def resolve_pin(store: ReferenceListStore, pin: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Manifest and entries of a pinned version; integrity errors when it is missing or changed."""
    folder = store.path(pin["rl_id"], int(pin["version"]))
    if not (folder / CHECKSUMS).is_file():
        raise ValidationError(
            f"The pinned reference list {pin['rl_id']} version {pin['version']} is not in this SAGE instance",
            code="PCC_RL_MISSING",
            next_action="Import the reference list package again, or pin another version for this Job.")
    if package_sha256(folder) != pin["sha256"]:
        raise ValidationError(
            f"The pinned reference list {pin['rl_id']} version {pin['version']} changed on disk",
            code="PCC_RL_CHANGED",
            next_action="Restore the package, or re-pin the Job so the change is reviewed explicitly.")
    return verify_reference_list(folder), load_entries(folder)


def live_group_ids(entries: Iterable[Mapping[str, Any]]) -> set[str]:
    """Group ids (concept + sense) that rules may attach to: every recurring sense of a kept entry."""
    return {group_id(e["concept_key"], s["sense_key"]) for e in entries if e["status"] != "DROPPED"
            for s in e["senses"] if s["kind"] == "SENSE"}


@dataclass
class RepinReport:
    """What a re-pin carried over and what it made stale."""

    old: dict[str, Any] | None
    new: dict[str, Any]
    added: int = 0
    dropped: int = 0
    changed: int = 0
    unchanged: int = 0
    rules_carried: int = 0
    rules_stale: list[str] = field(default_factory=list)
    report_path: Path | None = None

    def lines(self) -> list[str]:
        """Operator-readable summary."""
        old = f"{self.old['rl_id']} v{self.old['version']}" if self.old else "none"
        return [f"Reference list: {old} -> {self.new['rl_id']} v{self.new['version']}",
                f"Concepts: {self.unchanged} unchanged, {self.changed} with changed senses, {self.added} added, "
                f"{self.dropped} no longer on the list.",
                f"Glossary rules: {self.rules_carried} carried over, {len(self.rules_stale)} marked STALE for review."]


def _diff(old: list[Mapping[str, Any]], new: list[Mapping[str, Any]], report: RepinReport) -> None:
    """Count concepts added, dropped, changed and unchanged between two versions."""
    def senses(entry: Mapping[str, Any]) -> list[str]:
        """Recurring sense keys of an entry."""
        return sorted(s["sense_key"] for s in entry["senses"] if s["kind"] == "SENSE")

    before = {e["concept_key"]: e for e in old if e["status"] != "DROPPED"}
    after = {e["concept_key"]: e for e in new if e["status"] != "DROPPED"}
    report.added = len(after.keys() - before.keys())
    report.dropped = len(before.keys() - after.keys())
    for key in before.keys() & after.keys():
        if senses(before[key]) == senses(after[key]):
            report.unchanged += 1
        else:
            report.changed += 1


def repin(job_store: Any, job: Any, rl_store: ReferenceListStore, rl_id: str, version: int | None, *,
          actor: str, lock_path: Path, source_corpus_sha256: str, reports_root: Path) -> RepinReport:
    """Pin ``rl_id`` (``version`` or the newest) to ``job``; mark rules of vanished groups STALE; report."""
    open_runs = job_store.open_run_ids(job)
    if open_runs:
        raise ValidationError("Cannot re-pin the reference list while a Run is open", code="JOB_DEFAULTS_RUN_OPEN",
                              next_action="Finish or abandon the open Run, then re-pin.",
                              details={"run_ids": list(open_runs)})
    new_pin = pin_for(rl_store, rl_id, version)
    old_pin = job.defaults.get("reference_list")
    report = RepinReport(dict(old_pin) if old_pin else None, new_pin)
    _, new_entries = resolve_pin(rl_store, new_pin)
    old_entries: list[dict[str, Any]] = []
    if old_pin:
        try:
            _, old_entries = resolve_pin(rl_store, old_pin)
        except ValidationError:
            old_entries = []  # the old version is gone or changed: everything counts as added
    _diff(old_entries, new_entries, report)
    live = live_group_ids(new_entries)
    rules = current_rules(job.root)
    for rule in sorted(rules.values(), key=lambda r: r["rule_id"]):
        if rule["state"] not in LIVE_RULE_STATES:
            continue
        if rule["group_id"] in live:
            report.rules_carried += 1
            continue
        stale = dict(rule, state="STALE",
                     rationale=rule["rationale"] + f" Marked STALE: its concept or sense is not on reference list "
                                                   f"{rl_id} v{new_pin['version']}.")
        _append_rule(job, lock_path, source_corpus_sha256, stale, "MARK_STALE", actor, rules)
        report.rules_stale.append(rule["rule_id"])
    job_store.revise_job(job, defaults={**job.defaults, "reference_list": new_pin})
    report.report_path = _write_report(report, job.job_id, reports_root)
    return report


def _write_report(report: RepinReport, job_id: str, reports_root: Path) -> Path:
    """``PCC-REPIN-<rl_id>-v<n>.md`` in the Job's report folder."""
    folder = Path(reports_root) / job_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"PCC-REPIN-{report.new['rl_id']}-v{report.new['version']}.md"
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# PCC reference list re-pin: {job_id}", "", when, ""] + [f"- {line}" for line in report.lines()]
    if report.rules_stale:
        lines += ["", "## Rules marked STALE", "", "Review these renderings; they no longer match a concept and sense "
                  "on the pinned list. They stay in the journal and are never applied.", ""]
        lines += [f"- {rule_id}" for rule_id in report.rules_stale]
    atomic_write_text(path, "\n".join(lines) + "\n")
    return path
