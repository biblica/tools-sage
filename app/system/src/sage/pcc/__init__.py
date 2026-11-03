"""Phrase Consistency Checker (PCC).

Two functions on one Job (plan ``app/docs/superpowers/plans/2026-11-02-PCC-IMPLEMENTATION-PLAN.md``):
``terms`` builds a SOURCE terms list for the translation team, and ``check`` checks a WIP against the
team's glossary. Every step on the deterministic path is local and uses no LLM.
"""

from __future__ import annotations

ENGINE_VERSION = "pcc-0.1.0-p1"
OPERATIONS = ("terms", "check")
