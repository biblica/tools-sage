"""Routed NCA model phases preserve immutable provider and evidence identity."""

from __future__ import annotations

import json
from dataclasses import replace
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


@pytest.mark.parametrize("stream", ["ol", "registered"])
def test_correspondence_rejects_overlapping_primary_expression_spans(stream: str) -> None:
    """One source character cannot supply two independently counted expressions."""
    target = unit()
    raw = correspondence_response(target)
    authority = row()
    context = None
    expressions = []
    for index, (start, end, value) in enumerate(((0, 2, "12"), (1, 3, "23"))):
        expression = dict(raw["source_expressions"][0])
        expression.update(
            expression_id=f"{stream}-{index}", stream_id=stream,
            surface="123 men"[start:end], span={"start": start, "end": end},
            values=[value], role="men",
            role_spans=[{"start": 4, "end": 7, "surface": "men"}],
        )
        expressions.append(expression)
    if stream == "ol":
        authority = replace(authority, ol_text="123 men", ol_values=(Fraction(12), Fraction(23)))
        raw["source_expressions"] = expressions
    else:
        context = registered_context()
        context.update(text="123 men", values=["12", "23"], role="men")
        raw.update(registered_status="COMPLETE", registered_limitations=[], registered_expressions=expressions)

    with pytest.raises(ValidationError) as exc:
        validate_correspondence_response(target, validated_target(target), authority, raw, reading_context=context)

    assert exc.value.code == "NCA_CORRESPONDENCE_EVIDENCE_INVALID"


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


def test_extract_batch_has_one_target_only_capsule_and_exact_parent_receipt(package_root):
    """One physical batch call binds raw bytes and every local item without usage cloning."""
    import hashlib
    from sage.numbers.telemetry import summarize_calls
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    raw_text = ' \n' + json.dumps(batch_response(batch), ensure_ascii=False, indent=2) + '\n'
    transport = RecordedExecutor([ProviderResponse(provider='codex', model='gpt-5.6-sol',
        reasoning_effort='medium', content=raw_text, metadata={'usage': {'input_tokens': 100, 'output_tokens': 50}})])
    tasks = model_tasks(package_root, transport)
    assert hasattr(tasks, 'extract_batch'), 'one-call batch extraction is not implemented'
    result = tasks.extract_batch(batch, parsing_conventions={'ol_values': ['318'], 'registry_present': True})
    assert len(transport.requests) == 1
    prompt = json.loads(transport.requests[0].prompt)
    assert prompt['task_version'] == result.receipt.task_version == 'nca-extraction-2.0'
    assert prompt['input']['routed_sfm'] == batch.routed_sfm
    assert prompt['input']['parsing_conventions'] == {}
    assert all(word not in prompt['skill_contract'].lower() for word in ('niv', 'registry', 'correspondence', 'footnote'))
    assert len(result.value.item_sha256) == 2
    assert result.raw_response == raw_text
    assert result.receipt.response_sha256 == hashlib.sha256(raw_text.encode()).hexdigest()
    assert len(tasks.attempts) == 1
    attempt = tasks.attempts[0]
    assert attempt.raw_response == raw_text
    assert attempt.measurement.response_bytes == len(raw_text.encode())
    assert attempt.measurement.unit_ids == tuple(value.input_id for value in batch.inputs)
    wire = dict(prompt=transport.requests[0].prompt, schema=transport.requests[0].schema,
        model='gpt-5.6-sol', reasoning_effort='medium', timeout_seconds=600)
    assert attempt.measurement.request_bytes == len(json.dumps(wire, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode())
    assert summarize_calls(tuple(value.measurement for value in tasks.attempts))['input_tokens'] == 100
    assert all(node.get('additionalProperties') is False for node in object_schemas(transport.requests[0].schema))


@pytest.mark.parametrize('failure', ['provider', 'truncation', 'schema', 'route'])
def test_failed_batch_attempts_retain_raw_evidence_and_exact_call_count(package_root, failure):
    """Failed physical calls remain measurable even when no validated receipt can be admitted."""
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    content = '{"schema_version":' if failure == 'truncation' else json.dumps(batch_response(batch))
    if failure == 'schema':
        content = '{}'
    value = RuntimeError('transient') if failure == 'provider' else ProviderResponse(
        provider='codex', model='wrong' if failure == 'route' else 'gpt-5.6-sol',
        reasoning_effort='medium', content=content)
    transport = RecordedExecutor([value])
    tasks = model_tasks(package_root, transport)
    assert hasattr(tasks, 'extract_batch'), 'one-call batch extraction is not implemented'
    with pytest.raises(ValidationError):
        tasks.extract_batch(batch, parsing_conventions={})
    assert len(tasks.attempts) == len(transport.requests) == 1
    assert tasks.attempts[0].raw_response == (None if failure == 'provider' else content)
    assert tasks.attempts[0].measurement.status not in {'SUCCESS', 'COMPLETE', 'VALIDATED'}


def test_batch_preflight_failure_is_not_a_physical_attempt(package_root):
    """Invalid conventions cannot create phantom provider calls or telemetry."""
    from .test_batch_extraction import batch_fixture
    tasks = model_tasks(package_root, RecordedExecutor([]))
    assert hasattr(tasks, 'extract_batch'), 'one-call batch extraction is not implemented'
    with pytest.raises(ValidationError):
        tasks.extract_batch(batch_fixture(), parsing_conventions={'digits': {'preferred': '0'}})
    assert tasks.attempts == ()


def bounded_extract(tasks, batch, **kwargs):
    """Call the focused orchestration API with an explicit RED assertion."""
    from sage.numbers import model_tasks as module
    assert hasattr(module, 'extract_batch_with_retries'), 'bounded extraction is not implemented'
    return module.extract_batch_with_retries(tasks, batch, parsing_conventions={}, **kwargs)


@pytest.mark.parametrize('count', [1, 2, 4])
def test_retry_split_tree_has_finite_attempts_and_explicit_singleton_failures(package_root, count):
    """Repeated physical failures terminate within two attempts per binary-tree node."""
    from .test_batch_extraction import batch_fixture
    batch = batch_fixture(tuple('three men' for _ in range(count)))
    bound = 2 * (2 * count - 1)
    transport = RecordedExecutor([RuntimeError('transient') for _ in range(bound)])
    tasks = model_tasks(package_root, transport)
    result = bounded_extract(tasks, batch)
    assert len(transport.requests) == len(tasks.attempts) == bound
    assert len({value.measurement.request_id for value in tasks.attempts}) == bound
    assert not result.accepted
    assert set(result.pending) == {value.input_id for value in batch.inputs}
    assert all(value.startswith('NCA_BATCH_SINGLETON_FAILED') for value in result.pending.values())
    assert {request.model for request in transport.requests} == {'gpt-5.6-sol'}
    assert transport.status_calls == 1


@pytest.mark.parametrize('status', ['COMPLETE', 'PARTIAL', 'UNSUPPORTED'])
def test_accepted_items_checkpoint_before_remaining_calls_and_never_resubmit(package_root, status):
    """Durable parent acceptance precedes retries and incomplete interpretation stays terminal."""
    from sage.numbers.batching import _batch
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    raw = batch_response(batch)
    raw['work_units'].pop()
    raw['work_units'][0].update(status=status, limitations=[] if status == 'COMPLETE' else ['ambiguous'])
    remaining = _batch(batch.inputs[1:], batch.inputs[1].routed_sfm)
    transport = RecordedExecutor([raw, batch_response(remaining)])
    tasks = model_tasks(package_root, transport)
    parents = []

    def checkpoint(result):
        """Prove parent evidence is available before another provider request occurs."""
        assert len(transport.requests) == len(parents) + 1
        assert result.raw_response
        parents.append(result)

    result = bounded_extract(tasks, batch, on_accept=checkpoint)
    assert len(parents) == 2 and len(result.parents) == 2 and not result.pending
    assert result.accepted[batch.inputs[0].input_id].status == status
    assert json.loads(transport.requests[1].prompt)['input']['work_units'][0]['input_id'] == batch.inputs[1].input_id
    assert len(json.loads(transport.requests[1].prompt)['input']['work_units']) == 1


def test_acceptance_callback_interruption_is_not_retried(package_root):
    """A failed durable checkpoint interrupts before any next provider request."""
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    raw = batch_response(batch)
    raw['work_units'].pop()
    transport = RecordedExecutor([raw])
    tasks = model_tasks(package_root, transport)

    def interrupt(result):
        """Simulate a checkpoint interruption that must propagate unchanged."""
        raise RuntimeError('checkpoint interrupted')

    with pytest.raises(RuntimeError, match='checkpoint interrupted'):
        bounded_extract(tasks, batch, on_accept=interrupt)
    assert len(transport.requests) == 1


@pytest.mark.parametrize('retries', [True, -1, 2, '1'])
def test_invalid_retry_budget_fails_before_provider_calls(package_root, retries):
    """Only zero or one exact retry may be configured within the physical call bound."""
    from .test_batch_extraction import batch_fixture
    transport = RecordedExecutor([])
    with pytest.raises(ValidationError):
        bounded_extract(model_tasks(package_root, transport), batch_fixture(), transient_retries=retries)
    assert not transport.requests


def test_route_mismatch_does_not_retry_or_split(package_root):
    """A pinned identity failure cannot authorize more requests or another route."""
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    transport = RecordedExecutor([ProviderResponse(provider='codex', model='wrong',
        reasoning_effort='medium', content=json.dumps(batch_response(batch)))])
    with pytest.raises(ValidationError) as exc:
        bounded_extract(model_tasks(package_root, transport), batch)
    assert exc.value.code == 'LLM_RESPONSE_ROUTE_MISMATCH'
    assert len(transport.requests) == 1


def test_retry_then_split_accepts_recorded_children_on_the_pinned_route(package_root):
    """A failed parent can bisect into valid independent receipts without route substitution."""
    from sage.numbers.batching import split_batch
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    children = split_batch(batch)
    transport = RecordedExecutor([RuntimeError('transient'), RuntimeError('transient'),
        batch_response(children[0]), batch_response(children[1])])
    tasks = model_tasks(package_root, transport)
    result = bounded_extract(tasks, batch)
    assert not result.pending and len(result.accepted) == 2
    assert len(result.parents) == 2 and len(tasks.attempts) == 4
    assert all(parent.receipt.route_id == tasks.route_snapshot['route_id'] for parent in result.parents)


def test_zero_retries_uses_one_call_per_failed_tree_node(package_root):
    """Disabling transient retries preserves splitting while reducing the physical bound."""
    from .test_batch_extraction import batch_fixture
    transport = RecordedExecutor([RuntimeError('transient')] * 3)
    result = bounded_extract(model_tasks(package_root, transport), batch_fixture(), transient_retries=0)
    assert len(transport.requests) == 3 and len(result.pending) == 2


def test_valid_second_attempt_retains_failed_raw_parent_evidence(package_root):
    """A truncated first attempt remains auditable after a successful same-batch retry."""
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    transport = RecordedExecutor([ProviderResponse(provider='codex', model='gpt-5.6-sol',
        reasoning_effort='medium', content='{'), batch_response(batch)])
    tasks = model_tasks(package_root, transport)
    result = bounded_extract(tasks, batch)
    assert len(result.parents) == 1 and len(tasks.attempts) == 2
    assert tasks.attempts[0].raw_response == '{'
    assert tasks.attempts[0].measurement.status == 'NCA_MODEL_RESPONSE_INVALID'
    assert not result.pending


def test_receipt_rejects_unregistered_phase_version_pair(package_root):
    """A phase cannot relabel a v1 receipt as another phase or an invented task version."""
    target = unit()
    receipt = model_tasks(package_root, RecordedExecutor([extraction_response(target)])).extract(
        target, language='en', style_profile={}).receipt
    for version in ('nca-footnote-1.0', 'nca-extraction-9.0'):
        with pytest.raises(ValidationError) as exc:
            replace(receipt, task_version=version)
        assert exc.value.code == 'NCA_MODEL_RECEIPT_INVALID'


def test_batch_phase_result_requires_exact_receipt_bound_raw_response(package_root):
    """V2 replay cannot rely on reconstructed JSON or discard provider response bytes."""
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    tasks = model_tasks(package_root, RecordedExecutor([batch_response(batch)]))
    result = tasks.extract_batch(batch, parsing_conventions={})
    for raw in (None, result.raw_response + ' '):
        with pytest.raises(ValidationError) as exc:
            replace(result, raw_response=raw)
        assert exc.value.code == 'NCA_MODEL_RECEIPT_INVALID'


def test_parent_result_identifies_exact_physical_request_even_when_responses_repeat(package_root):
    """Replay consumers locate child request bytes by unique attempt ID instead of response hash."""
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    transport = RecordedExecutor([batch_response(batch), batch_response(batch)])
    tasks = model_tasks(package_root, transport)
    first = tasks.extract_batch(batch, parsing_conventions={})
    second = tasks.extract_batch(batch, parsing_conventions={})
    assert hasattr(first, 'request_id'), 'parent result does not identify its physical attempt'
    assert first.receipt.response_sha256 == second.receipt.response_sha256
    assert first.request_id != second.request_id
    assert first.request_id == tasks.attempts[0].measurement.request_id
    assert second.request_id == tasks.attempts[1].measurement.request_id


def test_physical_attempt_elapsed_excludes_local_semantic_validation(package_root, monkeypatch):
    """Provider latency must not absorb local validation time in transport telemetry."""
    from sage.numbers import model_tasks as module
    from .test_batch_extraction import batch_fixture, batch_response
    batch = batch_fixture()
    now = [1_000_000]

    def clock():
        """Return a deterministic wall-clock position around the transport boundary."""
        return now[0]

    class TimedTransport(RecordedExecutor):
        """Advance the clock only by the recorded physical provider latency."""
        def execute(self, request):
            """End the provider request after four milliseconds."""
            now[0] = 5_000_000
            return super().execute(request)

    actual = module.validate_batch_extraction_response

    def expensive_validation(batch, raw):
        """Add local semantic processing after the provider response has arrived."""
        now[0] = 100_000_000
        return actual(batch, raw)

    monkeypatch.setattr(module, 'perf_counter_ns', clock)
    monkeypatch.setattr(module, 'validate_batch_extraction_response', expensive_validation)
    tasks = model_tasks(package_root, TimedTransport([batch_response(batch)]))
    tasks.extract_batch(batch, parsing_conventions={})
    assert tasks.attempts[0].measurement.elapsed_ms == 4
