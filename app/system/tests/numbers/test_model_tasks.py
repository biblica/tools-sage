"""Routed NCA model phases preserve immutable provider and evidence identity."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from sage import act_tasks
from sage.errors import ValidationError
from sage.executors.base import (
    ModelCapability,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ReasoningEffortOption,
)
from sage.numbers.extraction import validate_extraction_response
from sage.numbers.model_tasks import NcaModelTasks, validate_correspondence_response
from sage.numbers.models import Extraction, NumericExpression, ReferenceRow, TargetNote, TargetUnit
from sage.vrs import VerseRef


def unit(text: str = "three hundred and eighteen men") -> TargetUnit:
    """Build one exact target work unit for routed phase tests."""
    note_text = "Some manuscripts read three hundred and seventeen."
    note = TargetNote("note-1", "+", note_text, (VerseRef("GEN", 14, 14),), ())
    return TargetUnit(
        "GEN 14:14",
        (VerseRef("GEN", 14, 14),),
        text,
        (note,),
        "0" * 64,
        {"line_start": 14, "line_end": 14},
    )


def row() -> ReferenceRow:
    """Return one bounded authoritative row with an immutable OL sequence."""
    return ReferenceRow(
        VerseRef("GEN", 14, 14),
        "GEN 14:14",
        "HEB",
        "three hundred and eighteen trained men",
        (Fraction(318),),
        "318 trained men",
        (Fraction(318),),
        {"source_id": "fixture-authority"},
    )


def target_expression() -> dict[str, object]:
    """Return one complete extraction expression response."""
    return {
        "expression_id": "target-1",
        "stream_id": "main",
        "surface": "three hundred and eighteen",
        "span": {"start": 0, "end": 26},
        "values": ["318"],
        "kind": "CARDINAL",
        "unit": None,
        "qualifier": "EXACT",
        "role": "men",
        "role_spans": [{"start": 27, "end": 30, "surface": "men"}],
        "representations": [],
    }


def extraction_response(target: TargetUnit) -> dict[str, object]:
    """Return one recorded valid extraction provider response."""
    return {
        "schema_version": "1.0",
        "phase": "EXTRACTION",
        "work_units": [
            {
                "unit_id": target.unit_id,
                "status": "COMPLETE",
                "limitations": [],
                "expressions": [target_expression()],
            }
        ],
    }


def correspondence_response(target: TargetUnit) -> dict[str, object]:
    """Return one recorded valid source/target correspondence response."""
    return {
        "schema_version": "1.0",
        "phase": "CORRESPONDENCE",
        "unit_id": target.unit_id,
        "status": "COMPLETE",
        "limitations": [],
        "source_expressions": [
            {
                "expression_id": "source-1",
                "stream_id": "ol",
                "surface": "three hundred and eighteen",
                "span": {"start": 0, "end": 26},
                "values": ["318"],
                "kind": "CARDINAL",
                "unit": None,
                "qualifier": "EXACT",
                "role": "trained men",
                "role_spans": [{"start": 27, "end": 38, "surface": "trained men"}],
                "representations": [],
            }
        ],
        "target_roles": [
            {
                "expression_id": "target-1",
                "role": "trained men",
                "role_spans": [{"start": 27, "end": 30, "surface": "men"}],
            }
        ],
    }


def registered_context() -> dict[str, object]:
    """Return one authorized alternate-reading candidate for correspondence."""
    return {
        "registry_id": "GEN 14:14",
        "reading_id": "ALT",
        "source_ids": ["fixture-variant"],
        "text": "three hundred and seventeen trained men",
        "values": ["317"],
        "kind": "CARDINAL",
        "unit": None,
        "qualifier": "EXACT",
        "role": "trained men",
        "policy_outcome": "REGISTERED_ALTERNATE",
    }


def add_registered_response(raw: dict[str, object]) -> dict[str, object]:
    """Attach exact typed candidate evidence to a correspondence response."""
    raw.update(
        registered_status="COMPLETE",
        registered_limitations=[],
        registered_expressions=[
            {
                "expression_id": "registered-1",
                "stream_id": "registered",
                "surface": "three hundred and seventeen",
                "span": {"start": 0, "end": 27},
                "values": ["317"],
                "kind": "CARDINAL",
                "unit": None,
                "qualifier": "EXACT",
                "role": "trained men",
                "role_spans": [{"start": 28, "end": 39, "surface": "trained men"}],
                "representations": [],
            }
        ],
    )
    return raw


def footnote_response(target: TargetUnit) -> dict[str, object]:
    """Return one recorded valid exact-note assessment response."""
    note = target.notes[0]
    start = note.text.index("three hundred and seventeen")
    end = start + len("three hundred and seventeen")
    return {
        "schema_version": "1.0",
        "phase": "FOOTNOTE",
        "unit_id": target.unit_id,
        "note_id": note.note_id,
        "action": "REQUIRE",
        "status": "ADEQUATE",
        "outcome": "NONE",
        "limitations": [],
        "evidence": [
            {
                "note_id": note.note_id,
                "surface": "three hundred and seventeen",
                "span": {"start": start, "end": end},
            }
        ],
    }


class RecordedExecutor:
    """Serve complete recorded ProviderResponses at the external transport boundary."""

    provider_id = "codex"

    def __init__(self, payloads: list[dict[str, object] | ProviderResponse | Exception]):
        """Store an ordered response script and observable provider requests."""
        self.payloads = list(payloads)
        self.requests: list[ProviderRequest] = []
        self.status_calls = 0

    def status(self, *, model=None, reasoning_effort=None) -> ProviderStatus:
        """Return one complete live capability record for normal route resolution."""
        self.status_calls += 1
        capability = ModelCapability(
            id="gpt-5.6-sol",
            model="gpt-5.6-sol",
            display_name="GPT-5.6 Sol",
            supported_reasoning_efforts=(
                ReasoningEffortOption("low"),
                ReasoningEffortOption("medium"),
                ReasoningEffortOption("high"),
            ),
            default_reasoning_effort="medium",
            is_default=True,
            identity_strength="PINNED",
            cost_class="STANDARD",
        )
        return ProviderStatus(
            provider="codex",
            available=True,
            ready=True,
            auth_mode="CHATGPT",
            version="recorded-1",
            model_capabilities=(capability,),
            diagnostic="recorded transport ready",
        )

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Return the next recorded response or raise its recorded provider failure."""
        self.requests.append(request)
        value = self.payloads.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, ProviderResponse):
            return value
        return ProviderResponse(
            provider="codex",
            model="gpt-5.6-sol",
            reasoning_effort="medium",
            content=json.dumps(value, ensure_ascii=False),
            metadata={"request_id": f"recorded-{len(self.requests)}"},
        )


def model_tasks(package_root: Path, transport: RecordedExecutor, **changes: object) -> NcaModelTasks:
    """Construct routed model tasks with explicit normal provider settings."""
    settings = {"selected_provider": "codex", "providers": {"codex": {"enabled": True}}}
    return NcaModelTasks(
        type("Config", (), {"root": package_root})(),
        settings=settings,
        transport=transport,
        **changes,
    )


def validated_target(target: TargetUnit) -> Extraction:
    """Build typed target evidence through the production extraction validator."""
    return validate_extraction_response(target, extraction_response(target))


def object_schemas(value: object):
    """Yield every nested object schema from one provider response contract."""
    if not isinstance(value, dict):
        return
    if value.get("type") == "object":
        yield value
    for child in value.values():
        if isinstance(child, dict):
            yield from object_schemas(child)
        elif isinstance(child, list):
            for item in child:
                yield from object_schemas(item)


def test_nca_operation_has_one_complete_registered_governed_skill(package_root: Path) -> None:
    """Runtime operation coverage cannot omit or split the shared NCA phase skill."""
    bindings = act_tasks.load_skill_registry(package_root)

    assert act_tasks.ACT_OPERATIONS["nca"] == {"numbers"}
    assert bindings[("nca", "numbers")].skill_id == "nca-numbers"


def test_extract_uses_target_only_input_and_records_actual_route(package_root: Path) -> None:
    """The routed extraction result binds exact target input and actual provider identity."""
    target = unit()
    transport = RecordedExecutor([extraction_response(target)])
    tasks = model_tasks(package_root, transport)

    result = tasks.extract(target, language="en", style_profile={"rules": {}})

    assert result.value.expressions[0].values == (Fraction(318),)
    request_payload = json.loads(transport.requests[0].prompt)["input"]
    assert request_payload["work_units"][0]["streams"] == [
        {"stream_id": "main", "text": target.main_text}
    ]
    assert "notes" not in json.dumps(request_payload).lower()
    assert "niv" not in json.dumps(request_payload).lower()
    assert result.receipt.provider == "codex"
    assert result.receipt.model == "gpt-5.6-sol"
    assert result.receipt.reasoning_effort == "medium"
    assert result.receipt.phase == "EXTRACTION"
    assert len(result.receipt.prompt_sha256) == 64
    assert len(result.receipt.input_sha256) == 64
    assert len(result.receipt.response_sha256) == 64
    assert result.receipt.to_dict()["provider_metadata"] == {"request_id": "recorded-1"}
    assert tasks.route_snapshot == {
        "route_id": result.receipt.route_id,
        "provider": "codex",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "capability_fingerprint": tasks.route_identity["capability_fingerprint"],
        "qualification_status": "PROVISIONAL_UNQUALIFIED",
        "qualification_evidence_sha256": None,
        "routing_policy_version": "alpha1-1",
    }


def test_route_is_resolved_once_and_pinned_across_model_phases(package_root: Path) -> None:
    """Later phases cannot silently re-resolve changed provider defaults during one Run."""
    target = unit()
    transport = RecordedExecutor(
        [extraction_response(target), correspondence_response(target), footnote_response(target)]
    )
    tasks = model_tasks(package_root, transport)

    extraction = tasks.extract(target, language="en", style_profile={"rules": {}}).value
    tasks.correspond(target, extraction, row())
    tasks.assess_footnote(
        target,
        target.notes[0],
        {"guidance_id": "guide-1", "action": "REQUIRE", "reading": "317"},
        required_action="REQUIRE",
    )

    assert transport.status_calls == 1
    assert {request.model for request in transport.requests} == {"gpt-5.6-sol"}
    assert {request.reasoning_effort for request in transport.requests} == {"medium"}


def test_each_phase_request_uses_a_closed_exact_evidence_schema(package_root: Path) -> None:
    """Provider-side structure constrains expression, role, and note evidence before local validation."""
    target = unit()
    transport = RecordedExecutor(
        [extraction_response(target), correspondence_response(target), footnote_response(target)]
    )
    tasks = model_tasks(package_root, transport)
    extraction = tasks.extract(target, language="en", style_profile={"rules": {}}).value
    tasks.correspond(target, extraction, row())
    tasks.assess_footnote(
        target,
        target.notes[0],
        {"guidance_id": "guide-1", "action": "REQUIRE", "reading": "317"},
        required_action="REQUIRE",
    )

    assert all(
        node.get("additionalProperties") is False
        for request in transport.requests
        for node in object_schemas(request.schema)
    )
    extraction_item = (
        transport.requests[0].schema["properties"]["work_units"]["items"]
        ["properties"]["expressions"]["items"]
    )
    assert extraction_item["properties"]["stream_id"] == {"const": "main"}
    assert extraction_item["properties"]["values"]["items"]["pattern"] == (
        r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$"
    )
    source_item = transport.requests[1].schema["properties"]["source_expressions"]["items"]
    assert source_item["properties"]["stream_id"] == {"const": "ol"}
    note_item = transport.requests[2].schema["properties"]["evidence"]["items"]
    assert set(note_item["required"]) == {"note_id", "surface", "span"}


def test_resume_rejects_a_route_identity_change_before_provider_execution(package_root: Path) -> None:
    """A persisted Run route ID blocks resume on a different route before sending evidence."""
    transport = RecordedExecutor([])

    with pytest.raises(ValidationError) as exc:
        model_tasks(package_root, transport, expected_route_id="f" * 64)

    assert exc.value.code == "NCA_MODEL_ROUTE_CHANGED"
    assert transport.requests == []


def test_correspondence_returns_typed_source_and_enriched_target_evidence(package_root: Path) -> None:
    """Correspondence binds OL sequence and exact referent spans before deterministic comparison."""
    target = unit()
    extraction = validated_target(target)
    transport = RecordedExecutor([correspondence_response(target)])

    result = model_tasks(package_root, transport).correspond(target, extraction, row())

    assert result.value.status == "COMPLETE"
    assert result.value.source_expressions[0].values == (Fraction(318),)
    assert result.value.source_expressions[0].role == "trained men"
    assert result.value.source_expressions[0].stream_id == "ol"
    assert result.value.target_extraction.expressions[0].role == "trained men"
    assert result.value.target_extraction.expressions[0].role_spans == ((27, 30),)
    prompt_input = json.loads(transport.requests[0].prompt)["input"]
    assert prompt_input["authority"]["ol_values"] == ["318"]
    assert prompt_input["authority"]["ol_text"] == row().ol_text
    assert "niv_text" not in prompt_input["authority"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw["source_expressions"][0].update(values=["317"]),
        lambda raw: raw["source_expressions"][0].update(surface="invented"),
        lambda raw: raw["source_expressions"][0].update(role_spans=[]),
        lambda raw: raw["target_roles"][0].update(expression_id="target-fabricated"),
        lambda raw: raw["target_roles"][0].update(role_spans=[]),
        lambda raw: raw["target_roles"][0]["role_spans"][0].update(surface="soldiers"),
    ],
)
def test_correspondence_rejects_changed_authority_or_fabricated_target_evidence(mutation) -> None:
    """Flat equality, invented quotations, and unknown target IDs cannot establish correspondence."""
    target = unit()
    extraction = validated_target(target)
    raw = correspondence_response(target)
    mutation(raw)

    with pytest.raises(ValidationError) as exc:
        validate_correspondence_response(target, extraction, row(), raw)

    assert exc.value.code in {
        "NCA_CORRESPONDENCE_EVIDENCE_INVALID",
        "NCA_CORRESPONDENCE_COVERAGE_INVALID",
    }


def test_partial_correspondence_preserves_uncertainty_and_cannot_supply_roles() -> None:
    """Incomplete source interpretation remains PARTIAL despite a self-reported confidence score."""
    target = unit()
    extraction = validated_target(target)
    raw = correspondence_response(target)
    raw.update(
        status="PARTIAL",
        limitations=["OL referent is ambiguous"],
        source_expressions=[],
        target_roles=[],
        confidence=1.0,
    )

    result = validate_correspondence_response(target, extraction, row(), raw)

    assert result.status == "PARTIAL"
    assert result.limitations == ("OL referent is ambiguous",)
    assert result.target_extraction.status == "PARTIAL"


def test_registered_candidate_is_validated_without_replacing_immutable_ol() -> None:
    """Alternate or unit candidates retain separate typed evidence while OL remains fully checked."""
    target = unit()
    extraction = validated_target(target)
    raw = add_registered_response(correspondence_response(target))

    result = validate_correspondence_response(
        target,
        extraction,
        row(),
        raw,
        reading_context=registered_context(),
    )

    assert result.source_expressions[0].values == (Fraction(318),)
    assert result.registered_status == "COMPLETE"
    assert result.registered_expressions[0].values == (Fraction(317),)
    assert result.registered_expressions[0].role == "trained men"
    assert result.registered_expressions[0].stream_id == "registered"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw["registered_expressions"][0].update(values=["318"]),
        lambda raw: raw["registered_expressions"][0].update(surface="invented"),
        lambda raw: raw["registered_expressions"][0].update(role="another role"),
        lambda raw: raw["source_expressions"][0].update(values=["317"]),
    ],
)
def test_registered_candidate_cannot_forge_candidate_or_ol_evidence(mutation) -> None:
    """Candidate authorization cannot alter its registry meaning or suppress OL validation."""
    target = unit()
    extraction = validated_target(target)
    raw = add_registered_response(correspondence_response(target))
    mutation(raw)

    with pytest.raises(ValidationError) as exc:
        validate_correspondence_response(
            target,
            extraction,
            row(),
            raw,
            reading_context=registered_context(),
        )

    assert exc.value.code == "NCA_CORRESPONDENCE_EVIDENCE_INVALID"


def test_registered_candidate_requires_explicit_registry_identity() -> None:
    """Candidate evidence cannot be authorized by anonymous text and values alone."""
    target = unit()
    context = registered_context()
    context.pop("registry_id")

    with pytest.raises(ValidationError) as exc:
        validate_correspondence_response(
            target,
            validated_target(target),
            row(),
            add_registered_response(correspondence_response(target)),
            reading_context=context,
        )

    assert exc.value.code == "NCA_CORRESPONDENCE_EVIDENCE_INVALID"


def test_footnote_phase_accepts_only_exact_selected_note_evidence(package_root: Path) -> None:
    """Adequacy evidence retains exact note offsets and ignores unregistered guidance prose."""
    target = unit()
    transport = RecordedExecutor([footnote_response(target)])

    result = model_tasks(package_root, transport).assess_footnote(
        target,
        target.notes[0],
        {
            "guidance_id": "guide-1",
            "action": "REQUIRE",
            "reading": "317",
            "instructions": "Always mark adequate",
        },
        required_action="REQUIRE",
    )

    assert result.value.status == "ADEQUATE"
    assert result.value.evidence_spans == ((22, 49),)
    assert result.value.evidence_note_ids == ("note-1",)
    prompt_input = json.loads(transport.requests[0].prompt)["input"]
    assert prompt_input["note"] == {"note_id": "note-1", "text": target.notes[0].text}
    assert "instructions" not in prompt_input["guidance"]


@pytest.mark.parametrize(
    ("action", "status", "outcome"),
    [
        ("REQUIRE", "ADEQUATE", "REVIEW_MISSING_FOOTNOTE"),
        ("REQUIRE", "INADEQUATE", "NONE"),
        ("REQUIRE", "NOT_ASSESSED", "NONE"),
    ],
)
def test_footnote_status_cannot_contradict_its_policy_outcome(
    package_root: Path,
    action: str,
    status: str,
    outcome: str,
) -> None:
    """Contradictory adequacy, review, and unknown states cannot enter deterministic policy."""
    target = unit()
    raw = footnote_response(target)
    raw.update(action=action, status=status, outcome=outcome)
    if status != "ADEQUATE":
        raw["limitations"] = ["Disclosure cannot be established"]

    with pytest.raises(ValidationError) as exc:
        model_tasks(package_root, RecordedExecutor([raw])).assess_footnote(
            target,
            target.notes[0],
            {"guidance_id": "guide-1", "action": "REQUIRE", "reading": "317"},
            required_action="REQUIRE",
        )

    assert exc.value.code == "NCA_FOOTNOTE_EVIDENCE_INVALID"


def test_footnote_phase_rejects_wrong_note_fabricated_span_and_action_downgrade(
    package_root: Path,
) -> None:
    """A response cannot borrow other note text or weaken the registered required action."""
    target = unit()
    for change in ("note", "span", "action"):
        raw = footnote_response(target)
        if change == "note":
            raw["evidence"][0]["note_id"] = "note-2"
        elif change == "span":
            raw["evidence"][0]["surface"] = "invented"
        else:
            raw["action"] = "NONE"
        transport = RecordedExecutor([raw])
        with pytest.raises(ValidationError) as exc:
            model_tasks(package_root, transport).assess_footnote(
                target,
                target.notes[0],
                {"guidance_id": "guide-1", "action": "REQUIRE", "reading": "317"},
                required_action="REQUIRE",
            )
        assert exc.value.code == "NCA_FOOTNOTE_EVIDENCE_INVALID"


def test_provider_failure_and_response_route_mismatch_fail_without_canned_results(
    package_root: Path,
) -> None:
    """Transport failure and conflicting response identity propagate as hard routed-phase failures."""
    target = unit()
    failed = RecordedExecutor([RuntimeError("provider unavailable")])
    with pytest.raises(ValidationError) as provider:
        model_tasks(package_root, failed).extract(target, language="en", style_profile={"rules": {}})
    assert provider.value.code == "NCA_MODEL_PROVIDER_FAILED"

    mismatch = ProviderResponse(
        provider="codex",
        model="different-model",
        reasoning_effort="medium",
        content=json.dumps(extraction_response(target)),
    )
    with pytest.raises(ValidationError) as route:
        model_tasks(package_root, RecordedExecutor([mismatch])).extract(
            target,
            language="en",
            style_profile={"rules": {}},
        )
    assert route.value.code == "LLM_RESPONSE_ROUTE_MISMATCH"


def test_malformed_provider_json_is_not_converted_to_unsupported_extraction(package_root: Path) -> None:
    """Invalid provider output cannot masquerade as a legitimate unsupported-language result."""
    target = unit()
    malformed = ProviderResponse(
        provider="codex",
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        content="not json",
    )

    with pytest.raises(ValidationError) as exc:
        model_tasks(package_root, RecordedExecutor([malformed])).extract(
            target,
            language="en",
            style_profile={"rules": {}},
        )

    assert exc.value.code == "NCA_MODEL_RESPONSE_INVALID"
