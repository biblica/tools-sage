"""Guided INIT review and governed effective-configuration remediation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, TextIO

import yaml

from .auto_resolution import resolve_auto_settings
from .canon import CANON_VALUES, PROJECT_ROLE_VALUES, TESTAMENT_VALUES
from .config import load_yaml
from .errors import InputRequiredError, OperatorCancelledError, SageError, ValidationError
from .guided_input import Suggestion, confirm_correction, prompt_for_value, prompt_text
from .operator_overrides import operator_override_path, write_operator_overrides
from .references import BOOK_ORDER
from .registry import EcosystemConfig, ProjectSpec


def _authoritative_suggestions(
    choices: Iterable[str],
    labels: Mapping[str, str] | None = None,
) -> list[Suggestion]:
    """Return only alternatives derived from the registered ecosystem and profile contracts."""
    labels = labels or {}
    return [
        Suggestion(
            value=str(value),
            label=str(labels.get(str(value), str(value))),
            score=1.0,
            confidence="AUTHORITATIVE",
        )
        for value in choices
    ]


def _choose(
    label: str,
    choices: Iterable[str],
    *,
    labels: Mapping[str, str] | None = None,
    received: str | None = None,
    input_stream: TextIO,
    output_stream: TextIO,
) -> str:
    """Prompt for one numbered option and return the explicitly selected value."""
    options = [str(item) for item in choices]
    value = prompt_for_value(
        label=label,
        received=received,
        suggestions=_authoritative_suggestions(options, labels),
        input_stream=input_stream,
        output_stream=output_stream,
    )
    if value not in options:
        raise InputRequiredError(
            f"Invalid {label.lower()}: {value!r}",
            code="INVALID_INIT_SETTING",
            received=value,
            suggestions=[item.to_dict() for item in _authoritative_suggestions(options, labels)],
            next_action=f"Choose one valid {label.lower()}.",
        )
    return value


def _yes_no(
    label: str,
    *,
    default: bool,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    """Request an explicit yes/no decision, treating cancellation as `ABANDONED`."""
    output_stream.write(f"{label} [{'Y/n' if default else 'y/N'}] ")
    output_stream.flush()
    answer = input_stream.readline()
    if answer == "":
        raise OperatorCancelledError("Input stream closed during INIT review")
    value = answer.strip().casefold()
    if not value:
        return default
    if value in {"y", "yes"}:
        return True
    if value in {"n", "no"}:
        return False
    raise InputRequiredError(
        f"Expected yes or no, received {answer.strip()!r}",
        code="INVALID_YES_NO_INPUT",
        received=answer.strip(),
        suggestions=[
            {"value": "yes", "label": "Yes", "score": 1.0, "confidence": "AUTHORITATIVE"},
            {"value": "no", "label": "No", "score": 1.0, "confidence": "AUTHORITATIVE"},
        ],
        next_action="Answer yes or no.",
    )


def _set_nested(root: dict[str, Any], dotted: str, value: Any) -> None:
    """Set one nested effective-setting value without mutating the source settings document."""
    parts = dotted.split(".")
    target = root
    for part in parts[:-1]:
        target = target.setdefault(part, {})
        if not isinstance(target, dict):
            raise ValidationError(f"Cannot set INIT override {dotted}; {part} is not a mapping")
    target[parts[-1]] = deepcopy(value)


def _existing_override_data(config: EcosystemConfig) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load the current governed override sidecar when its source hash is still valid."""
    path = config.operator_overrides_path
    if path is None or not path.is_file():
        return {}, []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    overrides = payload.get("overrides", {}) or {}
    resolutions = payload.get("operator_resolutions", []) or []
    if not isinstance(overrides, dict) or not isinstance(resolutions, list):
        raise ValidationError("Existing INIT operator override file is malformed")
    return deepcopy(overrides), [deepcopy(item) for item in resolutions if isinstance(item, dict)]


def _record(
    resolutions: list[dict[str, Any]],
    *,
    setting: str,
    original: Any,
    resolved: Any,
    method: str,
) -> None:
    """Append one remediation decision to the auditable resolution history."""
    resolutions.append(
        {
            "setting": setting,
            "original_value": deepcopy(original),
            "resolved_value": deepcopy(resolved),
            "method": method,
        }
    )


def _review_configured(
    config: EcosystemConfig,
    overrides: dict[str, Any],
    resolutions: list[dict[str, Any]],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    """Review the ecosystem configured flag and offer a governed effective override."""
    if config.configured:
        return False
    print("", file=output_stream)
    print(prompt_text("prompt.configured_false", "The ecosystem is declared configured: false."), file=output_stream)
    print(prompt_text("prompt.configured_override", "INIT can mark the effective configuration configured without rewriting ecosystem.yml."), file=output_stream)
    if not _yes_no(
        "Mark the effective configuration configured?",
        default=True,
        input_stream=input_stream,
        output_stream=output_stream,
    ):
        return False
    _set_nested(overrides, "ecosystem.configured", True)
    _record(
        resolutions,
        setting="ecosystem.configured",
        original=False,
        resolved=True,
        method="OPERATOR_CONFIRMED_OVERRIDE",
    )
    return True


def _explicit_auto_value(row: dict[str, Any]) -> Any:
    """Return an explicit alternative for one setting currently declared as `auto`."""
    setting = str(row["setting"])
    if setting.endswith("scope.expected_books"):
        return list(row.get("resolved") or [])
    if setting.endswith("versification.custom_file"):
        resolved = row.get("resolved")
        return Path(str(resolved)).name if resolved else "none"
    return deepcopy(row.get("resolved"))


def _alternative_auto_value(
    config: EcosystemConfig,
    row: dict[str, Any],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> Any:
    """Return another registered value that can safely replace the proposed automatic value."""
    setting = str(row["setting"])
    project_id = str(row["project_id"])
    project = config.project(project_id)
    if setting.endswith("scope.expected_books"):
        raw = prompt_for_value(
            label="Comma-separated USFM book codes or auto",
            input_stream=input_stream,
            output_stream=output_stream,
        )
        if raw.casefold() == "auto":
            return "auto"
        books = [item.strip().upper() for item in raw.split(",") if item.strip()]
        unknown = sorted(set(books) - set(BOOK_ORDER))
        if not books or unknown:
            raise InputRequiredError(
                "Expected one or more valid USFM book codes",
                code="INVALID_EXPECTED_BOOKS",
                received=raw,
                suggestions=[],
                next_action="Enter comma-separated canonical USFM book codes or auto.",
                details={"unknown_books": unknown},
            )
        return books
    if setting.endswith("versification.custom_file"):
        choices = ["auto", "none"]
        if project.path.is_dir():
            choices.extend(
                path.name
                for path in sorted(project.path.glob("*.vrs"))
                if path.is_file() and path.name not in choices
            )
        return _choose(
            "Custom VRS setting",
            choices,
            input_stream=input_stream,
            output_stream=output_stream,
        )
    return prompt_for_value(
        label="Explicit setting value",
        input_stream=input_stream,
        output_stream=output_stream,
    )


def _review_auto_settings(
    config: EcosystemConfig,
    overrides: dict[str, Any],
    resolutions: list[dict[str, Any]],
    *,
    required_only: bool,
    project_ids: set[str] | None = None,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    """Present unresolved automatic settings and persist only confirmed effective choices."""
    changed = False
    rows = resolve_auto_settings(config)
    for row in rows:
        if project_ids is not None and str(row.get("project_id")) not in project_ids:
            continue
        if required_only and row.get("resolution_status") == "ACCEPTED":
            continue
        setting = str(row["setting"])
        explicit = _explicit_auto_value(row)
        print("", file=output_stream)
        print(f"{prompt_text('prompt.auto_setting', 'Auto setting')}: {setting}", file=output_stream)
        print(f"{prompt_text('prompt.proposed_value', 'Proposed value')}: {row.get('resolved_summary', row.get('resolved'))}", file=output_stream)
        print(f"{prompt_text('prompt.basis', 'Basis')}: {row.get('source')} [{row.get('confidence')}]", file=output_stream)
        action = _choose(
            "Auto-resolution action",
            ("accept-explicit", "keep-auto", "edit", "cancel"),
            labels={
                "accept-explicit": "Accept detected value as an explicit effective override",
                "keep-auto": "Keep the source setting as auto",
                "edit": "Enter a different explicit value",
                "cancel": "Cancel INIT",
            },
            input_stream=input_stream,
            output_stream=output_stream,
        )
        if action == "cancel":
            raise OperatorCancelledError("Operator cancelled INIT auto-resolution review")
        if action == "keep-auto":
            _record(
                resolutions,
                setting=setting,
                original="auto",
                resolved="auto",
                method="OPERATOR_CONFIRMED_AUTO",
            )
            continue
        resolved = explicit if action == "accept-explicit" else _alternative_auto_value(
            config,
            row,
            input_stream=input_stream,
            output_stream=output_stream,
        )
        if not confirm_correction(
            "auto",
            str(resolved),
            label=setting,
            input_stream=input_stream,
            output_stream=output_stream,
        ):
            raise OperatorCancelledError("Operator declined the INIT setting correction")
        _set_nested(overrides, setting, resolved)
        _record(
            resolutions,
            setting=setting,
            original="auto",
            resolved=resolved,
            method="OPERATOR_CONFIRMED_OVERRIDE",
        )
        changed = True
    return changed


def _parse_roles(raw: str) -> list[str]:
    """Normalise and validate the project roles selected during guided INIT."""
    roles = [item.strip().upper() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(roles) - PROJECT_ROLE_VALUES)
    if not roles or unknown:
        raise InputRequiredError(
            "Project roles must be a non-empty comma-separated list of registered roles",
            code="INVALID_PROJECT_ROLES",
            received=raw,
            suggestions=[],
            next_action="Enter only valid Job binding roles.",
            details={"unknown_roles": unknown, "valid_roles": sorted(PROJECT_ROLE_VALUES)},
        )
    return roles


def _edit_project(
    config: EcosystemConfig,
    project: ProjectSpec,
    overrides: dict[str, Any],
    resolutions: list[dict[str, Any]],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    """Review one project binding and stage confirmed effective changes in the sidecar."""
    # Stage confirmed changes in the sidecar only; never mutate the source settings document.
    changed = False
    while True:
        field = _choose(
            f"{project.project_id} setting to edit",
            (
                "enabled",
                "content_state",
                "testament",
                "canon",
                "expected_books",
                "roles",
                "base_file",
                "custom_file",
                "language_profile",
                "profile_variant",
                "done",
            ),
            input_stream=input_stream,
            output_stream=output_stream,
        )
        if field == "done":
            return changed
        setting = f"projects.{project.project_id}."
        if field == "enabled":
            original: Any = project.enabled
            raw = _choose("Enabled", ("true", "false"), input_stream=input_stream, output_stream=output_stream)
            resolved: Any = raw == "true"
            setting += "enabled"
        elif field == "content_state":
            original = project.content_state
            resolved = _choose(
                "Content state",
                ("LOCKED", "UNDER_REVIEW"),
                input_stream=input_stream,
                output_stream=output_stream,
            )
            setting += "content_state"
        elif field == "testament":
            original = project.scope.testament
            resolved = _choose(
                "Testament scope",
                sorted(TESTAMENT_VALUES),
                input_stream=input_stream,
                output_stream=output_stream,
            )
            setting += "scope.testament"
        elif field == "canon":
            original = project.scope.canon
            resolved = _choose(
                "Canon",
                sorted(CANON_VALUES),
                input_stream=input_stream,
                output_stream=output_stream,
            )
            setting += "scope.canon"
        elif field == "expected_books":
            original = project.scope.expected_books
            raw = prompt_for_value(
                label="Expected books (auto or comma-separated USFM codes)",
                input_stream=input_stream,
                output_stream=output_stream,
            )
            if raw.casefold() == "auto":
                resolved = "auto"
            else:
                books = [item.strip().upper() for item in raw.split(",") if item.strip()]
                unknown = sorted(set(books) - set(BOOK_ORDER))
                if not books or unknown:
                    raise InputRequiredError(
                        "Expected books contain invalid USFM codes",
                        code="INVALID_EXPECTED_BOOKS",
                        received=raw,
                        suggestions=[],
                        next_action="Enter auto or comma-separated canonical USFM book codes.",
                        details={"unknown_books": unknown},
                    )
                resolved = books
            setting += "scope.expected_books"
        elif field == "roles":
            original = list(project.scope.roles)
            raw = prompt_for_value(
                label="Comma-separated project roles",
                input_stream=input_stream,
                output_stream=output_stream,
            )
            resolved = _parse_roles(raw)
            setting += "scope.roles"
        elif field == "base_file":
            original = project.versification.base_file
            resolved = _choose(
                "Base VRS file",
                sorted(config.base_vrs_files),
                input_stream=input_stream,
                output_stream=output_stream,
            )
            setting += "versification.base_file"
        elif field == "custom_file":
            original = project.versification.custom_file
            choices = ["auto", "none"]
            if project.path.is_dir():
                choices.extend(
                    path.name for path in sorted(project.path.glob("*.vrs")) if path.is_file()
                )
            resolved = _choose(
                "Custom VRS file",
                tuple(dict.fromkeys(choices)),
                input_stream=input_stream,
                output_stream=output_stream,
            )
            setting += "versification.custom_file"
        elif field == "language_profile":
            original = project.language_profile
            resolved = _choose(
                "Language profile",
                sorted(config.language_profiles),
                input_stream=input_stream,
                output_stream=output_stream,
            )
            setting += "language.profile"
            _set_nested(overrides, f"projects.{project.project_id}.language.code", resolved)
        elif field == "profile_variant":
            original = project.profile_variant or ""
            namespace = config.language_profile(project.language_profile)
            choices = ["none", *sorted(namespace.variants)]
            selected = _choose(
                "Profile variant",
                choices,
                input_stream=input_stream,
                output_stream=output_stream,
            )
            resolved = "" if selected == "none" else selected
            setting += "language.variant"
        else:
            raise AssertionError(field)
        if str(original) == str(resolved):
            print(prompt_text("prompt.no_change", "No change recorded."), file=output_stream)
            continue
        if not confirm_correction(
            str(original),
            str(resolved),
            label=setting,
            input_stream=input_stream,
            output_stream=output_stream,
        ):
            continue
        _set_nested(overrides, setting, resolved)
        _record(
            resolutions,
            setting=setting,
            original=original,
            resolved=resolved,
            method="OPERATOR_CONFIRMED_OVERRIDE",
        )
        changed = True


def _review_projects(
    config: EcosystemConfig,
    overrides: dict[str, Any],
    resolutions: list[dict[str, Any]],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> tuple[bool, dict[str, str]]:
    """Review only projects required by the current task or explicit INIT scope."""
    changed = False
    decisions: dict[str, str] = {}
    for project_id, project in sorted(config.projects.items()):
        print("", file=output_stream)
        print(
            f"{project_id}: language={project.language_code}/{project.profile_ref}; "
            f"enabled={str(project.enabled).lower()}; state={project.content_state}; "
            f"scope={project.scope.testament}/{project.scope.canon}; "
            f"roles={','.join(project.scope.roles)}",
            file=output_stream,
        )
        action = _choose(
            f"{project_id} review action",
            ("accept", "edit", "skip", "cancel"),
            labels={
                "accept": "Accept the effective declaration",
                "edit": "Edit one or more effective settings",
                "skip": "Leave unresolved for later review",
                "cancel": "Cancel INIT",
            },
            input_stream=input_stream,
            output_stream=output_stream,
        )
        if action == "cancel":
            raise OperatorCancelledError("Operator cancelled project INIT review")
        if action == "edit":
            changed = _edit_project(
                config,
                project,
                overrides,
                resolutions,
                input_stream=input_stream,
                output_stream=output_stream,
            ) or changed
            decisions[project_id] = "EDITED"
        elif action == "accept":
            decisions[project_id] = "ACCEPTED"
        else:
            decisions[project_id] = "NOT_ANSWERED"
    return changed, decisions


def run_guided_init_remediation(
    config: EcosystemConfig,
    *,
    full_project_review: bool,
    required_only: bool = False,
    input_stream: TextIO,
    output_stream: TextIO,
) -> dict[str, Any]:
    """Review recoverable INIT settings and persist only confirmed overrides."""
    overrides, resolutions = _existing_override_data(config)
    changed = _review_configured(
        config,
        overrides,
        resolutions,
        input_stream=input_stream,
        output_stream=output_stream,
    )
    changed = _review_auto_settings(
        config,
        overrides,
        resolutions,
        required_only=required_only,
        project_ids=None,
        input_stream=input_stream,
        output_stream=output_stream,
    ) or changed
    project_decisions: dict[str, str] = {}
    if full_project_review:
        project_changed, project_decisions = _review_projects(
            config,
            overrides,
            resolutions,
            input_stream=input_stream,
            output_stream=output_stream,
        )
        changed = project_changed or changed
    path: Path | None = config.operator_overrides_path
    if changed:
        candidate_path = operator_override_path(config.settings_path)
        prior_bytes = candidate_path.read_bytes() if candidate_path.is_file() else None
        path = write_operator_overrides(config.settings_path, overrides, resolutions)
        try:
            from .registry import load_ecosystem

            load_ecosystem(config.settings_path)
        except SageError as exc:
            if prior_bytes is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(prior_bytes)
            raise InputRequiredError(
                f"The proposed INIT correction did not produce a valid effective configuration: {exc}",
                code="INIT_OVERRIDE_VALIDATION_FAILED",
                received=overrides,
                suggestions=[],
                next_action="Review the affected setting and choose a compatible value.",
                details={"underlying_reason_code": exc.code},
            ) from exc
    return {
        "changed": changed,
        "operator_overrides_path": str(path) if path else str(operator_override_path(config.settings_path)),
        "operator_resolutions": resolutions,
        "project_decisions": project_decisions,
    }


def run_targeted_init_remediation(
    config: EcosystemConfig,
    *,
    project_ids: Iterable[str],
    input_stream: TextIO,
    output_stream: TextIO,
) -> dict[str, Any]:
    """Remediate only requirements needed by the requested runtime scope.

    This path is intentionally narrow: it may mark the effective ecosystem
    configured, enable explicitly selected SAGE Projects, and review
    unresolved auto settings for those projects. It never rewrites the source
    settings file and never changes Scripture content.
    """
    selected = tuple(dict.fromkeys(str(item) for item in project_ids if str(item)))
    unknown = sorted(set(selected) - set(config.projects))
    if unknown:
        raise InputRequiredError(
            "Targeted INIT remediation received unknown projects",
            code="UNKNOWN_PROJECT_ID",
            received=unknown,
            suggestions=[],
            next_action="Correct the project identifiers before INIT remediation.",
        )
    # Apply only task-scoped overrides here so guided remediation cannot silently
    # broaden the active project set or mutate unrelated project declarations.
    overrides, resolutions = _existing_override_data(config)
    changed = _review_configured(
        config,
        overrides,
        resolutions,
        input_stream=input_stream,
        output_stream=output_stream,
    )
    for project_id in selected:
        project = config.project(project_id)
        if project.enabled:
            continue
        print("", file=output_stream)
        print(
            prompt_text(
                "prompt.project_disabled",
                "Project {project_id} is registered but disabled in the effective configuration.",
            ).format(project_id=project_id),
            file=output_stream,
        )
        if not _yes_no(
            f"Enable {project_id} for this effective SAGE configuration?",
            default=True,
            input_stream=input_stream,
            output_stream=output_stream,
        ):
            raise InputRequiredError(
                f"Project {project_id} remains disabled",
                code="PROJECT_ENABLEMENT_REQUIRED",
                received=project_id,
                suggestions=[
                    {
                        "value": project_id,
                        "label": f"Enable SAGE Project {project_id} through guided INIT",
                        "score": 1.0,
                        "confidence": "AUTHORITATIVE",
                    }
                ],
                next_action="Run `./sage project init` or repeat interactively and enable the project.",
            )
        setting = f"projects.{project_id}.enabled"
        _set_nested(overrides, setting, True)
        _record(
            resolutions,
            setting=setting,
            original=False,
            resolved=True,
            method="OPERATOR_CONFIRMED_RUNTIME_REMEDIATION",
        )
        changed = True
    changed = _review_auto_settings(
        config,
        overrides,
        resolutions,
        required_only=True,
        project_ids=set(selected),
        input_stream=input_stream,
        output_stream=output_stream,
    ) or changed
    path: Path | None = config.operator_overrides_path
    if changed:
        candidate_path = operator_override_path(config.settings_path)
        prior_bytes = candidate_path.read_bytes() if candidate_path.is_file() else None
        path = write_operator_overrides(config.settings_path, overrides, resolutions)
        try:
            from .registry import load_ecosystem

            effective = load_ecosystem(config.settings_path)
            for project_id in selected:
                if not effective.project(project_id).enabled:
                    raise InputRequiredError(
                        f"Project {project_id} was not enabled by the proposed correction",
                        code="INIT_OVERRIDE_VALIDATION_FAILED",
                        received=project_id,
                        suggestions=[],
                        next_action="Review the governed operator override sidecar.",
                    )
        except SageError as exc:
            if prior_bytes is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(prior_bytes)
            raise InputRequiredError(
                f"The proposed runtime correction did not produce a valid effective configuration: {exc}",
                code="INIT_OVERRIDE_VALIDATION_FAILED",
                received={"projects": list(selected)},
                suggestions=[],
                next_action="Review the affected INIT setting and choose a compatible value.",
                details={"underlying_reason_code": exc.code},
            ) from exc
    return {
        "changed": changed,
        "operator_overrides_path": str(path) if path else str(operator_override_path(config.settings_path)),
        "operator_resolutions": resolutions,
        "projects": list(selected),
    }
