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
    "report.nca.passes": "Passes",
    "report.nca.failures": "Failures",
    "report.nca.needs_review": "Needs review",
    "report.nca.not_assessed": "Not assessed",
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
    'report.nca.translator_note_fail':
        '{ref}: Please check the numbers in this verse. The translation currently has {wip}; '
        'based on {authority}, it should have {expected}.',
    'report.nca.translator_note_needs_review':
        '{ref}: The numbers {wip} appear in a different order than the source ({expected}). '
        'If this is simply natural word order in your language, no change is needed. If these '
        'numbers describe different things, please double-check each number is attached to '
        'the correct item. For reference, the source reads: "{authority_text}"',
    'report.nca.translator_note_authority_ol': 'the original-language text',
    'report.nca.translator_note_authority_niv': 'the reference translation (NIV)',
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


def _chapter_lines(document, text) -> list[str]:
    """Render navigation links without copying canonical evidence or findings."""
    groups = {group['unit_id']: group for group in document['groups']}
    findings = {finding['finding_id']: finding for finding in document['findings']}
    lines = []
    for section in chapter_sections(document):
        title = f"{section['book']} {section['chapter']}" if section['book'] else text('report.nca.unlocated')
        lines.extend([f'## {title}', ''])
        for group_id in section['group_ids']:
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
        for cross in section['cross_references']:
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


def _translator_note(finding: Mapping[str, object], group: Mapping[str, object], text) -> str | None:
    """Render one copy-paste-ready plain-language note for a FAIL or NEEDS_REVIEW finding.

    Deliberately outside the technical finding block above: no codes, no backticks, no
    internal field names -- an Operator must be able to select and paste this directly
    to a translator. Uses the WIP-side target reference (what the translator recognizes
    in their own project), not the internal Western/canonical reference.
    """
    code = finding.get('code')
    ref = _joined(finding.get('target_references'))
    wip = _joined(finding.get('wip_values'))
    expected = _joined(finding.get('expected_values'))
    if code == 'NCA_NUMBER_FAIL':
        comparison = group.get('comparison') or {}
        authority_key = ('report.nca.translator_note_authority_ol' if comparison.get('authority') == 'OL'
                         else 'report.nca.translator_note_authority_niv')
        return text('report.nca.translator_note_fail').format(
            ref=ref, wip=wip, expected=expected, authority=text(authority_key))
    if code == 'NCA_NUMBER_NEEDS_REVIEW':
        review_context = ((group.get('comparison') or {}).get('review_context')) or {}
        authority_text = review_context.get('authority_text') or 'NOT RECORDED'
        return text('report.nca.translator_note_needs_review').format(
            ref=ref, wip=wip, expected=expected, authority_text=authority_text)
    return None


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
        and group["extraction"].get("status") != "UNSUPPORTED"
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
    lines.extend(
        [
            "",
            f"## {text('report.nca.summary')}",
            "",
            f"- {text('report.nca.groups')}: `{summary.get('groups', 0)}`",
            f"- {text('report.nca.passes')}: `{summary.get('passes', 0)}`",
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
            f"## {text('report.nca.chapters')}",
            "",
        ]
    )
    lines.extend(_optimized_metrics(document, text))
    lines.extend(_chapter_lines(document, text))
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
