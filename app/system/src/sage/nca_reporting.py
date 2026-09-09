"""Render canonical NCA machine results as bounded Operator-facing Markdown."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .errors import ValidationError
from .human_output import catalogue_text
from .numbers.results import NCA_CAPABILITY_LIMITATION


_ENGLISH = {
    "report.nca.title": "Number Consistency & Accuracy report",
    "report.nca.authority": "Authority and analyzed snapshot",
    "report.nca.summary": "Summary",
    "report.nca.coverage": "Coverage",
    "report.nca.limitations": "Limitations",
    "report.nca.capability_limitation": NCA_CAPABILITY_LIMITATION,
    "report.nca.checks": "Selected checks",
    "report.nca.units": "Units",
    "report.nca.findings": "Findings",
    "report.nca.no_findings": "No NCA findings were recorded.",
    "report.nca.target_reference": "Target reference",
    "report.nca.target_locator": "Target locator",
    "report.nca.western_reference": "Western reference",
    "report.nca.ol_reference": "Original-language reference",
    "report.nca.selected_reading": "Selected reading",
    "report.nca.source_ids": "Source IDs",
    "report.nca.footnote_action": "Footnote action",
    "report.nca.footnote_status": "Footnote status",
    "report.nca.suggested_note": "Suggested note",
    "report.nca.code": "Code",
    "report.nca.category": "Category",
    "report.nca.outcome": "Outcome",
    "report.nca.restrictions": "Restrictions",
    "report.nca.model_identity": "Model identity",
    "report.nca.style_profile": "Style profile",
    "report.nca.reference_package": "Reference package",
    "report.nca.expressions": "Expressions",
    "report.nca.insufficient_evidence": "Insufficient evidence",
    "report.nca.reference_not_indexed": "Reference not indexed",
    "report.nca.not_assessed": "Not assessed",
    "report.nca.result": "Result",
    "report.nca.confidence_basis": "Confidence basis",
    "report.nca.ol_expressions_checked": "OL expressions checked",
    "report.nca.target_expressions": "Target expressions",
    "report.nca.passes": "Passes",
    "report.nca.unit_conversions": "Unit conversions",
    "report.nca.value_differences": "Value differences",
    "report.nca.missing_numbers": "Missing numbers",
    "report.nca.added_numbers": "Added numbers",
    "report.nca.known_variants": "Known variants",
    "report.nca.style_findings": "Style findings",
    "report.nca.source_expressions": "OL source expressions",
    "report.nca.variant_class": "Variant class",
    "report.nca.scholarship_status": "Scholarship status",
}
_ENGLISH_LANGUAGES = frozenset({"en", "en-US", "en-GB"})
_CATALOG_LANGUAGES = _ENGLISH_LANGUAGES | {"id", "fr", "ru", "pt-BR", "uk"}


def _localization_function(
    *, language: str, localize: Callable[[str], str] | object | None
) -> Callable[[str], str]:
    """Resolve an explicit report-language catalog without silent English fallback."""
    if localize is None:
        if language not in _CATALOG_LANGUAGES:
            raise ValidationError(
                f"NCA report localization is unavailable for {language}.",
                code="NCA_REPORT_TRANSLATION_REQUIRED",
            )
        return lambda key: (
            _ENGLISH[key]
            if catalogue_text(language, key) == key
            else catalogue_text(language, key)
        )
    function = localize if callable(localize) else getattr(localize, "text_key", None)
    if not callable(function):
        raise ValidationError(
            "NCA report localizer must be callable or expose text_key().",
            code="NCA_REPORT_TRANSLATION_REQUIRED",
        )

    def localized(key: str) -> str:
        """Return catalog text, retaining English only for visibly unresolved labels."""
        value = function(key)
        if not isinstance(value, str) or not value.strip() or value == key:
            if key == "report.nca.capability_limitation" and language not in _ENGLISH_LANGUAGES:
                raise ValidationError(
                    f"NCA capability limitation is not localized for {language}.",
                    code="NCA_REPORT_TRANSLATION_REQUIRED",
                )
            return _ENGLISH[key]
        return value

    return localized


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    """Require one report section to be a mapping before rendering it."""
    if not isinstance(value, Mapping):
        raise ValidationError(
            f"NCA report {label} is malformed.", code="NCA_RESULT_SCHEMA_INVALID"
        )
    return value


def _joined(value: object) -> str:
    """Render a bounded sequence without changing the stored identifiers."""
    if not isinstance(value, (list, tuple)):
        return "NOT RECORDED"
    return ", ".join("NULL" if item is None else str(item) for item in value) or "NOT RECORDED"


def _locator(value: object) -> str:
    """Render the immutable target source locator in stable key order."""
    if not isinstance(value, Mapping):
        return "NOT RECORDED"
    return ", ".join(f"{key}={value[key]}" for key in sorted(value)) or "NOT RECORDED"


def _model_identities(value: object) -> tuple[str, ...]:
    """Collect exact provider/model identities from actual phase receipts."""
    if not isinstance(value, Mapping):
        return ()
    identities: list[str] = []
    for phase in ("EXTRACTION", "CORRESPONDENCE", "FOOTNOTE"):
        rows = value.get(phase, ())
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            provider, model = row.get("provider"), row.get("model")
            if isinstance(provider, str) and provider and isinstance(model, str) and model:
                identity = f"{phase}: {provider}/{model}"
                if identity not in identities:
                    identities.append(identity)
    return tuple(identities)


def _expressions(value: object) -> str:
    """Render typed source expressions without changing their canonical values."""
    if not isinstance(value, (list, tuple)):
        return "NOT RECORDED"
    rendered: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        attributes = [str(item.get("kind") or "UNKNOWN")]
        for key in ("role", "unit", "qualifier"):
            if item.get(key) is not None:
                attributes.append(f"{key}={item[key]}")
        rendered.append(
            f"{item.get('surface', 'NOT RECORDED')} = {_joined(item.get('values'))} "
            f"[{' ; '.join(attributes)}]"
        )
    return "; ".join(rendered) or "NOT RECORDED"


def render_nca_report(
    document: Mapping[str, object],
    *,
    language: str = "en",
    localize: Callable[[str], str] | object | None = None,
) -> str:
    """Render NCA evidence while localizing only human-facing prose and labels."""
    if not isinstance(document, Mapping) or document.get("check_id") != "NUMBERS":
        raise ValidationError(
            "NCA report requires a canonical NUMBERS result.",
            code="NCA_RESULT_SCHEMA_INVALID",
        )
    limitations = _mapping(document.get("limitations"), "limitations")
    if (
        limitations.get("capability") != NCA_CAPABILITY_LIMITATION
        or limitations.get("sqs_confidence_checks_applied") is not False
    ):
        raise ValidationError(
            "The NCA capability and SQS limitation is required.",
            code="NCA_RESULT_LIMITATION_REQUIRED",
        )
    text = _localization_function(language=language, localize=localize)
    provenance = _mapping(document.get("provenance"), "provenance")
    style = _mapping(provenance.get("style_profile"), "style profile")
    reference = _mapping(provenance.get("reference_package"), "reference package")
    wip = _mapping(provenance.get("wip"), "WIP")
    checks = _mapping(_mapping(document.get("check_policy"), "check policy").get("checks"), "checks")
    coverage = _mapping(document.get("coverage"), "coverage")
    summary = _mapping(document.get("summary"), "summary")
    findings = document.get("findings")
    units = document.get("units")
    if not isinstance(findings, (list, tuple)) or not isinstance(units, (list, tuple)):
        raise ValidationError(
            "NCA report units or findings are malformed.", code="NCA_RESULT_SCHEMA_INVALID"
        )

    # Human labels may change language; every backticked identity remains canonical machine evidence.
    lines = [
        f"# {text('report.nca.title')}",
        "",
        f"## {text('report.nca.authority')}",
        "",
        f"- Job: `{provenance.get('job_id', 'NOT RECORDED')}`",
        f"- Run: `{provenance.get('run_id', 'NOT RECORDED')}`",
        f"- WIP: `{wip.get('identity', 'NOT RECORDED')}` (`{wip.get('sha256', 'NOT RECORDED')}`)",
        f"- {text('report.nca.style_profile')}: `{style.get('selector', 'NOT RECORDED')}` (`{style.get('sha256', 'NOT RECORDED')}`)",
        f"- {text('report.nca.reference_package')}: `{reference.get('package_id', 'NOT RECORDED')}` (`{reference.get('sha256', 'NOT RECORDED')}`)",
        "",
        f"## {text('report.nca.checks')}",
        "",
    ]
    lines.extend(
        f"- `{name}`: `{'ON' if enabled is True else 'OFF'}`"
        for name, enabled in checks.items()
    )
    lines.extend(
        [
            "",
            f"## {text('report.nca.model_identity')}",
            "",
        ]
    )
    identities = _model_identities(document.get("model_receipts"))
    assessed_units = any(
        isinstance(unit, Mapping)
        and isinstance(unit.get("extraction"), Mapping)
        and unit["extraction"].get("status") != "UNSUPPORTED"
        for unit in units
    )
    if assessed_units and not identities:
        raise ValidationError(
            "Assessed NCA units require actual model identity.",
            code="NCA_RESULT_RECEIPT_INVALID",
        )
    lines.extend(f"- `{identity}`" for identity in identities)
    if not identities:
        lines.append("- `NOT RECORDED`")
    lines.extend(
        [
            "",
            f"## {text('report.nca.summary')}",
            "",
            f"- {text('report.nca.units')}: `{summary.get('units', 0)}`",
            f"- {text('report.nca.expressions')}: `{summary.get('expressions', 0)}`",
            f"- {text('report.nca.target_expressions')}: `{summary.get('target_expressions', 0)}`",
            f"- {text('report.nca.ol_expressions_checked')}: `{summary.get('ol_expressions_checked', 0)}`",
            f"- {text('report.nca.passes')}: `{summary.get('passes', 0)}`",
            f"- {text('report.nca.unit_conversions')}: `{summary.get('unit_conversions', 0)}`",
            f"- {text('report.nca.value_differences')}: `{summary.get('value_differences', 0)}`",
            f"- {text('report.nca.missing_numbers')}: `{summary.get('missing_numbers', 0)}`",
            f"- {text('report.nca.added_numbers')}: `{summary.get('added_numbers', 0)}`",
            f"- {text('report.nca.known_variants')}: `{summary.get('known_variants', 0)}`",
            f"- {text('report.nca.style_findings')}: `{summary.get('style_findings', 0)}`",
            f"- {text('report.nca.findings')}: `{summary.get('findings', 0)}`",
            f"- {text('report.nca.insufficient_evidence')}: `{summary.get('insufficient_evidence', 0)}`",
            f"- {text('report.nca.reference_not_indexed')}: `{summary.get('reference_not_indexed', 0)}`",
            f"- {text('report.nca.not_assessed')}: `{summary.get('not_assessed', 0)}`",
            "",
            f"## {text('report.nca.coverage')}",
            "",
            f"- {text('report.nca.result')}: `{coverage.get('result', 'NOT RECORDED')}`",
            f"- {text('report.nca.coverage')}: `{coverage.get('coverage', 'NOT RECORDED')}`",
            f"- {text('report.nca.confidence_basis')}: `{coverage.get('confidence_basis', 'NOT RECORDED')}`",
            f"- {text('report.nca.restrictions')}: {_joined(coverage.get('restrictions'))}",
            "",
            f"## {text('report.nca.units')}",
            "",
        ]
    )
    for raw_unit in units:
        unit = _mapping(raw_unit, "unit")
        projection = _mapping(unit.get("projection"), "unit projection")
        reading = _mapping(unit.get("reading"), "unit reading")
        footnote = _mapping(unit.get("footnote"), "unit footnote")
        source_evidence = _mapping(unit.get("source_evidence"), "unit source evidence")
        source_context = _mapping(source_evidence.get("context"), "unit source context")
        lines.extend(
            [
                f"### `{unit.get('unit_id', 'NOT RECORDED')}`",
                "",
                f"- {text('report.nca.target_reference')}: {_joined(projection.get('target_references'))}",
                f"- {text('report.nca.target_locator')}: {_locator(projection.get('source_locator'))}",
                f"- {text('report.nca.western_reference')}: {_joined(projection.get('western_references'))}",
                f"- {text('report.nca.ol_reference')}: {_joined(projection.get('ol_references'))}",
                f"- {text('report.nca.selected_reading')}: `{reading.get('selected', 'NOT RECORDED')}`",
                f"- {text('report.nca.source_ids')}: {_joined(reading.get('source_ids'))}",
                f"- {text('report.nca.source_expressions')}: {_expressions(source_evidence.get('expressions'))}",
                f"- {text('report.nca.variant_class')}: `{source_context.get('variant_class') or 'NOT RECORDED'}`",
                f"- {text('report.nca.scholarship_status')}: `{source_context.get('scholarship_status') or 'NOT RECORDED'}`",
                f"- {text('report.nca.footnote_action')}: `{footnote.get('action', 'NOT RECORDED')}`",
                f"- {text('report.nca.footnote_status')}: `{footnote.get('status', 'NOT RECORDED')}`",
                f"- {text('report.nca.outcome')}: `{unit.get('final_outcome', 'NOT RECORDED')}`",
                "",
            ]
        )
    lines.extend([f"## {text('report.nca.findings')}", ""])
    if not findings:
        if coverage.get("result") == "NO_FINDINGS":
            lines.append(text("report.nca.no_findings"))
        else:
            lines.append(f"`{coverage.get('result', 'NOT ASSESSED')}`")
    for raw_finding in findings:
        finding = _mapping(raw_finding, "finding")
        lines.extend(
            [
                f"### `{finding.get('finding_id', 'NOT RECORDED')}`",
                "",
                f"- {text('report.nca.code')}: `{finding.get('code', 'NOT RECORDED')}`",
                f"- {text('report.nca.category')}: `{finding.get('category', 'NOT RECORDED')}`",
                f"- {text('report.nca.target_reference')}: `{finding.get('target_reference') or 'NOT RECORDED'}`",
                f"- {text('report.nca.western_reference')}: {_joined(finding.get('western_references'))}",
                f"- {text('report.nca.ol_reference')}: `{finding.get('ol_reference') or 'NOT RECORDED'}`",
                f"- {text('report.nca.selected_reading')}: `{finding.get('selected_reading') or 'NOT RECORDED'}`",
                f"- {text('report.nca.source_ids')}: {_joined(finding.get('source_ids'))}",
                f"- {text('report.nca.footnote_action')}: `{finding.get('footnote_action') or 'NOT RECORDED'}`",
                f"- {text('report.nca.footnote_status')}: `{finding.get('footnote_status') or 'NOT RECORDED'}`",
                f"- {text('report.nca.suggested_note')}: {finding.get('suggested_note') or 'NOT RECORDED'}",
                "",
            ]
        )
    lines.extend(
        [
            f"## {text('report.nca.limitations')}",
            "",
            text("report.nca.capability_limitation"),
            "",
            "SQS: `NOT_APPLIED`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
