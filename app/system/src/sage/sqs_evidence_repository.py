"""SQS-backed QualificationEvidenceRepository -- extension seam only, not wired into live routing.

This class exists so a future Skill *could* be connected to SQS-sourced
evidence without inventing a new repository shape at that time. It is not
called from any current routing path (skill_routing.qualified_skill_routes/
resolve_skill_route always use the default LocalQualificationEvidenceRepository
today; nothing constructs this class outside its own tests).

Why it always returns empty, not just "empty until a mapping exists":
skill_routing._record_identity_matches requires an exact skill_sha256 and
suite_sha256 match -- proof a route passed *that specific registered Skill's*
qualification suite (system/config/model-policy.yml's skill_routes). SQS
evidence was never tested against any SAGE Skill's suite; it was tested
against SQS's own grammar/semantic-rewrite evaluation packs, keyed on a
language profile SAGE's routing identity has no field for at all. There is
no legitimate skill_sha256/suite_sha256 this repository could attach to SQS
evidence -- inventing one to satisfy the exact-match check would be forging
evidence, not bridging a real gap. Connecting a Skill to SQS evidence for
real requires SAGE's routing identity model to gain a language-profile
dimension first (a separate, larger design decision, deliberately deferred).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .sqs_cache import SqsCache


@dataclass(frozen=True)
class SqsQualificationEvidenceRepository:
    """Protocol-conformant placeholder: always returns no records.

    Retains a real SqsCache so a future implementation has everything it
    needs once the routing-identity gap above is actually resolved, without
    this class's construction signature needing to change.
    """

    cache: SqsCache

    def records_for_skill(self, skill_id: str) -> Sequence[Mapping[str, Any]]:
        """Return no records: see the module docstring for why this is not a temporary limitation."""
        del skill_id
        return []
