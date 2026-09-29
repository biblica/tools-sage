"""Validate reusable NCA number-style guides and assess exact presentation."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import re
import unicodedata
from typing import Any, Optional

import yaml

from sage.atomic import atomic_write_bytes
from sage.errors import ConfigurationError, ValidationError
from sage.language_codes import canonical_language_tag, canonical_script_code
from sage.registry import EcosystemConfig
from sage.storage import storage_layout
from .models import freeze

RULE_AREAS = ('digits', 'bands', 'grouping', 'decimal', 'ordinals', 'fractions', 'ranges', 'qualifiers', 'contexts', 'units')
CONTEXTS = ('ages', 'dates', 'time', 'money', 'measurements', 'counts', 'genealogies')
FORMS = frozenset({'WORDS', 'DIGITS', 'WORDS_AND_DIGITS'})
STATUSES = frozenset({'CONFIGURED', 'NOT_SPECIFIED', 'NOT_APPLICABLE'})


def _invalid(message: str) -> ValidationError:
    """Return a stable profile-remediation error without inventing defaults."""
    return ValidationError(message, code='NCA_STYLE_PROFILE_INVALID', next_action='Configure or import a complete compatible NCA Number Style Profile.')


def _plain(value: Any) -> Any:
    """Copy frozen profile data into a local assessment-only working structure."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _number(value: object) -> Fraction:
    """Parse an exact nonnegative rule boundary, disallowing floats and booleans."""
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?', value):
        raise _invalid('Number-style boundaries must use exact nonnegative integer/fraction strings.')
    return Fraction(value)


def _validate_area(area: str, rule: Mapping[str, Any]) -> None:
    """Validate configured rule semantics independently of profile selection."""
    if rule.get('status') not in STATUSES:
        raise _invalid(f'Invalid rule status for {area}.')
    if rule['status'] != 'CONFIGURED':
        return
    if area == 'digits':
        alphabets = rule.get('allowed')
        if not isinstance(alphabets, (list, tuple)) or not alphabets or rule.get('preferred') not in alphabets:
            raise _invalid('Digit rules require a preferred and explicit allowed alphabet.')
        for alphabet in alphabets:
            if not isinstance(alphabet, str) or len(alphabet) != 10:
                raise _invalid('A digit alphabet must contain exactly ten decimal characters.')
            try:
                if [unicodedata.decimal(char) for char in alphabet] != list(range(10)):
                    raise _invalid('Digit alphabets must list decimal values zero to nine in order.')
            except ValueError as exc:
                raise _invalid('A digit alphabet contains a non-decimal character.') from exc
    elif area == 'bands':
        bands = rule.get('bands')
        if not isinstance(bands, (list, tuple)) or not bands:
            raise _invalid('Number bands must be a nonempty list.')
        previous: Optional[Fraction] = Fraction(-1)
        for band in bands:
            if not isinstance(band, Mapping) or band.get('form') not in FORMS:
                raise _invalid('Each number band requires a configured presentation form.')
            low = _number(band.get('min'))
            high = None if band.get('max') is None else _number(band['max'])
            if previous is None or low <= previous or (high is not None and high < low):
                raise _invalid('Number bands overlap or are out of order.')
            previous = high
    elif area == 'grouping':
        if rule.get('style') not in {'WESTERN', 'INDIC', 'NONE'}:
            raise _invalid('Grouping must be WESTERN, INDIC or NONE.')
        separator = rule.get('separator')
        if not isinstance(separator, str) or (rule['style'] != 'NONE' and len(separator) != 1):
            raise _invalid('Grouping requires the exact separator character.')
        if any(char.isdecimal() for char in separator):
            raise _invalid('Grouping separators cannot be digits.')
        _number(rule.get('minimum'))
    elif area == 'decimal':
        separator = rule.get('separator')
        if not isinstance(separator, str) or len(separator) != 1 or separator.isdecimal():
            raise _invalid('Decimal convention requires one non-digit separator.')
    elif area == 'ordinals':
        if rule.get('form') not in FORMS:
            raise _invalid('Ordinal rules require a presentation form.')
        if 'suffixes' in rule and (not isinstance(rule['suffixes'], (list, tuple)) or any(not isinstance(x, str) or not x for x in rule['suffixes'])):
            raise _invalid('Ordinal suffixes must be literal nonempty strings.')
    elif area == 'fractions':
        if rule.get('notation') not in {'WORDS', 'SLASH', 'UNICODE'}:
            raise _invalid('Fraction rules require WORDS, SLASH or UNICODE notation.')
        forms = rule.get('forms', {})
        if not isinstance(forms, Mapping) or (rule['notation'] == 'UNICODE' and not forms):
            raise _invalid('Unicode fractions require explicit value-to-glyph forms.')
        for value, glyph in forms.items():
            _number(value)
            if not isinstance(glyph, str) or not glyph:
                raise _invalid('Fraction forms must be nonempty literal strings.')
    elif area == 'ranges':
        if not isinstance(rule.get('separator'), str) or not rule['separator']:
            raise _invalid('Range rules require an exact separator.')
    elif area == 'qualifiers':
        forms = rule.get('forms')
        if not isinstance(forms, Mapping) or not forms:
            raise _invalid('Qualifier rules require explicit literal forms.')
        for qualifier, labels in forms.items():
            if qualifier not in {'ABOUT', 'LESS_THAN', 'MORE_THAN'} or not isinstance(labels, (list, tuple)) or not labels or any(not isinstance(x, str) or not x for x in labels):
                raise _invalid('Invalid qualifier presentation forms.')
    elif area == 'contexts':
        decisions = rule.get('decisions')
        if not isinstance(decisions, Mapping) or set(decisions) != set(CONTEXTS):
            raise _invalid('Every supported context requires an explicit decision.')
        for decision in decisions.values():
            if not isinstance(decision, Mapping) or decision.get('status') not in {'INHERIT', 'OVERRIDE', 'NOT_SPECIFIED', 'NOT_APPLICABLE'}:
                raise _invalid('Invalid context decision.')
            if decision['status'] == 'OVERRIDE':
                overrides = decision.get('rules')
                if not isinstance(overrides, Mapping) or not overrides or set(overrides) - {'bands', 'grouping', 'units'}:
                    raise _invalid('Context overrides require explicit band, grouping or unit rules.')
                for name, override in overrides.items():
                    if not isinstance(override, Mapping):
                        raise _invalid('A context override must be a rule mapping.')
                    _validate_area(name, {**override, 'status': 'CONFIGURED'})
    elif area == 'units':
        locations = rule.get('locations')
        if not isinstance(locations, Mapping) or set(locations) != {'body', 'heading', 'footnote'}:
            raise _invalid('Unit style must specify body, heading and footnote decisions.')
        for value in locations.values():
            if not isinstance(value, Mapping) or value.get('status') not in STATUSES:
                raise _invalid('Unit location requires an explicit rule status.')
            if value['status'] != 'CONFIGURED':
                continue
            if value.get('form') not in {'FULL', 'ABBREVIATION'} or value.get('spacing') not in {'SPACE', 'NONE'}:
                raise _invalid('Unit location requires form and spacing rules.')
            aliases = value.get('forms')
            if not isinstance(aliases, Mapping) or not aliases:
                raise _invalid('Unit style requires explicit approved unit forms.')
            for labels in aliases.values():
                if not isinstance(labels, (list, tuple)) or not labels or any(not isinstance(x, str) or not x for x in labels):
                    raise _invalid('Approved unit forms must be literal strings.')


def validate_style_profile(raw: Optional[Mapping[str, object]], *, language: Optional[str] = None,
                           script: Optional[str] = None, project: Optional[str] = None) -> Mapping[str, object]:
    """Validate a selected guide or prepare an internal context with no style rules."""
    if raw is None:
        return freeze({'profile': {'status': 'NOT_CONFIGURED'}, 'rules': {
            area: {'id': 'NCA_UNCONFIGURED_' + area.upper(), 'status': 'NOT_SPECIFIED'}
            for area in RULE_AREAS
        }})
    if not isinstance(raw, Mapping) or raw.get('schema_version') != '1.0':
        raise _invalid('Missing or unsupported number-style schema version.')
    profile, rules = raw.get('profile'), raw.get('rules')
    required = {'id', 'version', 'language', 'script', 'projects', 'source_guide', 'recorded_by', 'recorded_date', 'status'}
    if not isinstance(profile, Mapping) or not required <= set(profile):
        raise _invalid('Number-style profile metadata is incomplete.')
    for key in required - {'projects'}:
        if not isinstance(profile[key], str) or not profile[key].strip():
            raise _invalid(f'Number-style profile {key} must be nonempty.')
    if profile['status'] != 'CONFIGURED':
        raise _invalid('A draft number-style template is not a selectable profile.')
    for key in ('id', 'version'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', profile[key]):
            raise _invalid(f'Invalid number-style profile {key}.')
    try:
        date.fromisoformat(profile['recorded_date'])
    except ValueError as exc:
        raise _invalid('Number-style recorded_date must be an ISO date.') from exc
    try:
        profile_language = canonical_language_tag(profile['language'], 'number-style language')
        profile_script = canonical_script_code(profile['script'], 'number-style script')
        requested_language = canonical_language_tag(language, 'Project language') if language else None
        requested_script = canonical_script_code(script, 'Project script') if script else None
    except ConfigurationError as exc:
        raise _invalid(exc.message) from exc
    projects = profile['projects']
    if not isinstance(projects, (list, tuple)) or not projects or any(not isinstance(p, str) or not p for p in projects):
        raise _invalid('Number-style applicability requires Projects or an explicit wildcard.')
    if requested_language and profile_language != requested_language:
        raise _invalid('Number-style profile language is incompatible with the Project.')
    if requested_script and profile_script != requested_script:
        raise _invalid('Number-style profile script is incompatible with the Project.')
    if project and '*' not in projects and project not in projects:
        raise _invalid('Number-style profile is not applicable to this Project.')
    if not isinstance(rules, Mapping) or set(rules) != set(RULE_AREAS):
        raise _invalid('Every number-style rule area requires an explicit decision.')
    ids: set[str] = set()
    for area in RULE_AREAS:
        rule = rules[area]
        if not isinstance(rule, Mapping) or not isinstance(rule.get('id'), str) or not rule['id'].strip() or rule['id'] in ids:
            raise _invalid('Number-style rules require distinct stable IDs.')
        ids.add(rule['id'])
        _validate_area(area, rule)
    grouping, decimal = rules['grouping'], rules['decimal']
    if grouping['status'] == decimal['status'] == 'CONFIGURED' and grouping.get('separator') == decimal['separator']:
        raise _invalid('Grouping and decimal separators cannot be ambiguous.')
    contexts = rules['contexts']
    if contexts['status'] == 'CONFIGURED' and decimal['status'] == 'CONFIGURED':
        for decision in contexts['decisions'].values():
            override = decision.get('rules', {}).get('grouping')
            if override and override.get('separator') == decimal['separator']:
                raise _invalid('A context override makes grouping and decimal separators ambiguous.')
    return freeze(raw)


@dataclass(frozen=True)
class StyleProfile:
    """One validated guide with exact import/snapshot bytes and content identity."""

    path: Path
    document: Mapping[str, object]
    sha256: str
    content_bytes: bytes

    @property
    def selector(self) -> str:
        """Return the stable profile ID/version used by Job bindings."""
        metadata = self.document['profile']
        return f"{metadata['id']}/{metadata['version']}"


class _ProfileLoader(yaml.SafeLoader):
    """Parse profile mappings without silently accepting duplicate YAML keys."""


def _unique_mapping(loader: _ProfileLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    """Reject duplicate fields instead of choosing one of conflicting rules."""
    result: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise _invalid(f'Duplicate number-style YAML key: {key}.')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_ProfileLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_style_profile(path: Path, *, language: Optional[str] = None,
                       script: Optional[str] = None, project: Optional[str] = None) -> StyleProfile:
    """Read, validate and fingerprint one exact profile without changing it."""
    try:
        data = path.read_bytes()
        if len(data) > 2 * 1024 * 1024:
            raise _invalid('Number-style profile exceeds the supported size.')
        raw = yaml.load(data.decode('utf-8-sig'), Loader=_ProfileLoader)
        if raw is None:
            raise _invalid('An imported number-style guide must contain a configured profile.')
        document = validate_style_profile(raw, language=language, script=script, project=project)
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, RecursionError) as exc:
        raise _invalid(f'Cannot read number-style profile: {path.name}.') from exc
    return StyleProfile(path.resolve(), document, sha256(data).hexdigest(), data)


def _profile_library(config: EcosystemConfig) -> Path:
    """Use the existing Operator style-guide storage surface."""
    return storage_layout(config.root).styleguides_root / 'numbers'


def import_style_profile(config: EcosystemConfig, source: Path) -> Path:
    """Import unchanged configured guide bytes without overwriting a version."""
    from sage.locking import WorkspaceLock

    profile = load_style_profile(source)
    library = _profile_library(config)
    destination = library / (profile.selector + '.yml')
    if library.is_symlink() or not destination.resolve().is_relative_to(library.resolve()):
        raise _invalid('Number-style destination escapes its local library.')
    layout = storage_layout(config.root)
    with WorkspaceLock(layout.locks_root / 'number-style-import.lock', 'NCA_STYLE_IMPORT'):
        if destination.exists():
            if destination.read_bytes() != profile.content_bytes:
                raise ValidationError('This number-style ID/version already has different content.', code='NCA_STYLE_PROFILE_CONFLICT', next_action='Import the changed guide under a new version.')
            return destination.resolve()
        atomic_write_bytes(destination, profile.content_bytes)
    return destination.resolve()


def style_profile_candidates(config: EcosystemConfig, *, language: str, script: str,
                             project: Optional[str] = None) -> tuple[StyleProfile, ...]:
    """List compatible configured guides without selecting among alternatives."""
    library = _profile_library(config)
    if library.is_symlink():
        raise _invalid('Number-style library must not be a symlink.')
    candidates: list[StyleProfile] = []
    for path in sorted(library.glob('*/*.yml')):
        if path.is_symlink() or not path.resolve().is_relative_to(library.resolve()):
            continue
        try:
            item = load_style_profile(path, language=language, script=script, project=project)
        except ValidationError:
            continue
        if path.relative_to(library).with_suffix('').as_posix() == item.selector:
            candidates.append(item)
    return tuple(candidates)


def resolve_style_profile(config: EcosystemConfig, selector: Optional[str], *, language: str,
                          script: str, project: Optional[str] = None) -> Optional[StyleProfile]:
    """Resolve an explicitly selected guide; omission never grants a guide authority."""
    if selector is not None:
        if not isinstance(selector, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,63}', selector):
            raise _invalid('Number-style selector must be an imported profile ID/version.')
        library = _profile_library(config)
        path = library / (selector + '.yml')
        if path.is_symlink() or not path.resolve().is_relative_to(library.resolve()):
            raise _invalid('Number-style profile escapes the local library.')
        result = load_style_profile(path, language=language, script=script, project=project)
        if result.selector != selector:
            raise _invalid('Number-style selector and stored profile identity disagree.')
        return result
    return None
