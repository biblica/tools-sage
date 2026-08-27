"""Interactive correction, ranked suggestions, and structured input-remediation helpers."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, TextIO

from .errors import InputRequiredError, OperatorCancelledError
from .ui_format import menu_item


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_MISSING_REQUIRED_RE = re.compile(r"the following arguments are required: (?P<items>.+)$")
_UNRECOGNIZED_RE = re.compile(r"unrecognized arguments?: (?P<items>.+)$")

_PROMPT_RENDERER: Callable[[str], str] | None = None


def configure_prompt_renderer(renderer: Callable[[str], str] | None) -> None:
    """Set the localized prompt-label renderer for the active CLI configuration."""
    global _PROMPT_RENDERER
    _PROMPT_RENDERER = renderer


def prompt_text(key: str, fallback: str) -> str:
    """Return one configured prompt message or the stable English fallback."""
    if _PROMPT_RENDERER is None:
        return fallback
    value = _PROMPT_RENDERER(key)
    return value if value and value != key else fallback


# High-confidence operator typo hints. These are suggestions only and are never
# applied without explicit confirmation.
COMMON_VALUE_HINTS: dict[str, str] = {
    "bci": "bic",
    "swa": "saw",
    "jun": "JHN",
    "joh": "JHN",
    "john": "JHN",
    "selfcheck": "self_check",
    "self-check": "self_check",
    "aproved": "APPROVED_FOR_REWRITE",
}


@dataclass(frozen=True)
class Suggestion:
    """Represent one ranked correction candidate shown to the Operator."""

    value: str
    label: str
    score: float
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for reports and state files."""
        return {
            "value": self.value,
            "label": self.label,
            "score": round(self.score, 3),
            "confidence": self.confidence,
        }


class ArgumentChoiceProblem(Exception):
    """Record an invalid enumerated choice detected during argument parsing."""

    def __init__(self, parser: argparse.ArgumentParser, action: argparse.Action, value: str) -> None:
        """Initialize the instance with the supplied governed state."""
        super().__init__(value)
        self.parser = parser
        self.action = action
        self.value = value


class ArgumentSyntaxProblem(Exception):
    """Record malformed command syntax detected before controller execution."""

    def __init__(self, parser: argparse.ArgumentParser, message: str) -> None:
        """Initialize the instance with the supplied governed state."""
        super().__init__(message)
        self.parser = parser
        self.message = message


class GuidedArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that reports remediable problems instead of exiting."""

    def _check_value(self, action: argparse.Action, value: str) -> None:
        """Record invalid choice metadata instead of terminating before guidance can run."""
        if action.choices is not None and value not in action.choices:
            raise ArgumentChoiceProblem(self, action, value)

    def error(self, message: str) -> None:
        """Record one parse error without immediately aborting correction analysis."""
        raise ArgumentSyntaxProblem(self, message)


def normalize_value(value: str) -> str:
    """Normalize an Operator token for conservative fuzzy comparison."""
    return _NORMALIZE_RE.sub("", str(value).casefold())


def _confidence(score: float, *, explicit_hint: bool = False) -> str:
    """Map a similarity score to the governed LOW, MEDIUM, or HIGH confidence label."""
    if explicit_hint or score >= 0.86:
        return "HIGH"
    if score >= 0.68:
        return "MEDIUM"
    return "LOW"


def rank_suggestions(
    received: str,
    choices: Iterable[str],
    *,
    labels: Mapping[str, str] | None = None,
    aliases: Mapping[str, Iterable[str]] | None = None,
    limit: int = 3,
    minimum_score: float = 0.50,
) -> list[Suggestion]:
    """Return conservative ranked alternatives for one invalid value."""
    labels = labels or {}
    aliases = aliases or {}
    source = normalize_value(received)
    hinted = COMMON_VALUE_HINTS.get(source)
    results: list[Suggestion] = []
    for raw_choice in choices:
        choice = str(raw_choice)
        label = str(labels.get(choice, choice))
        candidate_tokens = {normalize_value(choice), normalize_value(label)}
        candidate_tokens.update(normalize_value(item) for item in aliases.get(choice, ()))
        scores = [SequenceMatcher(None, source, token).ratio() for token in candidate_tokens if token]
        score = max(scores or [0.0])
        explicit_hint = hinted is not None and normalize_value(hinted) == normalize_value(choice)
        if explicit_hint:
            score = max(score, 0.99)
        if source and source == normalize_value(choice):
            score = 1.0
        if score >= minimum_score:
            results.append(
                Suggestion(
                    value=choice,
                    label=label,
                    score=score,
                    confidence=_confidence(score, explicit_hint=explicit_hint),
                )
            )
    results.sort(key=lambda item: (-item.score, item.value.casefold()))
    return results[: max(1, limit)]


def suggestions_payload(items: Sequence[Suggestion]) -> list[dict[str, Any]]:
    """Serialize ranked correction suggestions for JSON and prompt consumers."""
    return [item.to_dict() for item in items]


def prompts_allowed(argv: Sequence[str] | None = None) -> bool:
    """Return whether the current invocation may ask the Operator for input."""
    values = list(sys.argv[1:] if argv is None else argv)
    if "--no-prompt" in values or "--json" in values or "--non-interactive" in values:
        return False
    forced = os.environ.get("SAGE_FORCE_INTERACTIVE", "").strip().lower()
    if forced in {"1", "true", "yes", "on"}:
        return True
    if forced in {"0", "false", "no", "off"}:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_for_value(
    *,
    label: str,
    received: str | None = None,
    suggestions: Sequence[Suggestion] = (),
    attempts_remaining: int = 3,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> str:
    """Prompt for one corrected value and require an explicit Operator choice."""
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stderr
    if received is not None:
        print(prompt_text("prompt.value_not_recognised", "{label} {received} was not recognized.").format(label=label, received=repr(received)), file=output_stream)
    else:
        print(prompt_text("prompt.value_required", "{label} is required.").format(label=label), file=output_stream)
    if suggestions:
        print("", file=output_stream)
        print(prompt_text("prompt.possible_corrections", "Possible corrections:"), file=output_stream)
        for index, suggestion in enumerate(suggestions, start=1):
            detail = suggestion.label
            if detail != suggestion.value:
                detail = f"{suggestion.value} - {detail}"
            print(menu_item(index, f"{detail} [{prompt_text('prompt.confidence', 'confidence')}={suggestion.confidence.lower()}]"), file=output_stream)
        enter_number = len(suggestions) + 1
        has_explicit_cancel = any(normalize_value(item.value) == "cancel" for item in suggestions)
        cancel_number = None if has_explicit_cancel else len(suggestions) + 2
        print(menu_item(enter_number, prompt_text('prompt.enter_another_value', 'Enter another value')), file=output_stream)
        if cancel_number is not None:
            print(menu_item(cancel_number, prompt_text('prompt.cancel', 'Cancel')), file=output_stream)
        while attempts_remaining > 0:
            output_stream.write(prompt_text("prompt.selection", "Selection: "))
            output_stream.flush()
            selected = input_stream.readline()
            if selected == "":
                raise OperatorCancelledError("Input stream closed during guided correction")
            selected = selected.strip()
            if selected.isdigit():
                number = int(selected)
                if 1 <= number <= len(suggestions):
                    return suggestions[number - 1].value
                if number == enter_number:
                    break
                if cancel_number is not None and number == cancel_number:
                    raise OperatorCancelledError("Operator cancelled guided correction")
            print(prompt_text("prompt.enter_listed_number", "Enter one listed number."), file=output_stream)
            attempts_remaining -= 1
    output_stream.write(prompt_text("prompt.enter_value", "Enter {label}: ").format(label=label.lower()))
    output_stream.flush()
    value = input_stream.readline()
    if value == "":
        raise OperatorCancelledError("Input stream closed during guided correction")
    value = value.strip()
    if not value:
        raise InputRequiredError(
            f"{label} must not be empty",
            code="EMPTY_OPERATOR_INPUT",
            received=value,
            suggestions=suggestions_payload(suggestions),
            next_action=f"Enter a valid {label.lower()} and retry.",
        )
    return value


def confirm_correction(
    original: str,
    corrected: str,
    *,
    label: str,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    """Require explicit confirmation before a correction affects execution."""
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stderr
    print(prompt_text("prompt.resolved_value", "Resolved {label}: {original} -> {corrected}").format(label=label, original=repr(original), corrected=repr(corrected)), file=output_stream)
    output_stream.write(prompt_text("prompt.use_correction", "Use this correction? [Y/n/edit] "))
    output_stream.flush()
    answer = input_stream.readline()
    if answer == "":
        raise OperatorCancelledError("Input stream closed during correction confirmation")
    normalized = answer.strip().casefold()
    if normalized in {"", "y", "yes"}:
        return True
    if normalized in {"n", "no", "cancel", "c"}:
        raise OperatorCancelledError("Operator rejected guided correction")
    return False


def _replace_argument_value(argv: list[str], action: argparse.Action, old: str, new: str) -> None:
    """Replace one canonical argument value while preserving the remaining command order."""
    if action.option_strings:
        for index, token in enumerate(argv):
            for option in action.option_strings:
                if token == option and index + 1 < len(argv) and argv[index + 1] == old:
                    argv[index + 1] = new
                    return
                prefix = option + "="
                if token.startswith(prefix) and token[len(prefix) :] == old:
                    argv[index] = prefix + new
                    return
    for index, token in enumerate(argv):
        if token == old:
            argv[index] = new
            return
    raise InputRequiredError(
        "Could not safely locate the invalid command value for correction",
        code="COMMAND_CORRECTION_LOCATION_UNKNOWN",
        received=old,
        next_action="Re-enter the command using the canonical syntax.",
    )


def _all_option_strings(parser: argparse.ArgumentParser) -> set[str]:
    """Collect every option spelling accepted by the active argparse action tree."""
    result: set[str] = set()
    visited: set[int] = set()

    def visit(item: argparse.ArgumentParser) -> None:
        """Inspect one parser node and collect supported command metadata."""
        if id(item) in visited:
            return
        visited.add(id(item))
        for action in item._actions:
            result.update(action.option_strings)
            choices = getattr(action, "choices", None)
            if isinstance(choices, Mapping):
                for child in choices.values():
                    if isinstance(child, argparse.ArgumentParser):
                        visit(child)

    visit(parser)
    return result


def _find_action(parser: argparse.ArgumentParser, dest_or_option: str) -> argparse.Action | None:
    """Locate the parser action that owns one invalid option or positional value."""
    for action in parser._actions:
        if action.dest == dest_or_option or dest_or_option in action.option_strings:
            return action
    return None


def _append_missing_value(
    argv: list[str],
    action: argparse.Action | None,
    item: str,
    value: str,
) -> None:
    """Insert a corrected value at the parser position that originally lacked it."""
    if item.startswith("--"):
        argv.extend([item, value])
        return
    argv.append(value)


def parse_args_with_guidance(
    parser: GuidedArgumentParser,
    argv: Sequence[str] | None = None,
    *,
    max_attempts: int = 3,
) -> argparse.Namespace:
    """Parse CLI arguments with interactive correction or structured failures."""
    # Parse, diagnose, and remediate in that order so corrected input is re-parsed canonically.
    values = list(sys.argv[1:] if argv is None else argv)
    interactive = prompts_allowed(values)
    corrections: list[dict[str, str]] = []
    attempts = 0
    while True:
        try:
            namespace = parser.parse_args(values)
            setattr(namespace, "_guided_interactive", interactive)
            setattr(namespace, "_input_corrections", corrections)
            setattr(namespace, "_canonical_argv", list(values))
            return namespace
        except ArgumentChoiceProblem as problem:
            choices = [str(item) for item in (problem.action.choices or ())]
            suggestions = rank_suggestions(problem.value, choices)
            if not interactive or attempts >= max_attempts:
                raise InputRequiredError(
                    f"Invalid value for {problem.action.dest}: {problem.value!r}",
                    code="INVALID_COMMAND_VALUE",
                    received=problem.value,
                    suggestions=suggestions_payload(suggestions),
                    next_action="Choose one valid value and rerun the command.",
                    details={"field": problem.action.dest, "valid_values": choices},
                )
            corrected = prompt_for_value(
                label=problem.action.dest.replace("_", " ").title(),
                received=problem.value,
                suggestions=suggestions,
                attempts_remaining=max_attempts - attempts,
            )
            if corrected != problem.value and not confirm_correction(
                problem.value,
                corrected,
                label=problem.action.dest.replace("_", " "),
            ):
                corrected = prompt_for_value(
                    label=problem.action.dest.replace("_", " ").title(),
                    received=problem.value,
                    suggestions=(),
                )
            _replace_argument_value(values, problem.action, problem.value, corrected)
            corrections.append(
                {"field": problem.action.dest, "original": problem.value, "resolved": corrected}
            )
            attempts += 1
        except ArgumentSyntaxProblem as problem:
            missing = _MISSING_REQUIRED_RE.search(problem.message)
            if missing:
                raw_items = [item.strip() for item in missing.group("items").split(",")]
                all_options = _all_option_strings(parser)
                unknown_options = [
                    token.split("=", 1)[0]
                    for token in values
                    if token.startswith("-") and token.split("=", 1)[0] not in all_options
                ]
                typo_candidate: tuple[str, str] | None = None
                for unknown in unknown_options:
                    ranked = rank_suggestions(unknown, [item for item in raw_items if item.startswith("--")])
                    if ranked and ranked[0].score >= 0.72:
                        typo_candidate = (unknown, ranked[0].value)
                        break
                if typo_candidate is not None:
                    unknown, corrected_option = typo_candidate
                    suggestion = Suggestion(
                        value=corrected_option,
                        label=corrected_option,
                        score=1.0,
                        confidence="HIGH",
                    )
                    if not interactive or attempts >= max_attempts:
                        raise InputRequiredError(
                            f"Unknown command option {unknown!r}",
                            code="UNKNOWN_COMMAND_OPTION",
                            received=unknown,
                            suggestions=[suggestion.to_dict()],
                            next_action=f"Replace {unknown} with {corrected_option} and retry.",
                        )
                    selected = prompt_for_value(
                        label="Command option",
                        received=unknown,
                        suggestions=[suggestion],
                        attempts_remaining=max_attempts - attempts,
                    )
                    for index, token in enumerate(values):
                        if token == unknown:
                            values[index] = selected
                            break
                        if token.startswith(unknown + "="):
                            values[index] = selected + token[len(unknown):]
                            break
                    corrections.append({"field": "option", "original": unknown, "resolved": selected})
                    attempts += 1
                    continue
                if not interactive or attempts >= max_attempts:
                    raise InputRequiredError(
                        problem.message,
                        code="MISSING_COMMAND_INPUT",
                        received=None,
                        suggestions=[],
                        next_action="Supply the missing command input and retry.",
                        details={"missing": raw_items},
                    )
                for item in raw_items:
                    action = _find_action(problem.parser, item.lstrip("-")) or _find_action(problem.parser, item)
                    choice_values = [str(value) for value in (action.choices or ())] if action else []
                    suggestions = [
                        Suggestion(value=value, label=value, score=1.0, confidence="AUTHORITATIVE")
                        for value in choice_values[:8]
                    ]
                    corrected = prompt_for_value(
                        label=item,
                        suggestions=suggestions,
                        attempts_remaining=max_attempts - attempts,
                    )
                    _append_missing_value(values, action, item, corrected)
                    corrections.append({"field": item, "original": "<missing>", "resolved": corrected})
                attempts += 1
                continue
            unrecognized = _UNRECOGNIZED_RE.search(problem.message)
            if unrecognized:
                tokens = shlex.split(unrecognized.group("items"))
                token = tokens[0] if tokens else ""
                options = sorted(_all_option_strings(parser))
                suggestions = rank_suggestions(token, options)
                if not interactive or attempts >= max_attempts:
                    raise InputRequiredError(
                        problem.message,
                        code="UNKNOWN_COMMAND_OPTION",
                        received=token,
                        suggestions=suggestions_payload(suggestions),
                        next_action="Use a recognized option and rerun the command.",
                    )
                corrected = prompt_for_value(
                    label="Command option",
                    received=token,
                    suggestions=suggestions,
                    attempts_remaining=max_attempts - attempts,
                )
                if not corrected.startswith("-"):
                    corrected = "--" + corrected.lstrip("-")
                for index, value in enumerate(values):
                    if value == token:
                        values[index] = corrected
                        break
                corrections.append({"field": "option", "original": token, "resolved": corrected})
                attempts += 1
                continue
            raise InputRequiredError(
                problem.message,
                code="INVALID_COMMAND_SYNTAX",
                received=None,
                suggestions=[],
                next_action="Review the command help, correct the input, and retry.",
            )


def resolve_from_choices(
    value: str,
    choices: Iterable[str],
    *,
    label: str,
    code: str,
    labels: Mapping[str, str] | None = None,
    aliases: Mapping[str, Iterable[str]] | None = None,
    interactive: bool = False,
    max_attempts: int = 3,
) -> tuple[str, dict[str, Any] | None]:
    """Resolve a dynamic identifier with prompting or a stable INPUT_REQUIRED error."""
    choice_values = [str(item) for item in choices]
    if value in choice_values:
        return value, None
    suggestions = rank_suggestions(
        value,
        choice_values,
        labels=labels,
        aliases=aliases,
    )
    if not interactive:
        raise InputRequiredError(
            f"Unknown {label.lower()}: {value!r}",
            code=code,
            received=value,
            suggestions=suggestions_payload(suggestions),
            next_action=f"Choose a registered {label.lower()} and retry.",
            details={
                "valid_value_count": len(choice_values),
                "valid_values": choice_values if len(choice_values) <= 12 else choice_values[:12],
                "valid_values_truncated": len(choice_values) > 12,
            },
        )
    current = value
    for _ in range(max_attempts):
        corrected = prompt_for_value(
            label=label,
            received=current,
            suggestions=suggestions,
        )
        if corrected in choice_values:
            if corrected != value and not confirm_correction(value, corrected, label=label.lower()):
                current = prompt_for_value(label=label, received=current, suggestions=())
                continue
            return corrected, {
                "field": label,
                "original": value,
                "resolved": corrected,
                "resolution": "OPERATOR_CONFIRMED",
            }
        current = corrected
        suggestions = rank_suggestions(
            current,
            choice_values,
            labels=labels,
            aliases=aliases,
        )
    raise InputRequiredError(
        f"No valid {label.lower()} was selected",
        code=code,
        received=current,
        suggestions=suggestions_payload(suggestions),
        next_action=f"Rerun and choose a registered {label.lower()}.",
    )


def suggest_existing_paths(value: str, candidates: Iterable[Path], *, limit: int = 3) -> list[Suggestion]:
    """Rank existing path candidates by filename and relative-path similarity."""
    paths = [Path(item) for item in candidates]
    labels = {str(path): path.name for path in paths}
    aliases = {str(path): (path.name, path.stem) for path in paths}
    return rank_suggestions(value, [str(path) for path in paths], labels=labels, aliases=aliases, limit=limit)
