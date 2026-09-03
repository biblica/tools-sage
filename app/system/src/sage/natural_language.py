"""Governed natural-language request routing to registered SAGE commands.

This module proposes canonical commands. It never bypasses the normal parser,
controller, validation, scope, review, transaction, or write controls.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .atomic import atomic_write_text
from .guided_input import rank_suggestions
from .profiles import load_workflow_profile
from .platform_commands import render_sage_command
from .references import BOOK_ALIASES, BOOK_LABELS, BOOK_ORDER, parse_scope, resolve_book
from .registry import EcosystemConfig
from .vocabulary import (
    CANONICAL_TARGET_TEXT_OPERATION,
    require_canonical_target_text_vocabulary,
)

_WORD_RE = re.compile(r"[a-z0-9]+", re.I)
_SPACE_RE = re.compile(r"\s+")
_SCOPE_AFTER_BOOK_RE = re.compile(
    r"(?:\bchapters?\b|\bchapter\b|\bch\.?\b)?\s*"
    r"(?P<start>\d+(?::\d+)?)"
    r"(?:\s*(?:-|–|—|to|through|thru|and)\s*(?P<end>\d+(?::\d+)?))?",
    re.I,
)
_UNKNOWN_CODE_SCOPE_RE = re.compile(
    r"\b(?P<book>[A-Za-z]{3})\s+"
    r"(?P<start>\d+(?::\d+)?)"
    r"(?:\s*(?:-|–|—|to|through|thru|and)\s*(?P<end>\d+(?::\d+)?))?\b",
    re.I,
)

# BEGIN PRIVATE OPERATOR INPUT ALIASES
# These untrusted input synonyms are recognized but are never emitted as SAGE action vocabulary.
_PRIVATE_BIC_REWRITE_INPUT_ALIASES: tuple[tuple[str, float], ...] = (
    ("bic rewrite", 1.0),
    ("rewrite", 0.98),
    ("translate", 0.88),
    ("draft", 0.82),
    ("generate translation", 0.90),
    ("prepare", 0.66),
    ("make the translation better", 0.58),
)
# END PRIVATE OPERATOR INPUT ALIASES



@dataclass(frozen=True)
class RequestCorrection:
    """One proposed correction made while interpreting natural-language input."""

    field: str
    original: str
    resolved: str
    confidence: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation for reports and state files."""
        return {
            "field": self.field,
            "original": self.original,
            "resolved": self.resolved,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class CommandProposal:
    """One ranked registered SAGE command interpretation."""

    command_id: str
    title: str
    argv: tuple[str, ...]
    score: float
    confidence: str
    read_only: bool
    state_changing: bool
    workflow: str | None = None
    operation: str | None = None
    scope: str | None = None
    output_project: str | None = None
    contemporary_source: str | None = None
    lexical_donor: str | None = None
    missing_inputs: tuple[str, ...] = ()
    defaults_used: tuple[str, ...] = ()
    corrections: tuple[RequestCorrection, ...] = ()
    explanation: str = ""
    related_group: str = "general"

    @property
    def executable(self) -> bool:
        """Return whether this proposal can be submitted to the canonical parser."""
        return self.confidence in {"HIGH", "MEDIUM"} and not self.missing_inputs

    @property
    def canonical_command(self) -> str:
        """Return the shell-rendered canonical command for operator review."""
        return render_sage_command(self.argv)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for reports and state files."""
        require_canonical_target_text_vocabulary(
            "\n".join((self.title, self.canonical_command, self.explanation)),
            surface=f"natural-language proposal {self.command_id}",
        )
        return {
            "command_id": self.command_id,
            "title": self.title,
            "canonical_argv": list(self.argv),
            "canonical_command": self.canonical_command,
            "score": round(self.score, 3),
            "confidence": self.confidence,
            "executable": self.executable,
            "read_only": self.read_only,
            "state_changing": self.state_changing,
            "workflow": self.workflow,
            "operation": self.operation,
            "scope": self.scope,
            "output_project": self.output_project,
            "contemporary_source": self.contemporary_source,
            "lexical_donor": self.lexical_donor,
            "missing_inputs": list(self.missing_inputs),
            "defaults_used": list(self.defaults_used),
            "corrections": [item.to_dict() for item in self.corrections],
            "explanation": self.explanation,
            "related_group": self.related_group,
        }


@dataclass(frozen=True)
class IntentCandidate:
    """Internal intent score before command arguments are resolved."""

    command_id: str
    title: str
    base_argv: tuple[str, ...]
    score: float
    read_only: bool
    state_changing: bool
    workflow: str | None = None
    operation: str | None = None
    related_group: str = "general"
    explanation: str = ""
    needs_scope: bool = False
    needs_projects: bool = False
    needs_focus: bool = False


@dataclass
class ScopeResolution:
    """Store a resolved Scripture scope and any proposed book correction."""
    value: str | None = None
    explicit: bool = False
    corrections: list[RequestCorrection] = field(default_factory=list)


@dataclass
class ProjectResolution:
    """Store resolved source and target projects for a routed request."""
    mentioned: list[str] = field(default_factory=list)
    explicit: bool = False


def _normalise_text(value: str) -> str:
    """Case-fold and simplify Operator wording for conservative intent matching."""
    return _SPACE_RE.sub(" ", value.strip().casefold())


def _contains_phrase(text: str, phrase: str) -> bool:
    """Return whether a complete routed phrase occurs in the normalized request."""
    phrase_value = _normalise_text(phrase)
    if not phrase_value:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase_value) + r"(?![a-z0-9])", text) is not None


def _phrase_score(text: str, weighted: Sequence[tuple[str, float]]) -> float:
    """Return the strongest score among configured phrases found in the request."""
    return max((weight for phrase, weight in weighted if _contains_phrase(text, phrase)), default=0.0)


def _confidence(score: float) -> str:
    """Map a routing score to the governed interpretation confidence label."""
    if score >= 0.84:
        return "HIGH"
    if score >= 0.62:
        return "MEDIUM"
    return "LOW"


def _book_patterns() -> list[tuple[str, str]]:
    """Return book-name and code patterns ordered to avoid partial-name collisions."""
    patterns: dict[str, str] = {}
    for code, label in BOOK_LABELS.items():
        patterns[code.casefold()] = code
        patterns[label.casefold()] = code
        compact = label.replace(" ", "").casefold()
        patterns[compact] = code
    # Common prose forms that are clearer with spaces than the internal aliases.
    numbered = {
        "first john": "1JN",
        "second john": "2JN",
        "third john": "3JN",
        "1 john": "1JN",
        "2 john": "2JN",
        "3 john": "3JN",
        "i john": "1JN",
        "ii john": "2JN",
        "iii john": "3JN",
    }
    patterns.update(numbered)
    return sorted(patterns.items(), key=lambda item: (-len(item[0]), item[0]))


def _scope_from_parts(book: str, start: str | None, end: str | None) -> str:
    """Build a canonical Scripture scope from resolved book and numeric components."""
    if not start:
        return book
    if not end:
        candidate = f"{book} {start}"
    else:
        candidate = f"{book} {start}-{end}"
    return parse_scope(candidate).label()


def _extract_scope(request: str) -> ScopeResolution:
    """Extract a canonical scope and conservative book-code corrections."""
    text = request.strip()
    lower = text.casefold()
    for label, code in _book_patterns():
        match = re.search(r"(?<![a-z0-9])" + re.escape(label) + r"(?![a-z0-9])", lower)
        if not match:
            continue
        tail = text[match.end() :]
        range_match = _SCOPE_AFTER_BOOK_RE.search(tail)
        if range_match:
            try:
                value = _scope_from_parts(code, range_match.group("start"), range_match.group("end"))
            except Exception:  # The canonical parser will provide the final validation detail.
                value = code
        else:
            value = code
        return ScopeResolution(value=value, explicit=True)

    unknown = _UNKNOWN_CODE_SCOPE_RE.search(text)
    if unknown:
        received = unknown.group("book").upper()
        try:
            code = resolve_book(received)
            return ScopeResolution(
                value=_scope_from_parts(code, unknown.group("start"), unknown.group("end")),
                explicit=True,
            )
        except Exception:
            suggestions = rank_suggestions(received, BOOK_ORDER.keys(), labels=BOOK_LABELS)
            if suggestions and suggestions[0].confidence in {"HIGH", "MEDIUM"}:
                top = suggestions[0]
                return ScopeResolution(
                    value=_scope_from_parts(top.value, unknown.group("start"), unknown.group("end")),
                    explicit=True,
                    corrections=[
                        RequestCorrection(
                            field="Scripture book",
                            original=received,
                            resolved=top.value,
                            confidence=top.confidence,
                        )
                    ],
                )
    return ScopeResolution()


def _project_aliases(config: EcosystemConfig) -> dict[str, str]:
    """Build project aliases from IDs, language codes, names, and configured roles."""
    aliases: dict[str, str] = {}
    prefixes = ("ukr", "id", "us", "fa")
    for project_id in config.projects:
        key = project_id.casefold()
        aliases[key] = project_id
        for prefix in prefixes:
            if key.startswith(prefix) and len(key) > len(prefix):
                aliases[key[len(prefix) :]] = project_id
        aliases[re.sub(r"[^a-z0-9]", "", key)] = project_id
    return aliases


def _extract_projects(request: str, config: EcosystemConfig) -> ProjectResolution:
    """Resolve project mentions without inventing Project IDs that are not in SAGE."""
    text = request.casefold()
    aliases = _project_aliases(config)
    found: list[tuple[int, str]] = []
    for alias, project_id in aliases.items():
        if not alias:
            continue
        match = re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text)
        if match:
            found.append((match.start(), project_id))
    found.sort()
    projects = list(dict.fromkeys(project_id for _, project_id in found))
    return ProjectResolution(mentioned=projects, explicit=bool(projects))


def _workflow_defaults(config: EcosystemConfig, workflow_id: str) -> Mapping[str, str]:
    """Return the configured default Project bindings for one workflow."""
    profile = load_workflow_profile(config, config.workflow(workflow_id))
    return profile.bindings


def _intent_candidates(request: str) -> list[IntentCandidate]:
    """Score only registered SAGE operations that plausibly match the request."""
    # Score only registered intents; this procedure must never invent an executable operation.
    text = _normalise_text(request)
    candidates: list[IntentCandidate] = []

    def add(
        command_id: str,
        title: str,
        argv: Sequence[str],
        score: float,
        *,
        read_only: bool,
        state_changing: bool,
        workflow: str | None = None,
        operation: str | None = None,
        group: str = "general",
        explanation: str,
        needs_scope: bool = False,
        needs_projects: bool = False,
        needs_focus: bool = False,
    ) -> None:
        """Add one scored intent signal without discarding stronger prior evidence."""
        if score <= 0:
            return
        candidates.append(
            IntentCandidate(
                command_id=command_id,
                title=title,
                base_argv=tuple(argv),
                score=min(1.0, score),
                read_only=read_only,
                state_changing=state_changing,
                workflow=workflow,
                operation=operation,
                related_group=group,
                explanation=explanation,
                needs_scope=needs_scope,
                needs_projects=needs_projects,
                needs_focus=needs_focus,
            )
        )

    rtc_score = _phrase_score(
        text,
        (
            ("run rtc", 1.0),
            ("reference text comparison", 1.0),
            ("quality assurance", 1.0),
            ("rtc", 0.94),
            ("review translation", 0.78),
            ("review", 0.58),
            ("check", 0.52),
            ("audit", 0.62),
        ),
    )
    stc_score = _phrase_score(
        text,
        (
            ("run stc", 1.0),
            ("source text correspondence", 1.0),
            ("original language", 0.9),
            ("greek", 0.78),
            ("hebrew", 0.78),
        ),
    )
    bic_inspect = _phrase_score(
        text,
        (
            ("bic inspect", 1.0),
            ("translation challenges", 0.98),
            ("analyze challenges", 0.98),
            ("analyze challenges", 0.98),
            ("inspect", 0.86),
            ("prepare", 0.72),
            ("review", 0.55),
        ),
    )
    bic_rewrite = _phrase_score(text, _PRIVATE_BIC_REWRITE_INPUT_ALIASES)
    bic_self = _phrase_score(
        text,
        (("self-check", 1.0), ("self check", 1.0), ("verify rewrite", 0.92)),
    )

    if _contains_phrase(text, "bic") or "kkh" in text or "bol" in text:
        bic_inspect += 0.08
        bic_rewrite += 0.08
        bic_self += 0.08
    if _contains_phrase(text, "rtc") or "npu" in text or "tmn" in text:
        rtc_score += 0.08
    if _contains_phrase(text, "stc"):
        stc_score += 0.08
    if "from" in text and " to " in f" {text} ":
        bic_inspect += 0.08
        bic_rewrite += 0.06
    if _contains_phrase(text, "new translation") or _contains_phrase(text, "start translation"):
        bic_inspect += 0.12
    if _contains_phrase(text, "rewrite"):
        bic_inspect -= 0.18
    if stc_score > 0:
        rtc_score -= 0.18

    add(
        "rtc.compare",
        "Reference Text Comparison (RTC)",
        ("task", "create", "--workflow", "rtc", "--operation", "rtc"),
        rtc_score,
        read_only=False,
        state_changing=True,
        workflow="rtc",
        operation="rtc",
        group="rtc",
        explanation="Create a bounded read-only Reference Text Comparison (RTC) ACT task; task state and reports are written.",
        needs_scope=True,
        needs_projects=True,
    )
    add(
        "stc.correspondence",
        "Source Text Correspondence (STC)",
        ("task", "create", "--workflow", "stc", "--operation", "stc"),
        stc_score,
        read_only=False,
        state_changing=True,
        workflow="stc",
        operation="stc",
        group="stc",
        explanation="Create a bounded read-only Source Text Correspondence (STC) ACT task against the testament-correct primary authority.",
        needs_scope=True,
        needs_projects=True,
    )
    add(
        "bic.inspect",
        "BIC INSPECT",
        ("task", "create", "--workflow", "bic", "--operation", "inspect"),
        bic_inspect,
        read_only=False,
        state_changing=True,
        workflow="bic",
        operation="inspect",
        group="bic",
        explanation="Start the governed BIC sequence by analyzing translation challenges without writing Scripture.",
        needs_scope=True,
        needs_projects=True,
    )
    add(
        "bic.rewrite",
        "BIC REWRITE",
        ("task", "create", "--workflow", "bic", "--operation", CANONICAL_TARGET_TEXT_OPERATION),
        bic_rewrite,
        read_only=False,
        state_changing=True,
        workflow="bic",
        operation=CANONICAL_TARGET_TEXT_OPERATION,
        group="bic",
        explanation="Create a BIC REWRITE task after the required committed INSPECT operation; optional memory-review provenance does not gate execution.",
        needs_scope=True,
        needs_projects=True,
    )
    add(
        "bic.self_check",
        "BIC SELF-CHECK",
        ("task", "create", "--workflow", "bic", "--operation", "self_check"),
        bic_self,
        read_only=False,
        state_changing=True,
        workflow="bic",
        operation="self_check",
        group="bic",
        explanation="Create the isolated BIC self-check using a validated predecessor rewrite task.",
        needs_scope=True,
        needs_projects=True,
    )

    status_score = _phrase_score(text, (("status", 0.96), ("readiness", 0.88), ("show state", 0.86)))
    if status_score:
        if _contains_phrase(text, "bic"):
            add(
                "workflow.status.bic",
                "BIC workflow status",
                ("workflow", "status", "--workflow", "bic"),
                status_score + 0.04,
                read_only=True,
                state_changing=False,
                workflow="bic",
                group="status",
                explanation="Report BIC readiness and restrictions without changing project state.",
            )
        elif _contains_phrase(text, "rtc"):
            add(
                "workflow.status.rtc",
                "RTC workflow status",
                ("workflow", "status", "--workflow", "rtc"),
                status_score + 0.04,
                read_only=True,
                state_changing=False,
                workflow="rtc",
                group="status",
                explanation="Report RTC readiness and restrictions without changing Project state.",
            )
        elif _contains_phrase(text, "stc"):
            add(
                "workflow.status.stc",
                "STC workflow status",
                ("workflow", "status", "--workflow", "stc"),
                status_score + 0.04,
                read_only=True,
                state_changing=False,
                workflow="stc",
                group="status",
                explanation="Report STC readiness and restrictions without changing Project state.",
            )
        else:
            add(
                "workspace.status",
                "Workspace status",
                ("workspace", "status"),
                status_score,
                read_only=True,
                state_changing=False,
                group="status",
                explanation="Show the last governed workspace state without changing it.",
            )

    init_score = _phrase_score(
        text,
        (("initialize workspace", 1.0), ("initialize workspace", 1.0), ("workspace initialize", 1.0)),
    )
    setup_score = _phrase_score(
        text,
        (("project init", 1.0), ("set up", 0.82), ("setup", 0.82), ("configure", 0.76), ("initialize", 0.70), ("initialize", 0.70)),
    )
    add(
        "workspace.initialize",
        "Initialize workspace resources",
        ("workspace", "initialize"),
        init_score,
        read_only=False,
        state_changing=True,
        group="initialization",
        explanation="Compile registered resources and write governed readiness state.",
    )
    add(
        "project.init",
        "Guided project INIT",
        ("project", "init"),
        setup_score,
        read_only=False,
        state_changing=True,
        group="initialization",
        explanation="Review recoverable settings and store governed effective Operator choices.",
    )

    list_projects = _phrase_score(text, (("list projects", 1.0), ("show projects", 0.94), ("registered projects", 0.86)))
    add(
        "project.list",
        "List SAGE Projects",
        ("project", "list"),
        list_projects,
        read_only=True,
        state_changing=False,
        group="project",
        explanation="List SAGE Projects, roles, scope, state, and profiles.",
    )

    validate_score = _phrase_score(text, (("validate workspace", 1.0), ("workspace validate", 1.0), ("validate", 0.68)))
    add(
        "workspace.validate",
        "Validate workspace",
        ("workspace", "validate"),
        validate_score,
        read_only=True,
        state_changing=False,
        group="workspace",
        explanation="Validate current ecosystem configuration without performing translation analysis.",
    )
    doctor_score = _phrase_score(text, (("workspace doctor", 1.0), ("doctor", 0.92), ("diagnose environment", 0.88)))
    add(
        "workspace.doctor",
        "Run workspace doctor",
        ("workspace", "doctor"),
        doctor_score,
        read_only=True,
        state_changing=False,
        group="workspace",
        explanation="Check Python, dependencies, settings, and workspace paths.",
    )
    reset_score = _phrase_score(text, (("reset workspace", 1.0), ("reset state", 0.96), ("clear runtime state", 0.94)))
    add(
        "workspace.reset_state",
        "Reset generated workspace state",
        ("workspace", "reset-state"),
        reset_score,
        read_only=False,
        state_changing=True,
        group="workspace",
        explanation="Remove generated runtime state and caches while preserving project resources and configuration.",
    )

    publish_score = _phrase_score(text, (("publish target", 1.0), ("publish generation", 1.0), ("publish", 0.68)))
    add(
        "generation.publish",
        "Publish generated target",
        ("generation", "publish"),
        publish_score,
        read_only=False,
        state_changing=True,
        group="generation",
        explanation="Validate and publish the current BIC target as an immutable generation.",
    )
    generation_list = _phrase_score(text, (("list generations", 1.0), ("show generations", 0.94)))
    add(
        "generation.list",
        "List target generations",
        ("generation", "list"),
        generation_list,
        read_only=True,
        state_changing=False,
        group="generation",
        explanation="List immutable BIC target generations.",
    )
    generation_verify = _phrase_score(text, (("verify generation", 1.0), ("check generation", 0.90)))
    add(
        "generation.verify",
        "Verify target generation",
        ("generation", "verify"),
        generation_verify,
        read_only=True,
        state_changing=False,
        group="generation",
        explanation="Verify one exact immutable generation and file inventory.",
    )

    transaction_list = _phrase_score(text, (("list transactions", 1.0), ("incomplete transactions", 0.92)))
    add(
        "transaction.list",
        "List incomplete transactions",
        ("transaction", "list", "--workflow", "bic" if "bic" in text else "stc" if "stc" in text else "rtc"),
        transaction_list,
        read_only=True,
        state_changing=False,
        group="transaction",
        explanation="List incomplete transactions for the selected workflow.",
    )
    transaction_recover = _phrase_score(text, (("recover transaction", 1.0), ("rollback transaction", 0.96)))
    add(
        "transaction.recover",
        "Recover transaction",
        ("transaction", "recover", "--workflow", "bic" if "bic" in text else "stc" if "stc" in text else "rtc"),
        transaction_recover,
        read_only=False,
        state_changing=True,
        group="transaction",
        explanation="Rollback one incomplete transaction after the transaction ID is supplied.",
    )

    submit_score = _phrase_score(text, (("submit task", 1.0), ("finalize task", 0.94), ("finalize task", 0.94)))
    add(
        "task.submit",
        "Submit completed ACT task",
        ("task", "submit"),
        submit_score,
        read_only=False,
        state_changing=True,
        group="task",
        explanation="Validate and finalize one completed ACT task; the task-manifest path is required.",
    )
    aggregate_score = _phrase_score(text, (("aggregate work units", 1.0), ("aggregate plan", 0.94)))
    add(
        "task.aggregate",
        "Aggregate analysis work units",
        ("task", "aggregate"),
        aggregate_score,
        read_only=False,
        state_changing=True,
        group="task",
        explanation="Aggregate finalized RTC/STC work units through their governed partition plan.",
    )

    return candidates


def _project_roles(config: EcosystemConfig, project_ids: Iterable[str]) -> dict[str, list[str]]:
    """Return role sets used to validate a routed source or target project."""
    result: dict[str, list[str]] = {}
    for project_id in project_ids:
        try:
            result[project_id] = list(config.project(project_id).scope.roles)
        except Exception:
            result[project_id] = []
    return result


def _resolve_task_proposal(
    candidate: IntentCandidate,
    request: str,
    config: EcosystemConfig,
    scope: ScopeResolution,
    projects: ProjectResolution,
) -> CommandProposal:
    """Construct one complete canonical task command from a scored intent."""
    argv = list(candidate.base_argv)
    missing: list[str] = []
    defaults_used: list[str] = []
    output_project: str | None = None
    contemporary_source: str | None = None
    lexical_donor: str | None = None
    project_roles = _project_roles(config, projects.mentioned)
    bindings = _workflow_defaults(config, candidate.workflow or "rtc")

    if candidate.workflow in {"rtc", "stc"}:
        for project_id in projects.mentioned:
            roles = set(project_roles.get(project_id, ()))
            if output_project is None and "WIP" in roles:
                output_project = project_id
            if candidate.workflow == "rtc" and contemporary_source is None and "REFERENCE" in roles:
                contemporary_source = project_id
        if output_project is None:
            output_project = bindings.get("WIP")
            if output_project:
                defaults_used.append("output_project")
        if candidate.workflow == "rtc" and contemporary_source is None:
            contemporary_source = bindings.get("REFERENCE")
            if contemporary_source:
                defaults_used.append("contemporary_source")
    elif candidate.workflow == "bic":
        for project_id in projects.mentioned:
            roles = set(project_roles.get(project_id, ()))
            if output_project is None and "GENERATED_TARGET" in roles:
                output_project = project_id
            if contemporary_source is None and "CONTENT_SOURCE" in roles:
                contemporary_source = project_id
            if lexical_donor is None and "LEXICAL_DONOR" in roles:
                lexical_donor = project_id
        if output_project is None:
            output_project = bindings.get("GENERATED_TARGET")
            if output_project:
                defaults_used.append("output_project")
        if contemporary_source is None:
            contemporary_source = bindings.get("CONTENT_SOURCE")
            if contemporary_source:
                defaults_used.append("contemporary_source")
        if lexical_donor is None:
            lexical_donor = bindings.get("LEXICAL_DONOR")
            if lexical_donor:
                defaults_used.append("lexical_donor")

    if output_project:
        argv.extend((("--target" if candidate.workflow == "bic" else "--wip"), output_project))
    else:
        missing.append("output_project")
    if contemporary_source:
        argv.extend((("--source" if candidate.workflow == "bic" else "--reference"), contemporary_source))
    elif candidate.workflow != "stc":
        missing.append("contemporary_source")
    if candidate.workflow == "bic":
        if lexical_donor:
            argv.extend(("--donor", lexical_donor))
        else:
            missing.append("lexical_donor")
    if scope.value:
        argv.extend(("--scope", scope.value))
    else:
        missing.append("scope")

    if candidate.needs_focus:
        focus_match = re.search(r"\b(?:focus(?:ed)?\s+(?:on|question)?|question)\s*[:=-]?\s*(.+)$", request, re.I)
        if focus_match and focus_match.group(1).strip():
            argv.extend(("--focus", focus_match.group(1).strip()))
        else:
            missing.append("focus")

    score = candidate.score
    if scope.value:
        score += 0.04
    else:
        score -= 0.16
    if projects.explicit:
        score += 0.03
    if defaults_used:
        score -= 0.03 * len(defaults_used)
    if scope.corrections:
        score -= 0.04
    score -= 0.12 * len(missing)
    score = max(0.0, min(1.0, score))
    return CommandProposal(
        command_id=candidate.command_id,
        title=candidate.title,
        argv=tuple(argv),
        score=score,
        confidence=_confidence(score),
        read_only=candidate.read_only,
        state_changing=candidate.state_changing,
        workflow=candidate.workflow,
        operation=candidate.operation,
        scope=scope.value,
        output_project=output_project,
        contemporary_source=contemporary_source,
        lexical_donor=lexical_donor,
        missing_inputs=tuple(missing),
        defaults_used=tuple(defaults_used),
        corrections=tuple(scope.corrections),
        explanation=candidate.explanation,
        related_group=candidate.related_group,
    )


def _resolve_generic_proposal(candidate: IntentCandidate) -> CommandProposal:
    """Construct a canonical non-task command proposal from a scored intent."""
    missing: list[str] = []
    if candidate.command_id == "transaction.recover":
        missing.append("transaction_id")
    if candidate.command_id == "task.submit":
        missing.append("task_manifest")
    if candidate.command_id == "task.aggregate":
        missing.append("partition_plan")
    score = max(0.0, candidate.score - 0.12 * len(missing))
    return CommandProposal(
        command_id=candidate.command_id,
        title=candidate.title,
        argv=candidate.base_argv,
        score=score,
        confidence=_confidence(score),
        read_only=candidate.read_only,
        state_changing=candidate.state_changing,
        workflow=candidate.workflow,
        operation=candidate.operation,
        missing_inputs=tuple(missing),
        explanation=candidate.explanation,
        related_group=candidate.related_group,
    )


def related_operations() -> list[dict[str, str]]:
    """Return concise registered operation families for low-confidence fallback."""
    return [
        {"command_id": "bic.inspect", "label": "BIC INSPECT - analyze a bounded source scope"},
        {"command_id": "bic.rewrite", "label": "BIC REWRITE - generate a candidate after review"},
        {"command_id": "bic.self_check", "label": "BIC SELF-CHECK - validate and commit a rewrite"},
        {"command_id": "rtc.compare", "label": "Reference Text Comparison (RTC) - compare a bounded WIP scope with its Reference Project"},
        {"command_id": "stc.correspondence", "label": "Source Text Correspondence (STC) - compare a bounded WIP scope with primary source text"},
        {"command_id": "project.init", "label": "Guided INIT - review recoverable settings"},
        {"command_id": "workspace.status", "label": "Workspace status - read current governed state"},
    ]


def interpret_request(request: str, config: EcosystemConfig) -> dict[str, Any]:
    """Map a natural-language request to ranked registered SAGE commands."""
    original = request.strip()
    candidates = _intent_candidates(original)
    scope = _extract_scope(original)
    projects = _extract_projects(original, config)
    proposals: list[CommandProposal] = []
    for candidate in candidates:
        if candidate.needs_scope or candidate.needs_projects:
            proposal = _resolve_task_proposal(candidate, original, config, scope, projects)
        else:
            proposal = _resolve_generic_proposal(candidate)
        if proposal.score >= 0.34:
            proposals.append(proposal)
    proposals.sort(key=lambda item: (-item.score, item.command_id))
    proposals = proposals[:6]

    top = proposals[0] if proposals else None
    if top is None or top.score < 0.50:
        status = "UNSUPPORTED_OPERATION"
        message = "This request does not match a registered SAGE operation with sufficient confidence."
        exact = False
    else:
        exact = (
            top.confidence == "HIGH"
            and not top.defaults_used
            and not top.corrections
            and not top.missing_inputs
        )
        status = "MATCHED" if exact else "INTERPRETATION_REQUIRED"
        message = (
            "The request maps unambiguously to one registered SAGE operation."
            if exact
            else "This request does not exactly match one registered SAGE operation."
        )

    if top is not None and top.executable:
        menu = [
            "Refine the request",
            "Execute the suggested command",
            "Edit the suggested command",
            "Explain the suggested command",
            "Show other related operations",
            "Advisory response only - no project changes",
            "Cancel",
        ]
    else:
        menu = [
            "Refine the request",
            "Show related supported operations",
            "Advisory response only - no project changes",
            "Cancel",
        ]

    return {
        "schema_version": "1.0",
        "status": status,
        "message": message,
        "original_request": original,
        "exact_match": exact,
        "most_likely_command": top.to_dict() if top is not None else None,
        "command_proposals": [item.to_dict() for item in proposals],
        "related_operations": related_operations(),
        "operator_choices": menu,
        "execution_policy": {
            "canonical_controller_required": True,
            "silent_correction_permitted": False,
            "state_change_requires_explicit_confirmation": True,
            "freestyle_project_execution_permitted": False,
            "advisory_mode_writes_project_state": False,
        },
    }


def request_log_path(config: EcosystemConfig) -> Path:
    """Return the governed request-routing audit log path."""
    return config.system_root / "logs" / "natural-language-requests.jsonl"


def append_request_log(
    config: EcosystemConfig,
    interpretation: Mapping[str, Any],
    *,
    decision: str,
    selected_command: Mapping[str, Any] | None = None,
) -> Path:
    """Append one routing decision without changing project resources or settings."""
    path = request_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "original_request": interpretation.get("original_request"),
        "interpretation_status": interpretation.get("status"),
        "decision": decision,
        "selected_command_id": (selected_command or {}).get("command_id"),
        "canonical_command": (selected_command or {}).get("canonical_command"),
        "confidence": (selected_command or {}).get("confidence"),
    }
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    atomic_write_text(path, existing + json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path
