"""SAGE system-interface localization and menu-key grammar contracts."""

from __future__ import annotations

import ast
import json
import io
import re
from pathlib import Path

import yaml

from sage.errors import ConfigurationError
from sage.interface_localization import SUPPORTED_INTERFACE_LANGUAGES, InterfaceLocalizer
from sage.menu import MenuExitRequested, MenuIO, SageControlCenter, ScriptedInput
from sage.operator_overrides import load_effective_settings
from sage.ui_format import display_width


DYNAMIC_MENU_TEXT = {
    "Add RTC Job <WIP PROJECT, REFERENCE PROJECT>",
    "Add STC Job <WIP PROJECT>",
    "Add another Project to SAGE",
    "Validate all SAGE Projects",
    "All languages",
    "Choose another ISO language code",
    "Use unresolved language code [und]",
    "Filter catalog",
    "Rescan Paratext Projects",
    "Invalid Project folders",
    "Other Project location",
    "Install Ollama on this host",
    "Stop Ollama",
    "Start Ollama",
    "Disable Local AI",
    "Enable Local AI",
    "Manage Local AI models",
    "Install configured model",
    "Reinstall configured model",
    "Test Local AI",
    "BIC INSPECT",
    "BIC REWRITE",
    "BIC SELF-CHECK",
    "SAW Reference Text Comparison (RTC)",
    "SAW Source Text Correspondence (STC)",
    "SAW Targeted Check",
    "SAW Original-Language Review",
    "CHOOSE BIC <SOURCE>",
    "CHOOSE BIC <DONOR>",
    "CHOOSE BIC <TARGET>",
    "CHOOSE SAW <WIP>",
    "CHOOSE SAW <REFERENCE>",
    "CHOOSE SECONDARY REPORTING LANGUAGE",
    "Choose other language",
    "No secondary reporting language",
    "Other secondary reporting language",
    "Use WIP language [Recommended]",
    "Use TARGET language [Recommended]",
    "Primary SAGE Project",
    "SAGE Project",
    "Open active BIC Job",
    "Open active SAW Job",
    "Recovery and Reset",
    "Job management",
    "Configure",
    "Recommended",
    "Use",
    "Use bundled",
    "ISO language",
    "List incomplete transactions",
    "Recover one transaction",
    "Abandon active Run",
    "Export diagnostics",
    "Restart one BIC scope [TARGET unchanged]",
    "Choose from existing profile list",
    "Choose existing compatible Language Profile",
    "Add grammar profile from YAML file",
    "Show configured grammar profiles",
    "Validate grammar profiles",
    "SYSTEM ACTIONS",
    "SAGE DATA FOLDERS",
    "PATH ACTIONS",
    "LANGUAGE ACTIONS",
    "CURRENT SYSTEM STATE [LAST KNOWN]",
    "CHECK ACTIONS",
    "LOCAL AI ACTIONS",
    "MODEL ACTIONS",
    "CONFIGURE HOSTED AI",
    "BIC JOB STORAGE",
    "SAW JOB STORAGE",
}


def _static_choose_text(menu_path: Path) -> set[str]:
    """Collect literal menu titles/options that must exist in the editable locale table."""
    tree = ast.parse(menu_path.read_text(encoding="utf-8"))
    values: set[str] = {
        "Back",
        "Main Menu",
        "Exit SAGE",
        "Language",
        "Choose: ",
        "Invalid choice. Choose one listed option.",
        "INTERFACE LANGUAGE",
        "Interface language",
        "Choose interface language",
    }
    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "choose"
        ):
            continue
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            values.add(call.args[0].value)
        if len(call.args) > 1 and isinstance(call.args[1], (ast.Tuple, ast.List)):
            for item in call.args[1].elts:
                if not isinstance(item, (ast.Tuple, ast.List)) or len(item.elts) < 2:
                    continue
                label = item.elts[1]
                if isinstance(label, ast.Constant) and isinstance(label.value, str):
                    values.add(label.value)
    return values


def test_menu_localization_json_covers_all_static_and_governed_dynamic_menu_text(package_root: Path) -> None:
    """Verify every governed menu concept has all six interface renderings exactly once."""
    source = package_root / "system/config/localization/menu-localization.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    assert raw["_meta"]["locales"] == list(SUPPORTED_INTERFACE_LANGUAGES)
    strings = raw["strings"]
    assert strings
    assert len(strings) >= 339
    canonical = {value["en-US"].casefold() for value in strings.values()}
    assert len(canonical) == len(strings)
    required = _static_choose_text(package_root / "system/src/sage/menu.py") | DYNAMIC_MENU_TEXT
    missing = sorted(text for text in required if text.strip().casefold() not in canonical)
    assert not missing
    for key, value in strings.items():
        assert key.startswith("menu.")
        for language in SUPPORTED_INTERFACE_LANGUAGES:
            assert value[language].strip(), (key, language)


def test_menu_localization_json_reduces_display_case_duplicates(package_root: Path) -> None:
    """Verify capitalization-only headings are renderer style, not duplicate localization entries."""
    source = package_root / "system/config/localization/menu-localization.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    phrases = [value["en-US"] for value in raw["strings"].values()]
    assert "Help" in phrases
    assert "HELP" not in phrases
    assert "Main menu" in phrases
    assert "MAIN MENU" not in phrases
    assert "SAGE Maintenance" in phrases
    assert "SAGE MAINTENANCE" not in phrases


def test_menu_operator_action_grammar_uses_choose(package_root: Path) -> None:
    """Keep the menu's operator instruction verb consistently on Choose."""
    tree = ast.parse((package_root / "system/src/sage/menu.py").read_text(encoding="utf-8"))
    menu_literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    ]
    assert not [value for value in menu_literals if re.search(r"\bSelect\b", value, flags=re.IGNORECASE)]


def test_every_job_resource_assignment_heading_highlights_its_formal_role(package_root: Path) -> None:
    """Require angle-bracket role emphasis on every literal Project assignment chooser."""
    tree = ast.parse((package_root / "system/src/sage/menu.py").read_text(encoding="utf-8"))
    titles: list[str] = []
    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "choose_or_add_resource"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        ):
            continue
        titles.append(call.args[0].value)
    assert set(titles) == {
        "CHOOSE BIC <SOURCE>",
        "CHOOSE BIC <DONOR>",
        "CHOOSE BIC <TARGET>",
        "CHOOSE SAW <WIP>",
        "CHOOSE SAW <REFERENCE>",
        "CHOOSE RTC <REFERENCE>",
    }
    assert all(re.search(r"<[A-Z_]+>$", title) for title in titles)


def test_interface_language_hotkey_is_setup_owned_and_does_not_change_reporting(make_workspace) -> None:
    """Verify footer D changes only Setup-owned interface language and rerenders immediately."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    before = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["d", "3", "c"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )

    assert center.run() == 0
    raw = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
    effective, _sidecar, _resolutions = load_effective_settings(root / "ecosystem.yml")
    assert raw == before
    assert effective["interface"]["language"] == "id"
    assert effective.get("human_output") == before.get("human_output")
    rendered = output.getvalue()
    assert "Menu utama" in rendered
    assert "B. Menu utama   C. Keluar dari SAGE" in rendered
    assert "D. Bahasa   E. Bantuan   F. Status" in rendered


def test_menu_visible_operations_reject_alphabetic_action_keys() -> None:
    """Verify alphabetic keys remain reserved for the invariant footer controls."""
    menu = MenuIO(input_func=ScriptedInput(["1"]), output=io.StringIO())
    try:
        menu.choose("Test", (("F", "Filter"),))
    except ConfigurationError as exc:
        assert "numeric keys" in exc.message
    else:  # pragma: no cover - contract failure path
        raise AssertionError("alphabetic visible operation key was accepted")


def test_interactive_menu_navigation_preserves_terminal_scrollback(monkeypatch) -> None:
    """Keep prior forms visible and use headings rather than ANSI viewport clearing."""

    class TTYBuffer(io.StringIO):
        """Captured output that advertises interactive terminal capabilities."""

        def isatty(self) -> bool:
            """Report an interactive stream for viewport-reset testing."""
            return True

    monkeypatch.setenv("TERM", "xterm-256color")
    output = TTYBuffer()
    menu = MenuIO(input_func=ScriptedInput(["1"]), output=output)

    assert menu.choose("FIRST PANEL", (("1", "Open second panel"),)) == "1"
    menu.write("Second-panel context")
    menu.input_func = ScriptedInput(["a"])
    assert menu.choose("SECOND PANEL", (("B", "Back"),)) == "B"

    rendered = output.getvalue()
    assert "\x1b[" not in rendered
    assert rendered.startswith("\n╔" + "═" * 70 + "╗\n║ FIRST PANEL")
    assert "Second-panel context\n\n╔" + "═" * 70 + "╗" in rendered
    assert "║ SECOND PANEL" in rendered


def test_menu_pause_is_non_blocking_and_prints_no_continue_prompt() -> None:
    """Routine action completion returns directly to the next delimited menu panel."""
    output = io.StringIO()

    def unexpected_input(prompt: str) -> str:
        """Fail if the non-blocking pause attempts to read terminal input."""
        raise AssertionError(f"pause unexpectedly requested input: {prompt}")

    MenuIO(input_func=unexpected_input, output=output).pause()
    assert output.getvalue() == ""


def test_captured_menu_output_has_panel_boundary_without_ansi() -> None:
    """Keep logs and scripted output readable without terminal control sequences."""
    output = io.StringIO()
    menu = MenuIO(input_func=ScriptedInput(["1"]), output=output)

    assert menu.choose("CAPTURED PANEL", (("1", "Continue"),)) == "1"

    rendered = output.getvalue()
    assert "\x1b[" not in rendered
    assert rendered.startswith("\n╔" + "═" * 70 + "╗\n║ CAPTURED PANEL")
    assert "╚" + "═" * 70 + "╝\n\n  1. Continue" in rendered
    assert "\n┌" + "─" * 70 + "┐\n│  B. Main menu   C. Exit SAGE" in rendered
    assert rendered.endswith("└" + "─" * 70 + "┘\n\n")


def test_major_minor_and_footer_use_distinct_line_styles() -> None:
    """Pin boxed major/footer blocks and indented, underlined minor headings."""
    output = io.StringIO()
    menu = MenuIO(output=output)

    menu.write_menu_header("MAJOR")
    menu.write_menu_header("Minor", major=False)
    menu.write_menu_footer(include_back=True)

    rendered = output.getvalue()
    assert "╔" + "═" * 70 + "╗\n║ MAJOR" in rendered
    assert "\n> Minor\n" + "─" * 72 + "\n\n" in rendered
    assert "│  A. Back   B. Main menu   C. Exit SAGE" in rendered
    assert rendered.endswith("└" + "─" * 70 + "┘\n\n")


def test_menu_output_wraps_within_the_configured_viewport() -> None:
    """Catch long menu content or boxes expanding beyond the visible terminal."""
    output = io.StringIO()
    menu = MenuIO(
        input_func=ScriptedInput(["a"]),
        output=output,
        viewport_columns=48,
    )

    assert menu.choose(
        "START NEW STC REVIEW <WIP PROJECT>",
        (
            (
                "1",
                "ukrNPUv1 New Ukrainian Translation ver. uk-UA "
                "[Imported 20260902]",
            ),
            ("2", "漢字 Project label remains bounded by terminal-cell width"),
            ("B", "Back"),
        ),
        context=(
            "This explanatory information block is intentionally wider than the viewport.",
        ),
    ) == "B"

    rendered = output.getvalue()
    assert max(display_width(line) for line in rendered.splitlines()) <= 48
    assert "\n     uk-UA [Imported 20260902]" in rendered
    assert "╔" + "═" * 46 + "╗" in rendered


def test_information_rows_share_one_value_column_and_wrap_under_values() -> None:
    """Catch ad-hoc padding that misaligns labels or wrapped information values."""
    output = io.StringIO()
    menu = MenuIO(output=output, viewport_columns=42)

    menu.write_info(
        (
            ("WIP Project", "ukrNPUv1 New Ukrainian Translation"),
            ("Date imported", "20260902"),
        ),
        label_width=20,
    )

    assert output.getvalue().splitlines() == [
        "WIP Project         ukrNPUv1 New",
        "                    Ukrainian Translation",
        "Date imported       20260902",
    ]


def test_information_rows_render_missing_values_consistently(make_workspace) -> None:
    """Catch localization coercing a missing information value into the word None."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    menu = MenuIO(
        output=output,
        localizer=InterfaceLocalizer.load(root, root / "ecosystem.yml"),
        viewport_columns=32,
    )

    menu.write_info((("Secondary language", None),), label_width=20)

    assert output.getvalue() == "Secondary language  —\n"


def test_numeric_menu_rows_use_sentence_case_with_mid_sentence_protocol_entities() -> None:
    """Distinguish governed menu entities from ordinary words and the Book of Job."""
    output = io.StringIO()
    menu = MenuIO(input_func=ScriptedInput(["a"]), output=output)

    assert menu.choose(
        "MENU COPY",
        (
            ("1", "Add STC Job <WIP PROJECT>"),
            ("2", "Runs and Task history"),
            ("3", "Run Original-Language Review"),
            ("4", "Review bound Projects"),
            ("5", "Advanced Run controls"),
            ("6", "Continue to main menu"),
            ("7", "Job"),
            ("B", "Back"),
        ),
    ) == "B"

    rendered = output.getvalue()
    assert "  1. Add STC JOB <WIP PROJECT>" in rendered
    assert "  2. Runs and TASK history" in rendered
    assert "  3. Run Original-Language Review" in rendered
    assert "  4. Review bound PROJECTS" in rendered
    assert "  5. Advanced RUN controls" in rendered
    assert "  6. Continue to main menu" in rendered
    assert "  7. Job" in rendered


def test_english_menu_copy_uses_sentence_case_and_declared_protocol_names(make_workspace) -> None:
    """Catch incidental title case without flattening governed names or role selectors."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    menu = MenuIO(
        input_func=ScriptedInput(["a", "a"]),
        output=output,
        localizer=InterfaceLocalizer.load(root, root / "ecosystem.yml"),
    )

    assert menu.choose(
        "ADVANCED RUN CONTROLS",
        (
            ("1", "BIC Memory and Terminology"),
            ("2", "Choose Book"),
            ("3", "Continue to Main Menu"),
            ("4", "Generated Target and Generations"),
            ("5", "Recovery and Reset"),
            ("6", "Paratext Project Catalog"),
            ("7", "Quick Scan"),
            ("8", "Resource Status Report"),
            ("9", "Configure Local AI"),
            ("10", "Use another location"),
            ("B", "Back"),
        ),
    ) == "B"
    assert menu.choose("CHOOSE BIC <SOURCE>", (("B", "Back"),)) == "B"

    rendered = output.getvalue()
    assert "Advanced RUN controls" in rendered
    assert "  1. BIC memory and terminology" in rendered
    assert "  2. Choose book" in rendered
    assert "  3. Continue to main menu" in rendered
    assert "  4. Generated TARGET and generations" in rendered
    assert "  5. Recovery and reset" in rendered
    assert "  6. Paratext PROJECT catalog" in rendered
    assert "  7. Quick scan" in rendered
    assert "  8. Resource Status Report" in rendered
    assert "  9. Configure Local AI" in rendered
    assert " 10. Use another location" in rendered
    assert "CHOOSE BIC <SOURCE>" in rendered


def test_plain_text_output_expands_tabs_before_viewport_wrapping() -> None:
    """Catch terminal-dependent tab stops bypassing deterministic block alignment."""
    output = io.StringIO()
    menu = MenuIO(output=output, viewport_columns=24)

    menu.write("Header\tvalue that wraps")

    rendered = output.getvalue()
    assert "\t" not in rendered
    assert max(len(line) for line in rendered.splitlines()) <= 24


def test_en_us_and_en_gb_are_distinct_editable_interface_rows(make_workspace) -> None:
    """Verify U.S. and U.K. English remain separate editable interface columns."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    localizer = InterfaceLocalizer.load(root, root / "ecosystem.yml")
    assert localizer.text("Paratext Project Catalog") == "Paratext Project catalog"
    localizer.set_language("en-GB")
    assert localizer.text("Paratext Project Catalog") == "Paratext Project catalogue"
    assert localizer.text("Reinitialize Job") == "Reinitialise Job"
    localizer.set_language("en-US")
    assert localizer.text("Reinitialize Job") == "Reinitialize Job"


def test_all_six_interface_locales_render_the_invariant_footer(make_workspace) -> None:
    """Verify all shipped locales render Unicode labels while footer keys stay A-F."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    localizer = InterfaceLocalizer.load(root, root / "ecosystem.yml")
    expected = {
        "en-US": ("Main menu", "B. Main menu   C. Exit SAGE", "D. Language   E. Help   F. Status"),
        "en-GB": ("Main menu", "B. Main menu   C. Exit SAGE", "D. Language   E. Help   F. Status"),
        "id": ("Menu utama", "B. Menu utama   C. Keluar dari SAGE", "D. Bahasa   E. Bantuan   F. Status"),
        "fr": ("Menu principal", "B. Menu principal   C. Quitter SAGE", "D. Langue   E. Aide   F. État"),
        "ru": ("Главное меню", "B. Главное меню   C. Выйти из SAGE", "D. Язык   E. Справка   F. Состояние"),
        "pt-BR": ("Menu principal", "B. Menu principal   C. Sair do SAGE", "D. Idioma   E. Ajuda   F. Status"),
    }
    for language, (title, navigation, services) in expected.items():
        localizer.set_language(language)
        output = io.StringIO()
        menu = MenuIO(
            input_func=ScriptedInput(["c"]),
            output=output,
            localizer=localizer,
            language_handler=lambda: None,
            help_handler=lambda _title: None,
            status_handler=lambda: None,
        )
        try:
            menu.choose("MAIN MENU", (("1", "Scripture Projects"), ("X", "Exit SAGE")))
        except MenuExitRequested:
            pass
        rendered = output.getvalue()
        assert title in rendered
        assert navigation in rendered
        assert services in rendered
