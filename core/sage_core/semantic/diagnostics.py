"""Deterministic semantic diagnostics used by BIC and SAW before AI analysis."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def semantic_dispersion(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag one lemma spanning several top-level semantic domains for later semantic review."""
    by_lemma: dict[str, set[str]] = defaultdict(set)
    for record in records:
        lemma = record.get("lemma")
        if not lemma:
            continue
        for sense in record.get("senses", []) or []:
            for domain in sense.get("semdom", []) or []:
                code = str(domain.get("code", "")).strip()
                if code:
                    by_lemma[str(lemma)].add(code.split(".", 1)[0])
    return [
        {"lemma": lemma, "top_level_domains": sorted(domains), "signal": "SEMANTIC_DISPERSION"}
        for lemma, domains in sorted(by_lemma.items(), key=lambda item: item[0].casefold())
        if len(domains) >= 3
    ]


def saw_signals_from_scope_evidence(packet: dict[str, Any]) -> dict[str, Any]:
    """Derive bounded semantic triage signals without creating SAW findings."""
    signals: list[dict[str, Any]] = []
    for match in packet.get("matches", []) or []:
        if not isinstance(match, dict):
            continue
        senses = [item for item in match.get("senses", []) or [] if isinstance(item, dict)]
        domains = {
            str(domain.get("code", "")).strip()
            for sense in senses
            for domain in (sense.get("semdom", []) or [])
            if isinstance(domain, dict) and str(domain.get("code", "")).strip()
        }
        top_levels = {value.split(".", 1)[0] for value in domains}
        if any(bool(sense.get("identity_conflict")) for sense in senses):
            signals.append(
                {
                    "signal": "INDEX_IDENTITY_CONFLICT",
                    "surface_form": match.get("surface_form"),
                    "interpretation": "TRIAGE_ONLY",
                }
            )
        if len(senses) >= 2:
            signals.append(
                {
                    "signal": "MULTIPLE_INDEXED_SENSES",
                    "surface_form": match.get("surface_form"),
                    "sense_count": len(senses),
                    "semantic_domains": sorted(domains),
                    "interpretation": "TRIAGE_ONLY",
                }
            )
        if len(top_levels) >= 3:
            signals.append(
                {
                    "signal": "BROAD_SEMANTIC_DISPERSION",
                    "surface_form": match.get("surface_form"),
                    "top_level_domains": sorted(top_levels),
                    "interpretation": "TRIAGE_ONLY",
                }
            )
    return {
        "schema_version": "1.0",
        "source_project": packet.get("project_id"),
        "semantic_language": packet.get("semantic_language"),
        "signal_count": len(signals),
        "signals": signals,
        "authority_rule": (
            "Deterministic semantic-index signals are interrogation candidates only. "
            "SAW must verify meaning in bounded evidence before creating a finding."
        ),
    }
