"""CLI surface for local RWC/SEMDOM indexing and FLEx/Combine interchange."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .registry import load_ecosystem
from .semantic import (
    build_semantic_indexes,
    export_lift,
    import_greek_reference_xlsx,
    import_lift_snapshot,
    import_rwc_seed_xlsx,
    import_semdom_authority_json,
    import_specific_first_docx,
    semantic_status,
)
from .semantic.evidence import evidence_for_form
from .semantic.policy import EXPORT_VIEWS, REVIEW_STATES
from .semantic.store import (
    clear_review_state,
    load_bindings,
    load_import_selection,
    load_review_states,
    set_authority_selection,
    set_binding,
    set_import_active,
    set_review_state,
)


def _config(args: argparse.Namespace):
    """Load the configured SAGE ecosystem for one RWC command."""
    return load_ecosystem(Path(args.settings).expanduser().resolve())


def _emit(args: argparse.Namespace, title: str, payload: dict[str, Any]) -> int:
    """Render one deterministic RWC command result as text or JSON."""
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(title)
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
        else:
            print(f"{key}: {value}")
    return 0


def command_rwc_status(args: argparse.Namespace) -> int:
    """Show local RWC imports, bindings, authorities, and index coverage."""
    result = semantic_status(_config(args), language=args.language)
    result["bindings"] = load_bindings(_config(args))
    return _emit(args, "SAGE RWC / SEMDOM STATUS", result)


def command_rwc_lookup(args: argparse.Namespace) -> int:
    """Look up one exact indexed surface form locally without an AI call."""
    result = evidence_for_form(_config(args), language=args.language, form=args.form)
    return _emit(args, "SAGE RWC LOCAL LOOKUP", result)


def command_rwc_bind(args: argparse.Namespace) -> int:
    """Bind a project or resource identifier to a semantic language namespace."""
    config = _config(args)
    bindings = set_binding(config, project_id=args.project, language=args.language)
    return _emit(
        args,
        "SAGE RWC PROJECT BINDING",
        {"project": args.project, "semantic_language": args.language, "bindings": bindings},
    )


def command_rwc_import_seed(args: argparse.Namespace) -> int:
    """Import one immutable RWC seed workbook."""
    result = import_rwc_seed_xlsx(
        _config(args),
        Path(args.file),
        source_id=args.source_id,
        language=args.language,
        analysis_language=args.analysis_language,
        sheet=args.sheet,
        headword_column=args.headword_column,
        gloss_column=args.gloss_column,
        key_term_column=args.key_term_column,
        semdom_column=args.semdom_column,
    )
    return _emit(args, "SAGE RWC SEED IMPORT", result)


def command_rwc_import_greek(args: argparse.Namespace) -> int:
    """Import form-level Greek biblical reference evidence."""
    result = import_greek_reference_xlsx(
        _config(args),
        Path(args.file),
        source_id=args.source_id,
        language=args.language,
        sheet=args.sheet,
    )
    return _emit(args, "SAGE GREEK SEMANTIC REFERENCE IMPORT", result)


def command_rwc_import_selection(args: argparse.Namespace) -> int:
    """Activate or deactivate one immutable RWC/lexical import snapshot."""
    active = set_import_active(
        _config(args),
        language=args.language,
        source_id=args.source_id,
        active=args.import_state == "activate",
    )
    return _emit(
        args,
        "SAGE RWC IMPORT SELECTION",
        {"language": args.language, "source_id": args.source_id, "state": args.import_state.upper(), "active_imports": active},
    )


def command_rwc_import_lift(args: argparse.Namespace) -> int:
    """Import one immutable FLEx or Combine LIFT snapshot."""
    result = import_lift_snapshot(
        _config(args),
        Path(args.file),
        source_id=args.source_id,
        source_application=args.application,
        language=args.language,
    )
    return _emit(args, f"SAGE {args.application} LIFT IMPORT", result)


def command_rwc_authority_semdom(args: argparse.Namespace) -> int:
    """Import one operator-supplied SIL Semantic Domains authority snapshot."""
    result = import_semdom_authority_json(
        _config(args), Path(args.file), source_id=args.source_id
    )
    return _emit(args, "SAGE SIL SEMDOM AUTHORITY IMPORT", result)


def command_rwc_authority_folders(args: argparse.Namespace) -> int:
    """Import RapidWords specific-first folder metadata for local retrieval."""
    result = import_specific_first_docx(
        _config(args), Path(args.file), source_id=args.source_id
    )
    return _emit(args, "SAGE RAPIDWORDS SPECIFIC-FIRST IMPORT", result)



def command_rwc_authority_select(args: argparse.Namespace) -> int:
    """Select one imported authority snapshot explicitly without changing translation authority."""
    result = set_authority_selection(
        _config(args), authority_type=args.authority_type, source_id=args.source_id
    )
    return _emit(args, "SAGE SEMANTIC AUTHORITY SELECTION", {"active": result})

def command_rwc_index_build(args: argparse.Namespace) -> int:
    """Build deterministic local semantic indexes for one language namespace."""
    result = build_semantic_indexes(_config(args), language=args.language)
    return _emit(args, "SAGE LOCAL SEMANTIC INDEX BUILD", result)


def command_rwc_export(args: argparse.Namespace) -> int:
    """Generate a new validated FLEx or Combine LIFT exchange file."""
    output = Path(args.out).expanduser().resolve() if args.out else None
    result = export_lift(
        _config(args), language=args.language, profile=args.profile, view=args.view, output=output
    )
    return _emit(args, f"SAGE {result['profile']} LIFT EXPORT", result)


def command_rwc_initialise(args: argparse.Namespace) -> int:
    """Bind configured resources and build current local semantic indexes in one governed step."""
    config = _config(args)
    result: dict[str, Any] = {"bindings": {}, "indexes": {}}
    pairs = [(args.project, args.language)]
    if args.greek_project:
        pairs.append((args.greek_project, args.greek_language))
    for project_id, language in pairs:
        if not load_import_selection(config, language):
            raise ValidationError(f"No active semantic imports are available for {language}; import reference data first")
        set_binding(config, project_id=project_id, language=language)
        result["bindings"][project_id] = language
        result["indexes"][language] = build_semantic_indexes(config, language=language)
    result["rule"] = "Initialisation binds explicit project IDs to semantic namespaces and builds only from active local inputs."
    return _emit(args, "SAGE RWC INITIALISATION", result)


def command_rwc_review_set(args: argparse.Namespace) -> int:
    """Set one human-reviewed sense state; imports cannot perform this transition."""
    config = _config(args)
    result = set_review_state(
        config,
        language=args.language,
        sense_id=args.sense_id,
        status=args.status,
        reviewer=args.reviewer,
        note=args.note,
    )
    result["next_action"] = f"Rebuild {args.language} indexes before BIC, SAW, or export."
    return _emit(args, "SAGE SEMANTIC EVIDENCE REVIEW", result)


def command_rwc_review_clear(args: argparse.Namespace) -> int:
    """Clear one explicit review state and return to imported evidence status."""
    result = clear_review_state(_config(args), language=args.language, sense_id=args.sense_id)
    result["next_action"] = f"Rebuild {args.language} indexes before BIC, SAW, or export."
    return _emit(args, "SAGE SEMANTIC REVIEW CLEAR", result)


def command_rwc_review_list(args: argparse.Namespace) -> int:
    """List explicit reviewed sense states without interpreting import provenance as approval."""
    states = load_review_states(_config(args), args.language)
    if args.status:
        wanted = args.status.upper()
        states = {key: value for key, value in states.items() if str(value.get("status", "")).upper() == wanted}
    return _emit(
        args,
        "SAGE SEMANTIC REVIEW STATES",
        {"language": args.language, "reviewed_count": len(states), "senses": states},
    )


def register_rwc_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the RWC/SEMDOM surface without expanding the main CLI module."""
    rwc = subparsers.add_parser(
        "rwc",
        help="Manage Rapid Word Correction references, SEMDOM indexes, and FLEx/Combine exchange",
    )
    actions = rwc.add_subparsers(dest="rwc_command", required=True)

    status = actions.add_parser("status", help="Show local RWC/SEMDOM imports and index coverage")
    status.add_argument("--language", required=True, help="Semantic language namespace")
    status.set_defaults(handler=command_rwc_status)

    initialise = actions.add_parser("initialise", help="Bind project/resource IDs and build current local indexes")
    initialise.add_argument("--project", required=True, help="Primary SAGE Project ID")
    initialise.add_argument("--language", required=True, help="Primary semantic language namespace")
    initialise.add_argument("--greek-project", help="Optional governed Greek resource ID (normally GRK / @GRK)")
    initialise.add_argument("--greek-language", default="grc", help="Greek semantic namespace")
    initialise.set_defaults(handler=command_rwc_initialise)

    lookup = actions.add_parser("lookup", help="Look up one exact indexed surface form locally")
    lookup.add_argument("--language", required=True)
    lookup.add_argument("--form", required=True)
    lookup.set_defaults(handler=command_rwc_lookup)

    bind = actions.add_parser("bind", help="Bind a Scripture project/resource ID to a semantic language namespace")
    bind.add_argument("--project", required=True, help="SAGE Project ID")
    bind.add_argument("--language", required=True, help="Semantic language namespace")
    bind.set_defaults(handler=command_rwc_bind)

    authority = actions.add_parser("authority", help="Import semantic classification/traversal authority resources")
    authority_actions = authority.add_subparsers(dest="rwc_authority_command", required=True)
    semdom = authority_actions.add_parser("semdom", help="Import current SIL semdom.org JSON")
    semdom.add_argument("--file", required=True)
    semdom.add_argument("--source-id", default="sil-semdom-v4")
    semdom.set_defaults(handler=command_rwc_authority_semdom)
    folders = authority_actions.add_parser("folders", help="Import RapidWords specific-first folder divisions DOCX")
    folders.add_argument("--file", required=True)
    folders.add_argument("--source-id", default="rapidwords-specific-first-v4")
    folders.set_defaults(handler=command_rwc_authority_folders)
    select = authority_actions.add_parser("select", help="Select one previously imported SEMDOM or folder authority snapshot")
    select.add_argument("authority_type", choices=("semdom", "folders"))
    select.add_argument("--source-id", required=True)
    select.set_defaults(handler=command_rwc_authority_select)

    imports = actions.add_parser("import", help="Import immutable seed/reference snapshots")
    import_actions = imports.add_subparsers(dest="rwc_import_command", required=True)
    seed = import_actions.add_parser("seed", help="Import an operator-declared RWC/SemDom seed XLSX")
    seed.add_argument("--file", required=True)
    seed.add_argument("--source-id", required=True)
    seed.add_argument("--language", required=True)
    seed.add_argument("--analysis-language", default="en")
    seed.add_argument("--sheet", default="Entire Luke")
    seed.add_argument("--headword-column", required=True)
    seed.add_argument("--gloss-column", default="English gloss")
    seed.add_argument("--key-term-column", default="Key Term")
    seed.add_argument("--semdom-column", default="SIL SemDom")
    seed.set_defaults(handler=command_rwc_import_seed)
    greek = import_actions.add_parser("greek-reference", help="Import the supplied Greek biblical-term/SemDom XLSX as form-level reference")
    greek.add_argument("--file", required=True)
    greek.add_argument("--source-id", required=True)
    greek.add_argument("--language", default="grc")
    greek.add_argument("--sheet", default="Luke-keyterms")
    greek.set_defaults(handler=command_rwc_import_greek)
    for state in ("activate", "deactivate"):
        selection = import_actions.add_parser(state, help=f"{state.title()} one immutable import snapshot for index builds")
        selection.add_argument("--source-id", required=True)
        selection.add_argument("--language", required=True)
        selection.set_defaults(handler=command_rwc_import_selection, import_state=state)
    for application in ("FLEx", "Combine"):
        parser = import_actions.add_parser(application.lower(), help=f"Import an immutable {application} LIFT snapshot")
        parser.add_argument("--file", required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--language", required=True)
        parser.set_defaults(handler=command_rwc_import_lift, application=application)

    review = actions.add_parser("review", help="Govern sense evidence states independently of import provenance")
    review_actions = review.add_subparsers(dest="rwc_review_command", required=True)
    review_set = review_actions.add_parser("set", help="Set OBSERVED, TEAM_CONFIRMED, ESTABLISHED, or APPROVED for one indexed sense")
    review_set.add_argument("--language", required=True)
    review_set.add_argument("--sense-id", required=True)
    review_set.add_argument("--status", required=True, choices=REVIEW_STATES)
    review_set.add_argument("--reviewer", required=True)
    review_set.add_argument("--note")
    review_set.set_defaults(handler=command_rwc_review_set)
    review_clear = review_actions.add_parser("clear", help="Remove one explicit review state")
    review_clear.add_argument("--language", required=True)
    review_clear.add_argument("--sense-id", required=True)
    review_clear.set_defaults(handler=command_rwc_review_clear)
    review_list = review_actions.add_parser("list", help="List explicit reviewed sense states")
    review_list.add_argument("--language", required=True)
    review_list.add_argument("--status", choices=REVIEW_STATES)
    review_list.set_defaults(handler=command_rwc_review_list)

    index = actions.add_parser("index", help="Build deterministic local semantic indexes")
    index_actions = index.add_subparsers(dest="rwc_index_command", required=True)
    build = index_actions.add_parser("build", help="Build lemma, sense/SEMDOM, surface-form, key-term, and coverage indexes")
    build.add_argument("--language", required=True)
    build.set_defaults(handler=command_rwc_index_build)

    export = actions.add_parser("export", help="Generate a new validated LIFT view; imports are never modified")
    export.add_argument("profile", choices=("flex", "combine"))
    export.add_argument("--language", required=True)
    export.add_argument("--view", required=True, choices=tuple(EXPORT_VIEWS), help="Explicit evidence-state export view")
    export.add_argument("--out", help="Optional output .lift path")
    export.set_defaults(handler=command_rwc_export)
