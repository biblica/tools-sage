"""Render canonical NCA machine results as bounded Operator-facing Markdown."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
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
    "report.nca.findings": "Findings",
    "report.nca.no_findings": "No NCA findings were recorded.",
    "report.nca.target_reference": "Target reference",
    "report.nca.western_reference": "Western reference",
    "report.nca.code": "Code",
    "report.nca.category": "Category",
    "report.nca.severity": "Severity",
    "report.nca.outcome": "Outcome",
    "report.nca.restrictions": "Restrictions",
    "report.nca.model_identity": "Model identity",
    "report.nca.style_profile": "Style profile",
    "report.nca.reference_package": "Reference package",
    "report.nca.result": "Result",
    "report.nca.confidence_basis": "Confidence basis",
    "report.nca.groups": "Groups",
    "report.nca.passes": "No issue",
    "report.nca.failures": "Variances",
    "report.nca.needs_review": "Consistency checks",
    "report.nca.not_assessed": "Not checked",
    "report.nca.noteworthy_notes": "Noteworthy notes",
    "report.nca.extraction_status": "Extraction status",
    "report.nca.wip_values": "WIP values",
    "report.nca.expected_values": "Expected values",
    "report.nca.comparison_outcome": "Comparison outcome",
    "report.nca.comparison_mode": "Comparison mode",
    "report.nca.comparison_authority": "Authority",
    "report.nca.review_context": "Review context",
    "report.nca.classification": "Classification",
    "report.nca.scholarship_status": "Scholarship status",
    "report.nca.manuscript_evidence": "Manuscript evidence",
    "report.nca.ol_values": "OL values",
}
_ENGLISH.update({
    'report.nca.chapters': 'WIP chapters',
    'report.nca.unlocated': 'Unlocated WIP coverage',
    'report.nca.cross_reference': 'See primary evidence',
    'report.nca.parent_group': 'Protected parent group',
    'report.nca.planned_inputs': 'Planned extraction inputs',
    'report.nca.planned_extraction_calls': 'Planned extraction calls (initial batches)',
    'report.nca.executed_calls': 'Executed calls',
    'report.nca.reused_checkpoints': 'Reused checkpoints',
    'report.nca.blocked_inputs': 'Blocked extraction inputs',
    'report.nca.missing_owners': 'Groups without extraction',
    'report.nca.requested_scope': 'Requested scope',
    'report.nca.extraction_complete': 'Complete extractions',
    'report.nca.extraction_partial': 'Partial extractions',
    'report.nca.extraction_unsupported': 'Unsupported extractions',
    'report.nca.planning_notice': 'Planning estimates describe initial extraction batches, not measured time, cost or model qualification. Semantic calls and retries depend on evidence.',
    'report.nca.preflight': 'Scoped preflight',
    'report.nca.reference_expectations': 'Reference expectations (Western)',
    'report.nca.protected_groups': 'Protected groups',
    'report.nca.mandatory_profile': 'Number Style Profile (optional)',
    'report.nca.input_language': 'Input language and script',
    'report.nca.failed_calls': 'Failed calls',
    'report.nca.no_stylesheet': 'No stylesheet selected. Checks against approved rules are not assessed; numeric accuracy and footnote review remain independent.',
    'report.nca.translator_note_heading': 'Note for translator (copy below)',
    'report.nca.passes_not_listed': 'counted here, not listed below',
    'report.nca.translator_note_normalized':
        '{ref}: Check consistency: the translation has {wip}; the number index lists {expected}. The index '
        'does not read every number-like word in the original-language text here as a number{detail}. '
        'Original-language text: "{ol_text}". Reference translation (BSB): "{bsb_text}". Also see the NIV ({niv}).',
})
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


def _model_identities(value: object) -> tuple[str, ...]:
    """Collect exact provider/model identities from actual EXTRACTION phase receipts."""
    if not isinstance(value, Mapping):
        return ()
    identities: list[str] = []
    for row in value.get("EXTRACTION", ()):
        if not isinstance(row, Mapping):
            continue
        provider, model = row.get("provider"), row.get("model")
        if isinstance(provider, str) and provider and isinstance(model, str) and model:
            identity = f"EXTRACTION: {provider}/{model}"
            if identity not in identities:
                identities.append(identity)
    return tuple(identities)


def chapter_sections(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    """Assign each canonical group and finding once using only proven WIP coordinates."""
    from sage.references import BOOK_ORDER
    import re

    groups = document.get('groups', ())
    findings = document.get('findings', ())
    sections: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    owners = {}
    by_owner: dict[str, list[str]] = {}
    seen_findings = set()
    for finding in findings:
        identity = finding['finding_id']
        if identity in seen_findings:
            raise ValidationError('Duplicate canonical finding', code='NCA_RESULT_FINDING_INVALID')
        seen_findings.add(identity)
        by_owner.setdefault(finding['work_unit_id'], []).append(identity)

    def coordinate(label):
        """Read a canonical WIP coordinate without interpreting Western or OL labels."""
        match = re.fullmatch(r'([A-Z0-9]{3}) (\d+):(\d+)', label)
        if match is None:
            raise ValidationError('Invalid WIP coordinate', code='NCA_RESULT_REFERENCE_INVALID')
        book, chapter, verse = match.groups()
        return BOOK_ORDER.get(book, 999), book, int(chapter), int(verse)

    ordered = sorted(groups, key=lambda group: (
        min((coordinate(ref) for ref in group['target_references']), default=(1000, '', 0, 0)),
        group['unit_id']))
    for group in ordered:
        identity = group['unit_id']
        if identity in owners:
            raise ValidationError('Duplicate canonical parent', code='NCA_RESULT_COVERAGE_INVALID')
        refs = sorted(group['target_references'], key=coordinate)
        chapters = list(dict.fromkeys((coordinate(ref)[1], coordinate(ref)[2]) for ref in refs)) or [(None, None)]
        primary = chapters[0]
        owners[identity] = primary
        for key in chapters:
            section = sections.setdefault(key, {'book': key[0], 'chapter': key[1],
                'group_ids': [], 'finding_ids': [], 'cross_references': [], 'target_references': []})
            section['target_references'].extend(ref for ref in refs
                if (coordinate(ref)[1], coordinate(ref)[2]) == key and ref not in section['target_references'])
            if key == primary:
                section['group_ids'].append(identity)
                section['finding_ids'].extend(by_owner.get(identity, ()))
            else:
                section['cross_references'].append({'group_id': identity,
                    'book': primary[0], 'chapter': primary[1],
                    'finding_ids': tuple(by_owner.get(identity, ()))})
    if set(by_owner) - set(owners):
        raise ValidationError('Finding has no canonical parent', code='NCA_RESULT_FINDING_INVALID')
    return tuple({key: tuple(value) if isinstance(value, list) else value for key, value in sections[identity].items()}
        for identity in sorted(sections, key=lambda key: (BOOK_ORDER.get(key[0], 1000), key[0] or '', key[1] or 0)))


def _anchor(identity: str, kind: str) -> str:
    """Generate a safe stable Markdown destination without changing canonical identities."""
    from hashlib import sha256
    return 'nca-' + kind + '-' + sha256(identity.encode('utf-8')).hexdigest()[:20]


def _exact(value: object) -> str:
    """Quote exact structured evidence without letting source text become report markup."""
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True).replace('`', '\\u0060').replace('<', '\\u003c')


def _optimized_metrics(document, text) -> list[str]:
    """Expose sealed planning and observed work separately from the summary counters."""
    metrics = document.get('metrics', {})
    planning = metrics.get('planning', {})
    coverage = document['coverage']
    values = {
        'planned_extraction_calls': planning.get('planned_extraction_calls', 'NOT RECORDED'),
        'planned_inputs': len(planning['input_ids']) if 'input_ids' in planning else 'NOT RECORDED',
        'executed_calls': metrics.get('provider_calls', 'NOT RECORDED'),
        'reused_checkpoints': metrics.get('checkpoint_reuse', 'NOT RECORDED'),
        'failed_calls': metrics.get('failed_calls', 'NOT RECORDED'),
    }
    lines = [f"- {text('report.nca.' + key)}: `{value}`" for key, value in values.items()]
    for key, value in (('blocked_inputs', planning.get('blocked')), ('missing_owners', planning.get('missing_owner_ids')),
                       ('requested_scope', coverage.get('requested_scope'))):
        lines.append(f"- {text('report.nca.' + key)}: `{_exact(value)}`")
    return lines + ['', text('report.nca.planning_notice'), '']


def _group_lines(group, text) -> list[str]:
    """Render one indexed group's extraction, local comparison outcome, and advisory notes."""
    extraction = group['extraction']
    comparison = group['comparison']
    lines = [f'<a id="{_anchor(group["unit_id"], "group")}"></a>', f"### `{group['unit_id']}`", '',
        f"- {text('report.nca.target_reference')}: {_joined(group['target_references'])}",
        f"- {text('report.nca.western_reference')}: {_joined(group['western_references'])}",
        f"- {text('report.nca.extraction_status')}: `{extraction['status']}`",
        f"- {text('report.nca.wip_values')}: {_joined(extraction['values'])}",
        f"- {text('report.nca.comparison_outcome')}: `{comparison['outcome']}`",
        f"- {text('report.nca.comparison_mode')}: `{comparison['mode']}`",
        f"- {text('report.nca.comparison_authority')}: `{comparison['authority']}`",
        f"- {text('report.nca.expected_values')}: {_joined(comparison['expected_values'])}",
        f"- {text('report.nca.limitations')}: {_joined(group['limitations'])}"]
    if comparison['review_context']:
        lines.append(f"- {text('report.nca.review_context')}: `{_exact(comparison['review_context'])}`")
    for note in group['notes']:
        lines.extend(['', f"- {text('report.nca.classification')}: `{note.get('classification') or 'NOT RECORDED'}`",
            f"- {text('report.nca.scholarship_status')}: `{note.get('scholarship_status') or 'NOT RECORDED'}`",
            f"- {text('report.nca.manuscript_evidence')}: `{note.get('manuscript_evidence') or 'NOT RECORDED'}`",
            f"- {text('report.nca.ol_values')}: `{note.get('ol_values') or 'NOT RECORDED'}`"])
    lines.append('')
    return lines


def _listed(group, finding_ids) -> bool:
    """Whether one group belongs in the Operator report: PASS groups are counted, not listed.

    A PASS group is still listed when it carries a finding or a noteworthy advisory note,
    since those are evidence the Operator must act on or pass along.
    """
    return (group['comparison']['outcome'] != 'PASS' or bool(group['notes'])
            or bool(finding_ids))


def _chapter_lines(document, text) -> list[str]:
    """Render navigation links without copying canonical evidence or findings."""
    groups = {group['unit_id']: group for group in document['groups']}
    findings = {finding['finding_id']: finding for finding in document['findings']}
    owned: dict[str, list[str]] = {}
    for finding in document['findings']:
        owned.setdefault(finding['work_unit_id'], []).append(finding['finding_id'])
    lines = []
    for section in chapter_sections(document):
        group_ids = [identity for identity in section['group_ids'] if _listed(groups[identity], owned.get(identity))]
        cross_references = [cross for cross in section['cross_references']
                            if _listed(groups[cross['group_id']], cross['finding_ids'])]
        if not (group_ids or section['finding_ids'] or cross_references):
            continue
        title = f"{section['book']} {section['chapter']}" if section['book'] else text('report.nca.unlocated')
        lines.extend([f'## {title}', ''])
        for group_id in group_ids:
            lines.extend(_group_lines(groups[group_id], text))
        for finding_id in section['finding_ids']:
            finding = findings[finding_id]
            owner = finding['work_unit_id']
            refs = groups[owner]['target_references']
            lines.extend([f'<a id="{_anchor(finding_id, "finding")}"></a>', *_finding_lines(finding, text),
                f"- {text('report.nca.parent_group')}: [{owner}](#{_anchor(owner, 'group')})",
                f"- WIP: {_joined(refs)}", ''])
            note = _translator_note(finding, groups[owner], text)
            if note is not None:
                lines.extend(['', f"**{text('report.nca.translator_note_heading')}:**", '', f'> {note}', ''])
        for cross in cross_references:
            owner = cross['group_id']
            links = [f"[{owner}](#{_anchor(owner, 'group')})"]
            links.extend(f"[{identity}](#{_anchor(identity, 'finding')})" for identity in cross['finding_ids'])
            lines.extend([f"- {text('report.nca.cross_reference')}: " + ', '.join(links), ''])
    if not findings:
        lines.append(text('report.nca.no_findings') if document['coverage']['result'] == 'NO_FINDINGS'
                     else f"`{document['coverage']['result']}`")
    return lines


def _finding_lines(finding, text) -> list[str]:
    """Render canonical finding fields without altering stored coordinates or identities."""
    return [
        f"### `{finding.get('finding_id', 'NOT RECORDED')}`",
        "",
        f"- {text('report.nca.code')}: `{finding.get('code', 'NOT RECORDED')}`",
        f"- {text('report.nca.category')}: `{finding.get('category', 'NOT RECORDED')}`",
        f"- {text('report.nca.severity')}: `{finding.get('severity', 'NOT RECORDED')}`",
        f"- {text('report.nca.target_reference')}: {_joined(finding.get('target_references'))}",
        f"- {text('report.nca.western_reference')}: {_joined(finding.get('western_references'))}",
        f"- {text('report.nca.wip_values')}: {_joined(finding.get('wip_values'))}",
        f"- {text('report.nca.expected_values')}: {_joined(finding.get('expected_values'))}",
        f"- {finding.get('message', 'NOT RECORDED')}",
        "",
    ]


_NORMALIZED_REVIEW_KINDS = frozenset({'OL_NORMALIZED_UNDOCUMENTED', 'OL_NORMALIZATION_DIFFERENCE'})


def _normalization_detail(review_context: Mapping[str, object]) -> str:
    """Name the documented OL expressions the index normalized; blank when none are recorded."""
    items = [f'"{item["SOURCE_EXPRESSION"]}": {item["REASON"]}'
             for item in review_context.get('normalizations') or ()
             if isinstance(item, Mapping) and item.get('SOURCE_EXPRESSION') and item.get('REASON')]
    return f" ({'; '.join(items)})" if items else ''


def _translator_note(finding: Mapping[str, object], group: Mapping[str, object], text) -> str | None:
    """Render one copy-paste-ready plain-language note for a FAIL or NEEDS_REVIEW finding.

    Deliberately outside the technical finding block above: no codes, no backticks, no
    internal field names -- an Operator must be able to select and paste this directly
    to a translator. Uses the WIP-side target reference (what the translator recognizes
    in their own project), not the internal Western/canonical reference.
    """
    if finding.get('code') not in {'NCA_NUMBER_FAIL', 'NCA_NUMBER_NEEDS_REVIEW'}:
        return None
    # The same per-kind action text as the action report (one wording per finding kind).
    return _finding_text(finding, group, text)[1]


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
    groups = document.get("groups")
    if not isinstance(findings, (list, tuple)) or not isinstance(groups, (list, tuple)):
        raise ValidationError(
            "NCA report groups or findings are malformed.", code="NCA_RESULT_SCHEMA_INVALID"
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
        (f"- {text('report.nca.style_profile')}: `{style['selector']}` (`{style.get('sha256', 'NOT RECORDED')}`)"
         if style.get('selector') else f"- {text('report.nca.no_stylesheet')}"),
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
    assessed_groups = any(
        isinstance(group, Mapping)
        and isinstance(group.get("extraction"), Mapping)
        and group["extraction"].get("status") in {"COMPLETE", "PARTIAL"}  # a model read it
        for group in groups
    )
    if assessed_groups and not identities:
        raise ValidationError(
            "Assessed NCA groups require actual model identity.",
            code="NCA_RESULT_RECEIPT_INVALID",
        )
    lines.extend(f"- `{identity}`" for identity in identities)
    if not identities:
        lines.append("- `NOT RECORDED`")
    closing = (
        [
            f"## {text('report.nca.summary')}",
            "",
            f"- {text('report.nca.groups')}: `{summary.get('groups', 0)}`",
            f"- {text('report.nca.passes')}: `{summary.get('passes', 0)}` ({text('report.nca.passes_not_listed')})",
            f"- {text('report.nca.failures')}: `{summary.get('failures', 0)}`",
            f"- {text('report.nca.needs_review')}: `{summary.get('needs_review', 0)}`",
            f"- {text('report.nca.not_assessed')}: `{summary.get('not_assessed', 0)}`",
            f"- {text('report.nca.noteworthy_notes')}: `{summary.get('noteworthy_notes', 0)}`",
            f"- {text('report.nca.extraction_complete')}: `{summary.get('extraction_complete', 0)}`",
            f"- {text('report.nca.extraction_partial')}: `{summary.get('extraction_partial', 0)}`",
            f"- {text('report.nca.extraction_unsupported')}: `{summary.get('extraction_unsupported', 0)}`",
            f"- {text('report.nca.findings')}: `{summary.get('findings', 0)}`",
            "",
            f"## {text('report.nca.coverage')}",
            "",
            f"- {text('report.nca.result')}: `{coverage.get('result', 'NOT RECORDED')}`",
            f"- {text('report.nca.coverage')}: `{coverage.get('coverage', 'NOT RECORDED')}`",
            f"- {text('report.nca.confidence_basis')}: `{coverage.get('confidence_basis', 'NOT RECORDED')}`",
            f"- {text('report.nca.restrictions')}: {_joined(coverage.get('restrictions'))}",
            "",
        ]
    )
    lines.extend(["", f"## {text('report.nca.chapters')}", ""])
    lines.extend(_optimized_metrics(document, text))
    lines.extend(_chapter_lines(document, text))
    lines.extend(closing)
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


# ---------- Operator action reports (RTC/STC template) ----------
#
# render_nca_report above is the full technical projection; it is written to the Run's
# diagnostics folder. Operators get per-chapter action reports in the same template,
# paths and Job summary index RTC and STC use (act_outputs.render_action_report).

_ACTION_TEXT = {
    "report.nca_action_report": "NCA Action Report",
    "report.nca.authority_label.OL": "{family} original-language text",
    "report.nca.authority_label.NIV": "NIV (secondary authority)",
    "report.nca.authority_label.MIXED": "original-language and NIV readings",
    "report.nca.authority_label.NONE": "number index",
    "report.nca.no_numbers": "no numbers",
    "report.nca.coverage_line": "{checked} verse(s) checked; {not_indexed} without numbers",
    "report.nca.closing_summary": "Summary: no issue and not checked",
    "report.nca.coverage_status": "Coverage",
    "report.nca.no_issue": "No issue",
    "report.nca.without_numbers": "No numbers in the source or the index",
    "report.nca.not_checked": "Not checked",
    "report.nca.versification": "Versification differences",
    "report.nca.text_notes": "Text-critical notes",
    "report.nca.evidence_heading": "{label} evidence",
    "report.nca.closing_limitation": "Limitations",
    "report.nca.issue.VALUE_DIFFERENCE": "The translation has {wip}; the {authority} has {expected}.{unit_note}",
    "report.nca.issue.WRONG_ASSOCIATION":
        "The numbers match the source, but they are attached to different items: {wip_pairs} in the "
        "translation, {source_pairs} in the source.",
    "report.nca.action.WRONG_ASSOCIATION":
        "{ref}: Attach each number to its item as in the source: {source_pairs}.",
    "report.nca.issue.MALFORMED_NUMERAL": "The numeral(s) {numerals} cannot be read as a well-formed number.",
    "report.nca.action.MALFORMED_NUMERAL":
        "{ref}: Correct the numeral(s) {numerals} (digit grouping or decimal mark); the source has {expected}.",
    "report.nca.issue.NUMBER_NOT_IN_SOURCE":
        "The translation has the numeral(s) {numerals}, but the source has no number in this verse.",
    "report.nca.action.NUMBER_NOT_IN_SOURCE":
        "{ref}: Remove or correct {numerals}: the source has no number in this verse (a typing slip or a number from another verse).",
    "report.nca.issue.APPARATUS_VARIANT":
        "The translation has {wip}; the {authority} has {expected}, and the textual apparatus records a number "
        "variant here.",
    "report.nca.action.APPARATUS_VARIANT":
        "{ref}: Check consistency: the translation follows a variant reading ({wip}); the original-language text has {expected}. Footnote the reading followed.",
    "report.nca.issue.NUMBERS_DIFFER":
        "The translation has {wip}; the {authority} has {expected}.{omitted_part}{added_part}",
    "report.nca.action.NUMBERS_DIFFER":
        "{ref}: Check consistency: the numbers differ from the source ({wip} against {expected}).",
    "report.nca.omitted_part": " Not in the translation: {omitted}.",
    "report.nca.added_part": " Not in the source: {added}.",
    "report.nca.unit_note": " Units differ or are not determined: {unit_pairs}.",
    "report.nca.unit_pair": "source {source_value} {source_unit}; translation {wip_value} {wip_unit}",
    "report.nca.unit_pair.NOT_DETERMINED": " (unit not determined)",
    "report.nca.apparatus_heading": "Apparatus evidence",
    "report.nca.attribution": "Sources and attribution",
    "report.nca.no_apparatus": "No apparatus entry; registered by SAGE guidance only.",
    "report.nca.footnote_basis": "Suggested footnote basis (the translation has no footnote here)",
    "report.nca.text_critical": "Text-critical variants",
    "report.nca.text_critical_intro":
        "The textual apparatus records a number variant at these verses; NCA records which reading the "
        "translation follows and whether it has a footnote. They are not errors.",
    "report.nca.order_notes": "Notes (no action needed)",
    "report.nca.order_note":
        "{ref}: the numbers appear in a different order than the source; each is attached to the right item "
        "({pairs}).",
    "report.nca.action.VALUE_DIFFERENCE":
        "{ref}: Correct the numbers: the translation has {wip}; the original-language text has {expected}.{unit_note}",
    "report.nca.source_reads": 'For reference, the source reads: "{source}"',
    "report.nca.bsb_reads": 'For reference, the BSB reads: "{source}" (also see the NIV: {niv})',
    "report.nca.also_see_niv": "Also see — NIV (other reference)",
    "report.nca.issue.ORDER_DIFFERENCE":
        "The same numbers appear in a different order: translation {wip}, source {expected}.",
    "report.nca.action.ORDER_DIFFERENCE":
        "{ref}: Check consistency: the numbers {wip} appear in a different order than the source ({expected}); each number must stay attached to its item.",
    "report.nca.issue.NIV_ONLY_AUTHORITY":
        "The original language has no explicit number here. The NIV reads {expected}; the translation has {wip}.",
    "report.nca.action.NIV_ONLY_AUTHORITY":
        "{ref}: Check consistency: the NIV has {expected} where the original language has no explicit number; the translation has {wip}.",
    "report.nca.issue.MIXED_AUTHORITY":
        "Across these bridged verses the expected values ({expected}) combine original-language and "
        "NIV-only readings; the translation has {wip}.",
    "report.nca.action.MIXED_AUTHORITY":
        "{ref}: Check consistency: the translation has {wip}; the reference readings across these verses are {expected}, part of them from the NIV only.",
    "report.nca.issue.ATTESTED_VARIANT_READING":
        "The translation follows an attested alternate reading at {variant} ({alternate}); "
        "scholarship status: {status}.",
    "report.nca.action.ATTESTED_VARIANT_READING":
        "{ref}: This verse follows an alternate manuscript reading ({alternate}), which is acceptable. "
        "A footnote is {footnote}. Suggested note: {note}",
    "report.nca.issue.OL_NORMALIZED_UNDOCUMENTED":
        "The index normalized this verse's original-language numbers without a word-level record; "
        "the translation has {wip}, the index lists {expected}.",
    "report.nca.issue.OL_NORMALIZATION_DIFFERENCE":
        "The translation matches the original-language words before the index's documented "
        "normalization{detail}; the index lists {expected}.",
    "report.nca.issue.MATCHES_SECONDARY_AUTHORITY":
        "The translation matches the NIV ({niv}) but not the original-language reading ({expected}).",
    "report.nca.action.MATCHES_SECONDARY_AUTHORITY":
        "{ref}: Check consistency: the translation follows the NIV's numbers ({niv}); the original language reads {expected}.",
    "report.nca.issue.CONVENTION_EDGE_CASE":
        "The only difference is the extra value(s) {extra}, tagged as {kinds} by extraction.",
    "report.nca.action.CONVENTION_EDGE_CASE":
        "{ref}: Check consistency: {extra} is an ordinal or descriptive number word (such as \"second\" or \"twice\") that the reference does not count.",
    "report.nca.issue.NO_INDEXED_VALUES":
        "The index lists this coordinate without numeric values, but the translation has {wip}.",
    "report.nca.action.NO_INDEXED_VALUES":
        "{ref}: Check consistency: the translation has {wip}; the number index has no numbers for this verse.",
    "report.nca.issue.PROVISIONAL_INDEX":
        "The translation has {wip}; the rebuilt index has {expected}, which is not yet reviewed.",
    "report.nca.action.PROVISIONAL_INDEX":
        "{ref}: Check consistency: the translation has {wip}; the rebuilt index has {expected}, not yet reviewed.",
    "report.nca.footnote.REQUIRE": "required",
    "report.nca.footnote.RECOMMEND": "recommended",
    "report.nca.footnote.NONE": "not required",
}
_ENGLISH.update(_ACTION_TEXT)
_NEW_TESTAMENT_START = "MAT"
# Operator-facing names for the stored codes; the codes stay unchanged in results and diagnostics.
_FAMILY_NAMES = {"HEB": "Hebrew", "GRK": "Greek"}
_RESULT_NAMES = {"BLOCKING": "Variance", "REVIEW": "Consistency check"}
_CATEGORY_NAMES = {"ACCURACY": "Accuracy", "CONSISTENCY": "Consistency"}
_COVERAGE_NAMES = {"COMPLETE": "complete", "PARTIAL": "partial"}
_REASON_NAMES = {
    "NOT_ASSESSED": "not compared",
    "REGISTERED_ABSENCE": "verse absent in this versification",
    "COVERED_BY_WIP_GROUP": "checked with a neighbouring verse",
    "UNMAPPED": "no mapping to the source numbering",
    "CONTENT_UNREADABLE_BOOK": "book could not be read",
    "BOOK_LEFT_OUT": "book left out of the WIP snapshot (defect in the book file)",
}


def _human_reason(codes: object) -> str:
    """Plain words for one or more comma-joined reason codes ("MARKUP_ERROR" -> "markup error")."""
    parts = [part.strip() for part in str(codes or "").split(",") if part.strip()]
    return "; ".join(_REASON_NAMES.get(part) or part.removeprefix("NCA_").replace("_", " ").lower()
                     for part in parts) or _REASON_NAMES["NOT_ASSESSED"]


def _ol_family(book: str) -> str:
    """Return the routed original-language family for one canonical book code."""
    from sage.references import BOOK_ORDER
    return "GRK" if BOOK_ORDER.get(book, 0) >= BOOK_ORDER[_NEW_TESTAMENT_START] else "HEB"


def _list(values: object, text) -> str:
    """Render a value list for prose, naming an empty list explicitly."""
    items = [str(value) for value in values or ()]
    return ", ".join(items) if items else text("report.nca.no_numbers")


def _coordinate(label: str) -> tuple[int, str, int, int]:
    """Sort key for one canonical 'BOOK C:V' label."""
    from sage.references import BOOK_ORDER
    book, _, rest = label.partition(" ")
    chapter, _, verse = rest.partition(":")
    return BOOK_ORDER.get(book, 999), book, int(chapter or 0), int(verse or 0)


def _primary_chapter(group: Mapping[str, object]) -> tuple[str, int] | None:
    """The chapter a group is reported under: its first WIP coordinate, else its Western one."""
    refs = list(group.get("target_references") or ()) or list(group.get("western_references") or ())
    if not refs:
        return None
    _order, book, chapter, _verse = min(_coordinate(ref) for ref in refs)
    return book, chapter


def _finding_text(finding: Mapping[str, object], group: Mapping[str, object], text) -> tuple[str, str]:
    """Return (issue, proposed action) prose for one finding; the action is the translator note."""
    comparison = group.get("comparison") or {}
    context = comparison.get("review_context") or {}
    kind = str(finding.get("kind") or context.get("kind") or "VALUE_DIFFERENCE")
    refs = list(finding.get("target_references") or finding.get("western_references") or ())
    ref = ", ".join(refs)
    family = _ol_family(_coordinate(refs[0])[1]) if refs else "HEB"
    authority = text("report.nca.authority_label." + str(comparison.get("authority") or "OL")).format(
        family=_FAMILY_NAMES.get(family, family))
    wip, expected = _list(finding.get("wip_values"), text), _list(finding.get("expected_values"), text)
    values = {
        "ref": ref, "wip": wip, "expected": expected, "authority": authority,
        "ol": _list(context.get("ol_values"), text), "niv": _list(context.get("niv_values"), text),
    }
    if kind in _NORMALIZED_REVIEW_KINDS:
        issue = text("report.nca.issue." + kind).format(detail=_normalization_detail(context), **values)
        action = text("report.nca.translator_note_normalized").format(
            ref=ref, wip=wip, expected=expected, detail=_normalization_detail(context),
            ol_text=context.get("ol_text") or "NOT RECORDED", bsb_text=context.get("bsb_text") or "NOT RECORDED",
            niv=values["niv"])
        return issue, action
    if kind == "ATTESTED_VARIANT_READING":
        guidance = context.get("variant_guidance") or {}
        footnote = str(guidance.get("footnote_if_target_follows_alt") or "NONE").upper()
        values.update(
            variant=context.get("variant_reference") or ref,
            alternate=_list(context.get("alternate_values"), text),
            status=guidance.get("scholarship_status") or "NOT RECORDED",
            footnote=text("report.nca.footnote." + (footnote if footnote in {"REQUIRE", "RECOMMEND"} else "NONE")),
            note=guidance.get("suggested_note") or guidance.get("niv_footnote") or "NOT RECORDED",
        )
    if kind == "WRONG_ASSOCIATION":
        pairs = list(context.get("pairings") or ())
        values.update(
            wip_pairs=", ".join(f"{p.get('wip_counts') or '?'} {p.get('wip_value')}" for p in pairs) or wip,
            source_pairs=", ".join(f"{item.get('referent') or '?'} {item.get('value')}"
                                   for item in context.get("source_items") or ()) or expected)
    if kind == "NUMBERS_DIFFER":
        omitted, added = context.get("omitted") or (), context.get("added") or ()
        values.update(
            omitted_part=text("report.nca.omitted_part").format(omitted=_list(omitted, text)) if omitted else "",
            added_part=text("report.nca.added_part").format(added=_list(added, text)) if added else "")
    values["unit_note"] = ""
    if kind == "VALUE_DIFFERENCE" and context.get("unit_state") not in (None, "SAME"):
        values["unit_note"] = text("report.nca.unit_note").format(unit_pairs="; ".join(
            text("report.nca.unit_pair").format(**{"source_unit": "", "wip_unit": "", **item}).strip()
            + (text("report.nca.unit_pair.NOT_DETERMINED") if item.get("state") == "NOT_DETERMINED" else "")
            for item in context.get("units") or () if isinstance(item, Mapping)) or wip)
    if kind in {"MALFORMED_NUMERAL", "NUMBER_NOT_IN_SOURCE"}:
        values.update(numerals=", ".join(str(item) for item in context.get("numerals") or ()) or wip)
    if kind == "CONVENTION_EDGE_CASE":
        from collections import Counter
        wip_values = list(finding.get("wip_values") or ())
        extra = Counter(wip_values) - Counter(finding.get("expected_values") or ())
        kinds = list(context.get("wip_kinds") or ())
        values.update(extra=_list(list(extra.elements()), text),
                      kinds=", ".join(sorted({kinds[i] for i, v in enumerate(wip_values) if v in extra and i < len(kinds)})) or "edge case")
    key = kind if ("report.nca.issue." + kind) in _ENGLISH else "VALUE_DIFFERENCE"
    action = text("report.nca.action." + key).format(**values)
    if key == "ORDER_DIFFERENCE" and context.get("authority_text"):
        reads = "report.nca.bsb_reads" if context.get("authority_text_source") == "BSB" else "report.nca.source_reads"
        action += " " + text(reads).format(source=context["authority_text"], niv=values["niv"])
    return text("report.nca.issue." + key).format(**values), action


def _route(document: Mapping[str, object]) -> dict[str, object] | None:
    """The single EXTRACTION route the Run's receipts record, in the shared route shape."""
    receipts = [row for row in (document.get("model_receipts") or {}).get("EXTRACTION", ()) if isinstance(row, Mapping)]
    if not receipts:
        return None
    first = receipts[0]
    return {
        "skill_id": "nca-numbers",
        "provider": first.get("provider"),
        "model": first.get("model"),
        "model_id": first.get("model"),
        "reasoning_effort": first.get("reasoning_effort"),
        "routing_mode": first.get("routing_mode"),
        "qualification_status": first.get("qualification_status"),
        "route_id": first.get("route_id"),
    }


def _authority_lines(document: Mapping[str, object], *, family: str, snapshot_date: str) -> list[str]:
    """Shared ```text authority block (report_authority layout) for one NCA chapter report."""
    from .report_authority import _field
    provenance = document.get("provenance") or {}
    wip = provenance.get("wip") or {}
    package = provenance.get("reference_package") or {}
    style = provenance.get("style_profile") or {}
    policy = document.get("check_policy") or {}
    return [
        _field("Analysis", "NCA"),
        _field("Job", provenance.get("job_id", "NOT RECORDED")),
        _field("Run", provenance.get("run_id", "NOT RECORDED")),
        _field("WIP Project", wip.get("identity", "NOT RECORDED")),
        _field("WIP snapshot date", snapshot_date or "NOT RECORDED"),
        _field("WIP fingerprint", wip.get("sha256", "NOT RECORDED")),
        _field("Number reference package", package.get("package_id", "NOT RECORDED")),
        _field("Package fingerprint", package.get("sha256", "NOT RECORDED")),
        _field("Original-language authority", family),
        _field("Secondary authority", "NIV (guidance where OL has no explicit number)"),
        _field("Number Style Profile", style.get("selector") or "NONE"),
        _field("Comparison mode", policy.get("numeric_comparison_mode", "NOT RECORDED")),
    ]


def build_chapter_reports(
    document: Mapping[str, object],
    *,
    primary_language: str,
    secondary_language: str | None,
    snapshot_date: str = "",
) -> list[dict[str, object]]:
    """Split one canonical NCA result into per-chapter Operator report documents."""
    text = _localization_function(language=primary_language, localize=None) if primary_language in _CATALOG_LANGUAGES \
        else (lambda key: _ENGLISH[key])
    groups = [group for group in document.get("groups", ()) if isinstance(group, Mapping)]
    by_id = {group["unit_id"]: group for group in groups}
    wip_id = str(((document.get("provenance") or {}).get("wip") or {}).get("identity") or "WIP")
    route = _route(document)
    chapters: dict[tuple[str, int], dict[str, Any]] = {}
    for group in groups:
        key = _primary_chapter(group)
        if key is None:
            continue
        chapter = chapters.setdefault(key, {"groups": [], "findings": []})
        chapter["groups"].append(group)
    for finding in document.get("findings", ()):
        group = by_id.get(finding.get("work_unit_id"))
        key = _primary_chapter(group) if group else None
        if key is not None:
            chapters[key]["findings"].append(finding)
    reports = []
    for (book, chapter_number), chapter in sorted(chapters.items(), key=lambda item: _coordinate(f"{item[0][0]} {item[0][1]}:0")):
        family = _ol_family(book)
        outcomes = [str((group.get("comparison") or {}).get("outcome")) for group in chapter["groups"]]
        findings = []
        for finding in sorted(chapter["findings"], key=lambda row: (_coordinate((row.get("target_references") or ["ZZZ 0:0"])[0]), row["finding_id"])):
            group = by_id[finding["work_unit_id"]]
            issue, action = _finding_text(finding, group, text)
            context = (group.get("comparison") or {}).get("review_context") or {}
            findings.append({
                "finding_id": finding["finding_id"],
                "target_reference": ", ".join(finding.get("target_references") or ()),
                "western_reference": ", ".join(finding.get("western_references") or ()),
                "category": finding.get("category", "ACCURACY"),
                "action_level": finding.get("severity", "REVIEW"),
                "kind": finding.get("kind", "VALUE_DIFFERENCE"),
                "evidence_ids": ["WIP", f"ORIGINAL_LANGUAGE_{'GREEK' if family == 'GRK' else 'HEBREW'}", "BSB", "NIV"],
                "wip_values": list(finding.get("wip_values") or ()),
                "expected_values": list(finding.get("expected_values") or ()),
                "authority": (group.get("comparison") or {}).get("authority", "OL"),
                "issue": issue,
                "required_action": action,
                "evidence": {
                    "wip_text": str((group.get("evidence") or {}).get("wip_text") or ""),
                    "ol_text": str(context.get("ol_text") or ""),
                    "bsb_text": str(context.get("bsb_text") or ""),
                    "niv_values": [str(value) for value in context.get("niv_values") or ()],
                },
                "apparatus": list(context.get("apparatus") or ()),
                **({"execution_route": route} if route else {}),
            })
        advisories = [
            {"reference": ", ".join(group.get("target_references") or group.get("western_references") or ()),
             "code": ",".join(group.get("limitations") or ()) or "NOT_ASSESSED"}
            for group in chapter["groups"]
            if (group.get("comparison") or {}).get("outcome") == "NOT_ASSESSED"
        ]
        exceptions = [
            {"effect": "NOT_ASSESSED", "tool": "nca", "stage": "NCA", "severity": "WARNING", "attempts": 0,
             "work_unit": group.get("unit_id"),
             "code": ",".join(group.get("limitations") or ()) or "NOT_ASSESSED",
             "coordinates": list(group.get("target_references") or group.get("western_references") or ()),
             "message": "NCA could not compare these numbers, so none were checked."}
            for group in chapter["groups"]
            if (group.get("comparison") or {}).get("outcome") == "NOT_ASSESSED"
        ]
        versification = [
            {"reference": ", ".join(group.get("western_references") or ()),
             "code": ",".join(group.get("limitations") or ())}
            for group in chapter["groups"]
            if set(group.get("limitations") or ()) & {"REGISTERED_ABSENCE", "COVERED_BY_WIP_GROUP"}
        ]
        listed = {finding.get("work_unit_id") for finding in chapter["findings"]}
        no_issue = [", ".join(group.get("target_references") or group.get("western_references") or ())
                    for group in chapter["groups"]
                    if (group.get("comparison") or {}).get("outcome") == "PASS" and group.get("unit_id") not in listed]
        not_indexed = [", ".join(group.get("target_references") or group.get("western_references") or ())
                       for group in chapter["groups"] if (group.get("comparison") or {}).get("outcome") == "NOT_INDEXED"]
        notes = [dict(note, owner=", ".join(group.get("target_references") or group.get("western_references") or ()))
                 for group in chapter["groups"] for note in group.get("notes") or ()]
        report = {
            "workflow": "nca",
            "operation": "nca",
            "book": book,
            "chapter": chapter_number,
            "scope": f"{book} {chapter_number}",
            "narrative_language": {"tag": primary_language},
            "resource_bindings": {"WIP": wip_id, "REFERENCE": "NIV",
                                  f"ORIGINAL_LANGUAGE_{'GREEK' if family == 'GRK' else 'HEBREW'}": family},
            "coverage": {
                "status": "COMPLETE" if not advisories else "PARTIAL",
                "checked": sum(outcome not in {"NOT_INDEXED", "NOT_ASSESSED"} for outcome in outcomes),
                "not_indexed": outcomes.count("NOT_INDEXED"),
            },
            "authority_header": _authority_lines(document, family=family, snapshot_date=snapshot_date),
            "findings": findings,
            "no_issue": no_issue,
            "not_indexed": not_indexed,
            "advisories": advisories,
            "exceptions": exceptions,
            "versification_advisories": versification,
            "notes": notes,
        }
        if route:
            report["execution_route"] = route
        if secondary_language:
            report["language_authority"] = {"primary_language": primary_language, "secondary_language": secondary_language}
        reports.append(report)
    return reports


def render_nca_action_report(report: Mapping[str, object]) -> str:
    """Render one chapter's Operator action report in the shared RTC/STC template."""
    from .act_outputs import _language_display_name, _report_label, render_execution_section
    from .human_output import render_report_language_authority
    from .report_authority import authority_markdown

    primary = str((report.get("narrative_language") or {}).get("tag") or "en")
    authority = report.get("language_authority") or {}
    secondary = str(authority.get("secondary_language") or "") or None
    text = _localization_function(language=primary, localize=None) if primary in _CATALOG_LANGUAGES \
        else (lambda key: _ENGLISH[key])
    primary_name = _language_display_name(primary)
    secondary_name = _language_display_name(secondary) if secondary else None
    renderings = report.get("report_renderings") if isinstance(report.get("report_renderings"), Mapping) else {}
    rendering_rows = renderings.get("findings") if isinstance(renderings.get("findings"), Mapping) else {}
    bindings = report.get("resource_bindings") or {}
    wip_id = str(bindings.get("WIP") or "WIP")
    family = next((value for key, value in bindings.items() if key.startswith("ORIGINAL_LANGUAGE_")), "OL")
    source = f"{_FAMILY_NAMES[family]} original language" if family in _FAMILY_NAMES else "original language"
    coverage = report.get("coverage") or {}
    title = f"Number Consistency & Accuracy (NCA) — {_report_label(report, 'report.nca_action_report')}"
    lines = [
        "# " + title,
        "",
        f"- Projects: {wip_id} checked against the {source} (also see: NIV)",
        f"- {_report_label(report, 'label.scope')}: `{report.get('scope', '')}`",
        f"- Report languages: `{primary}`" + (f"; `{secondary}`" if secondary else ""),
        "",
        *authority_markdown(list(report.get("authority_header") or ())),
    ]
    route = report.get("execution_route")
    if isinstance(route, Mapping):
        lines.extend(["", *render_execution_section([route])])
    notice = render_report_language_authority(authority if authority else None, markdown=True)
    if notice:
        lines.extend(["", notice])
    if secondary and str(renderings.get("status") or "").upper() == "DEGRADED":
        lines.extend(["", f"> **{catalogue_text(primary, 'message.secondary_rendering_unavailable')}**"])
    lines.extend(["", "## " + _report_label(report, "report.actionable_findings"), ""])
    findings = list(report.get("findings") or ())
    if not findings:
        lines.append(_report_label(report, "message.no_actionable_findings"))
    for position, row in enumerate(findings):
        evidence = row.get("evidence") or {}
        secondary_row = rendering_rows.get(row["finding_id"]) if secondary else None
        lines.extend([
            f"### {row['finding_id']} — {row['target_reference']}",
            "",
            f"- Result: {_RESULT_NAMES.get(str(row['action_level']), str(row['action_level']))}",
            f"- Category: {_CATEGORY_NAMES.get(str(row['category']), str(row['category']))}",
            f"- Evidence: {wip_id}, {source}, NIV",
            f"- Numbers: translation {_list(row.get('wip_values'), text)}; source "
            f"{_list(row.get('expected_values'), text)} ("
            + text("report.nca.authority_label." + str(row.get("authority") or "OL")).format(
                family=_FAMILY_NAMES.get(family, family)) + ")",
            "",
            f"**Issue — {primary_name}**",
            "",
            str(row["issue"]),
            "",
            f"**Proposed action — {primary_name}**",
            "",
            str(row["required_action"]),
            "",
        ])
        if secondary and isinstance(secondary_row, Mapping):
            if str(secondary_row.get("issue") or "").strip():
                lines.extend([f"**Issue — {secondary_name}**", "", str(secondary_row["issue"]), ""])
            if str(secondary_row.get("required_action") or "").strip():
                lines.extend([f"**Proposed action — {secondary_name}**", "", str(secondary_row["required_action"]), ""])
        for label, value in ((wip_id, evidence.get("wip_text")), (source[:1].upper() + source[1:], evidence.get("ol_text")),
                             ("BSB", evidence.get("bsb_text"))):
            if value:
                lines.extend([f"**{text('report.nca.evidence_heading').format(label=label)}**", "", str(value), ""])
        # The NIV is cited by reference and numbers only; its text is never quoted (fair use).
        if evidence.get("bsb_text") or evidence.get("niv_values"):
            refs = row.get("western_reference") or row.get("target_reference") or "this verse"
            lines.extend([f"**{text('report.nca.also_see_niv')}**", "",
                          f"NIV {refs}: {_list(evidence.get('niv_values'), text)}", ""])
        if row.get("apparatus"):
            lines.extend([f"**{text('report.nca.apparatus_heading')}**", "", *_apparatus_markdown(row["apparatus"]), ""])
        if position != len(findings) - 1:
            lines.extend(["---", ""])
    # Notes split three ways: text-critical decisions (with cited apparatus), order notes, and
    # registry notes not already covered by a decision.
    notes = list(report.get("notes") or ())
    critical = [note for note in notes if note.get("kind") == "TEXT_CRITICAL"]
    order = [note for note in notes if note.get("kind") == "ORDER_NOTE"]
    covered = {note.get("western_reference") for note in critical}
    registry = [note for note in notes if note.get("kind") not in {"TEXT_CRITICAL", "ORDER_NOTE"}
                and (note.get("owner") or note.get("western_reference")) not in covered]
    if order:
        lines.extend(["", "## " + text("report.nca.order_notes"), ""])
        for note in order:
            pairs = ", ".join(f"{p.get('wip_counts') or '?'} {p.get('wip_value')}" for p in note.get("pairings") or ())
            lines.append("- " + text("report.nca.order_note").format(ref=note.get("western_reference", ""),
                                                                     pairs=pairs or "items matched"))
    if critical:
        lines.extend(["", "## " + text("report.nca.text_critical"), "", text("report.nca.text_critical_intro"), "",
                      "| Verse | Original language | NIV | Translation follows | Footnote in translation | "
                      "Registered guidance | Apparatus |", "|---|---|---|---|---|---|---|"])
        for note in critical:
            footnote = "yes" if note.get("footnote_in_wip") else "**no**"
            guidance = note.get("suggested_note") or note.get("niv_footnote") or "—"
            lines.append(f"| {note.get('western_reference')} | {_list(note.get('ol_values'), text)} | "
                         f"{_list(note.get('niv_values'), text)} | {'original language' if note.get('follows') == 'OL' else note.get('follows')} | {footnote} | "
                         f"{str(guidance).replace('|', '/')} | {_evidence_labels(note.get('apparatus'))} |")
        for note in critical:
            entries = list(note.get("apparatus") or ())
            lines.extend(["", f"**{note.get('western_reference')}** — {text('report.nca.apparatus_heading').lower()}", ""])
            lines.extend(_apparatus_markdown(entries) or ["- " + text("report.nca.no_apparatus")])
            if not note.get("footnote_in_wip"):
                basis = note.get("suggested_note") or next(
                    (str(entry.get("summary")) for entry in entries if entry.get("summary")), "")
                if basis:
                    lines.extend(["", f"{text('report.nca.footnote_basis')}: {basis}"])
    if registry:
        lines.extend(["", "## " + text("report.nca.text_notes"), ""])
        for note in registry:
            lines.append(
                f"- `{note.get('owner') or note.get('western_reference', '')}` | `{note.get('classification', '')}` "
                f"| `{note.get('scholarship_status', '')}` — {note.get('manuscript_evidence', '')} "
                f"(OL `{note.get('ol_values') or '—'}`; alternate `{note.get('alternate_values') or '—'}`)")
    lines.extend(["", *_closing_summary(report, coverage, text, primary)])
    cited = _cited_sources(report)
    if any((row.get("evidence") or {}).get("bsb_text") for row in findings):
        cited.add("BSB")  # quoted BSB verse text carries its public-domain attribution
    # Quoted original-language text comes from MACULA (CC BY 4.0), which requires its attribution line.
    ol_families = (
        ({family} if family in OL_TEXT_ATTRIBUTION else set(OL_TEXT_ATTRIBUTION))
        if any((row.get("evidence") or {}).get("ol_text") for row in findings)
        else set()
    )
    if cited or ol_families:
        from .numbers.index_build.apparatus import ATTRIBUTION
        lines.extend(["", "## " + text("report.nca.attribution"), "",
                      *[f"- {OL_TEXT_ATTRIBUTION[name]}" for name in OL_TEXT_ATTRIBUTION if name in ol_families],
                      *[f"- {ATTRIBUTION[source]}" for source in ATTRIBUTION if source in cited]])
    lines.extend(["", "## " + text("report.nca.closing_limitation"), "",
                  text("report.nca.capability_limitation"), "", "SQS: `NOT_APPLIED`"])
    return "\n".join(lines).rstrip() + "\n"


def _verse_list(refs: Sequence[str]) -> str:
    """Compact verse list: "GEN 1:5, 14, 16" within one chapter, full labels otherwise."""
    if not refs:
        return "—"
    prefixes = {ref.rsplit(":", 1)[0] for ref in refs if ":" in ref and "," not in ref}
    if len(prefixes) == 1 and all(":" in ref and "," not in ref for ref in refs):
        return f"{refs[0]}" + "".join(", " + ref.rsplit(":", 1)[1] for ref in refs[1:])
    return "; ".join(refs)


def _closing_summary(report: Mapping[str, object], coverage: Mapping[str, object], text, language: str) -> list[str]:
    """End-of-report summary: verses with no issue, verses without indexed numbers, and what was not checked."""
    from .exception_reports import render_exceptions_section
    no_issue = list(report.get("no_issue") or ())
    not_indexed = list(report.get("not_indexed") or ())
    advisories = list(report.get("advisories") or ())
    versification = list(report.get("versification_advisories") or ())
    lines = ["## " + text("report.nca.closing_summary"), "",
             f"- {text('report.nca.coverage_status')}: "
             f"{_COVERAGE_NAMES.get(str(coverage.get('status')), 'not recorded')} ("
             + text("report.nca.coverage_line").format(checked=coverage.get("checked", 0),
                                                       not_indexed=coverage.get("not_indexed", 0)) + ")",
             f"- {text('report.nca.no_issue')} ({len(no_issue)}): {_verse_list(no_issue)}",
             f"- {text('report.nca.without_numbers')} ({len(not_indexed)}): {_verse_list(not_indexed)}",
             f"- {text('report.nca.not_checked')} ({len(advisories)}): "
             + ("; ".join(f"{row['reference']} ({_human_reason(row['code'])})" for row in advisories) or "—")]
    if versification:
        lines.append(f"- {text('report.nca.versification')}: "
                     + "; ".join(f"{row['reference']} ({_human_reason(row['code'])})" for row in versification))
    if report.get("exceptions"):
        lines.extend(["", *render_exceptions_section(list(report["exceptions"]), language=language)])
    return lines


# Attribution for original-language verse text quoted in NCA reports; see docs/advanced/projects-and-resources/THIRD-PARTY-NOTICES.md.
OL_TEXT_ATTRIBUTION = {
    "HEB": "MACULA Hebrew Linguistic Datasets, available at https://github.com/Clear-Bible/macula-hebrew/ "
           "(© 2022–2024 Biblica, Inc., CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Hebrew text: "
           "Westminster Leningrad Codex, public domain. Number values are typed by SAGE from this data.",
    "GRK": "MACULA Greek Linguistic Datasets, available at https://github.com/Clear-Bible/macula-greek/ "
           "(© 2022–2024 Biblica, Inc., CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Greek text: "
           "SBL Greek New Testament, Copyright 2010 by the Society of Biblical Literature and Logos Bible "
           "Software, CC BY 4.0. Number values are typed by SAGE from this data.",
}


def _cited_sources(value: object) -> set[str]:
    """Every apparatus source quoted anywhere in a report (each needs its attribution line)."""
    found: set[str] = set()
    if isinstance(value, Mapping):
        if isinstance(value.get("source"), str):
            found.add(value["source"])
        for item in value.values():
            found |= _cited_sources(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= _cited_sources(item)
    return found


_SOURCE_LABELS = {
    "NET_TC": "NET Bible text-critical note",
    "SBLGNT_APPARATUS": "SBLGNT apparatus",
    "OSHB_KETIV_QERE": "Hebrew ketiv/qere (OSHB)",
    "REGISTRY": "SAGE textual-variant registry",
    "LXX_BRENTON": "Septuagint (Brenton 1851, public domain)",
    "VULGATE_DRA": "Vulgate (Douay-Rheims, public domain)",
    "KJV": "KJV (Masoretic / Received text, public domain)",
    "BSB": "Berean Standard Bible (public domain)",
    "BSB_NOTE": "Berean Standard Bible footnote",
    "PARALLEL": "Parallel passage (SAGE index)",
}


def _apparatus_markdown(entries) -> list[str]:
    """Cited apparatus evidence, one bullet per entry, readable without the source open."""
    from .numbers.index_build.apparatus import SIGLA
    lines = []
    for entry in entries or ():
        source = str(entry.get("source") or "")
        label = _SOURCE_LABELS.get(source, source)
        url = str(entry.get("url") or "")
        cite = f"[{label}]({url})" if url else label
        where = f" — {entry['reference']}" if entry.get("reference") else ""
        if source == "SBLGNT_APPARATUS" and entry.get("readings"):
            parts = []
            for reading in entry["readings"]:
                witnesses = ", ".join(SIGLA.get(name, name) for name in reading.get("witnesses") or ())
                prefix = "SBLGNT text " if reading.get("sblgnt") else ""
                parts.append(f"{prefix}«{reading.get('text')}»" + (f" ({witnesses})" if witnesses else ""))
            lines.append(f"- **{cite}**{where}: " + "; variant ".join(parts))
        elif source == "OSHB_KETIV_QERE" and entry.get("readings"):
            written, read = entry["readings"][0], entry["readings"][-1]
            lines.append(f"- **{cite}**{where}: written (ketiv) «{written.get('text')}», read (qere) «{read.get('text')}»")
        elif source == "REGISTRY":
            status = f" (scholarship: {entry['status']})" if entry.get("status") else ""
            lines.append(f"- **{cite}**{where}{status}: {entry.get('summary')}")
        else:
            basis = "; ".join(entry.get("basis") or ())
            see_also = "; ".join(entry.get("see_also") or ())
            lines.append(f"- **{cite}**{where}" + (f" — basis: {basis}" if basis else "")
                         + f": “{entry.get('summary')}”" + (f" Also see: {see_also}." if see_also else ""))
    return lines


def _evidence_labels(entries) -> str:
    """Short source list for a table cell."""
    labels = list(dict.fromkeys(_SOURCE_LABELS.get(str(entry.get("source")), str(entry.get("source")))
                                for entry in entries or ()))
    return "; ".join(labels) or "—"


def _publish_number_style(reports_root: Path, job, run, document: Mapping[str, object]) -> dict[str, str]:
    """Write NUMBER-STYLE.md for the Run and, without a profile, the reconstructed profile YAML."""
    from datetime import datetime, timezone
    import yaml
    from .atomic import atomic_write_text
    from .numbers.style import validate_style_profile
    from .numbers.style_report import reconstructed_profile, render
    style = (document.get("metrics") or {}).get("number_style")
    if not isinstance(style, Mapping):
        return {}
    wip = (document.get("provenance") or {}).get("wip") or {}
    project = str(wip.get("project_id") or wip.get("identity") or job.job_id)
    root = reports_root / job.job_id
    root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    profile = reconstructed_profile(
        style, project=project, language=str(wip.get("language") or ""), script=str(wip.get("script") or ""),
        recorded_date=datetime.now(timezone.utc).date().isoformat(), run_id=str(run.run_id))
    profile_path = None
    if profile is not None:
        try:
            validate_style_profile(profile)
        except Exception:  # an unimportable reconstruction is still reported, just not offered as a file
            profile = None
    if profile is not None:
        profile_path = root / f"{run.run_id}_NUMBER-STYLE-PROFILE-RECONSTRUCTED.yml"
        atomic_write_text(profile_path, yaml.safe_dump(profile, allow_unicode=True, sort_keys=False))
        paths["reconstructed_style_profile_path"] = str(profile_path)
    report_path = root / f"{run.run_id}_NUMBER-STYLE.md"
    atomic_write_text(report_path, render(style, project=project,
                                          profile_path=profile_path.name if profile_path else None))
    paths["number_style_report_path"] = str(report_path)
    return paths


def publish_nca_reports(config, job, run, document: Mapping[str, object], *,
                        primary_language: str, secondary_language: str | None) -> dict[str, object]:
    """Write per-chapter action reports, plain-text notes, the Job index and Run diagnostics."""
    from .act_outputs import render_plain_text_from_markdown
    from .atomic import atomic_write_text
    from .report_authority import chapter_note_path, chapter_report_path, write_job_summary
    from .report_translation import ensure_secondary_analysis_report_rendering

    snapshot = dict(job.wip_snapshot or {})
    raw_date = str(snapshot.get("snapshot_date") or "")
    snapshot_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}" if len(raw_date) == 8 else raw_date
    report_paths: list[str] = []
    note_paths: list[str] = []
    for report in build_chapter_reports(document, primary_language=primary_language,
                                        secondary_language=secondary_language, snapshot_date=snapshot_date):
        report_path = chapter_report_path(config.reports_root, job, run, report["book"], report["chapter"])
        note_path = chapter_note_path(config.reports_root, job, run, report["book"], report["chapter"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        if secondary_language and report["findings"]:
            report = ensure_secondary_analysis_report_rendering(config.root, report_path, report)
        markdown = render_nca_action_report(report)
        atomic_write_text(report_path, markdown)
        atomic_write_text(note_path, render_plain_text_from_markdown(markdown))
        report_paths.append(str(report_path))
        note_paths.append(str(note_path))
    summary_path = write_job_summary(config.reports_root, job, report_paths=[Path(path) for path in report_paths])
    style_paths = _publish_number_style(config.reports_root, job, run, document)
    diagnostics_path = run.root / "diagnostics" / "NCA-RUN-DIAGNOSTICS.md"
    atomic_write_text(diagnostics_path, render_nca_report(document, language="en"))
    return {
        "report_directory": str(config.reports_root / job.job_id),
        "report_paths": report_paths,
        "operator_note_text_paths": note_paths,
        "job_summary_path": str(summary_path),
        **style_paths,
        "diagnostics_path": str(diagnostics_path),
    }
