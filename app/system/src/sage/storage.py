"""Cross-platform SAGE application/local-data storage contract.

The application tree is immutable at runtime. Persistent operator and machine-local
state lives in the portable bundle's sibling ``localdata`` directory by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DATA_HOME_ENV = "SAGE_DATA_HOME"
DATA_LAYOUT_SCHEMA = 2
LEGACY_DATA_LAYOUT_SCHEMAS = frozenset({1})
DATA_MARKER = "data-root.json"
LOCATOR_SCHEMA = 1


class StorageError(RuntimeError):
    """Raised when the configured data-home boundary is unsafe or unavailable."""


def _resolved(path: Path) -> Path:
    """Expand and resolve one filesystem path without creating it."""
    return path.expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether path is contained by parent after resolution."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def default_data_home(app_root: Path) -> Path:
    """Return the zero-configuration portable bundle localdata directory."""
    root = _resolved(app_root)
    return root.parent / "localdata"


def _installation_key(app_root: Path) -> str:
    """Return a stable per-checkout key for the OS-local data-home locator."""
    value = str(_resolved(app_root))
    if os.name == "nt":
        value = value.casefold()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def locator_path(app_root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Return the OS-local pointer used only when a custom localdata home is persisted."""
    env = os.environ if environ is None else environ
    key = _installation_key(app_root)
    system = platform.system()
    if system == "Windows":
        base = Path(env.get("LOCALAPPDATA") or env.get("APPDATA") or Path.home() / "AppData" / "Local")
        return _resolved(base) / "SAGE" / "installations" / f"{key}.json"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "SAGE" / "installations" / f"{key}.json"
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return _resolved(base) / "sage" / "installations" / f"{key}.json"


def read_persisted_data_home(app_root: Path, environ: Mapping[str, str] | None = None) -> Path | None:
    """Load a persisted custom data-home pointer for this exact application checkout."""
    path = locator_path(app_root, environ)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(f"Invalid SAGE data-home locator: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != LOCATOR_SCHEMA:
        raise StorageError(f"Unsupported SAGE data-home locator: {path}")
    raw = str(payload.get("data_home") or "").strip()
    if not raw:
        raise StorageError(f"SAGE data-home locator does not contain a path: {path}")
    candidate = _resolved(Path(raw))
    if not candidate.exists():
        raise StorageError(
            f"Configured localdata location is unavailable: {candidate}. "
            "Restore/mount that location, set SAGE_DATA_HOME, or reset the persisted data-home setting."
        )
    return candidate


def persist_data_home(app_root: Path, data_home: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Persist a custom data-home pointer without moving or copying operator data."""
    root = _resolved(app_root)
    candidate = validate_data_home(root, data_home)
    path = locator_path(root, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": LOCATOR_SCHEMA,
        "app_root": str(root),
        "data_home": str(candidate),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def clear_persisted_data_home(app_root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Clear only the custom locator; operator data is never deleted."""
    path = locator_path(app_root, environ)
    path.unlink(missing_ok=True)
    return path


def validate_data_home(app_root: Path, data_home: Path) -> Path:
    """Reject data roots that overlap the Git-controlled SAGE application tree."""
    app = _resolved(app_root)
    data = _resolved(data_home)
    if data == app or _is_relative_to(data, app):
        raise StorageError(f"Local data must be outside the immutable SAGE app tree: {data}")
    return data


def resolve_data_home(
    app_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    explicit: Path | str | None = None,
) -> Path:
    """Resolve local data by explicit path, environment, persisted locator, then bundle default."""
    root = _resolved(app_root)
    env = os.environ if environ is None else environ
    if explicit not in (None, ""):
        return validate_data_home(root, Path(str(explicit)))
    raw_env = str(env.get(DATA_HOME_ENV, "")).strip()
    if raw_env:
        return validate_data_home(root, Path(raw_env))
    persisted = read_persisted_data_home(root, env)
    if persisted is not None:
        return validate_data_home(root, persisted)
    return validate_data_home(root, default_data_home(root))


@dataclass(frozen=True)
class StorageLayout:
    """Canonical ownership boundary for all SAGE runtime and operator data."""

    app_root: Path
    data_root: Path

    @property
    def inputs_root(self) -> Path:
        """Return the operator-supplied input collection root."""
        return self.data_root / "inputs"

    @property
    def work_root(self) -> Path:
        """Return the active Project and Job working root."""
        return self.data_root / "work"

    @property
    def projects_root(self) -> Path:
        """Return the visible working Project root."""
        return self.work_root / "projects"

    @property
    def jobs_root(self) -> Path:
        """Return the visible durable Job root."""
        return self.work_root / "jobs"

    @property
    def resources_root(self) -> Path:
        """Return the visible operator resource root."""
        return self.inputs_root / "resources"

    @property
    def styleguides_root(self) -> Path:
        """Return the reserved operator style-guide input root."""
        return self.inputs_root / "styleguides"

    @property
    def semantic_domains_root(self) -> Path:
        """Return the reserved operator semantic-domain input root."""
        return self.inputs_root / "semantic-domains"

    @property
    def plugins_root(self) -> Path:
        """Return the visible local plugin root."""
        return self.data_root / "plugins"

    @property
    def reports_root(self) -> Path:
        """Return the visible human-facing report root."""
        return self.data_root / "reports"

    @property
    def exports_root(self) -> Path:
        """Return the visible export root."""
        return self.data_root / "exports"

    @property
    def system_root(self) -> Path:
        """Return the hidden SAGE-managed system root."""
        return self.data_root / ".system"

    @property
    def config_root(self) -> Path:
        """Return the machine/operator configuration root."""
        return self.system_root / "config"

    @property
    def state_root(self) -> Path:
        """Return the persistent machine state root."""
        return self.system_root / "state"

    @property
    def indexes_root(self) -> Path:
        """Return the regenerable index root."""
        return self.system_root / "indexes"

    @property
    def cache_root(self) -> Path:
        """Return the regenerable cache root."""
        return self.system_root / "cache"

    @property
    def locks_root(self) -> Path:
        """Return the runtime lock root."""
        return self.system_root / "locks"

    @property
    def transactions_root(self) -> Path:
        """Return the transaction journal root."""
        return self.system_root / "transactions"

    @property
    def logs_root(self) -> Path:
        """Return the runtime log root."""
        return self.system_root / "logs"

    @property
    def diagnostics_root(self) -> Path:
        """Return the diagnostic artifact root."""
        return self.system_root / "diagnostics"

    @property
    def temp_root(self) -> Path:
        """Return the temporary-file root."""
        return self.system_root / "temp"

    @property
    def runtime_root(self) -> Path:
        """Return the managed runtime root."""
        return self.system_root / "runtime"

    @property
    def venv_root(self) -> Path:
        """Return the managed Python virtual-environment root."""
        return self.runtime_root / "venv"

    @property
    def workflow_root(self) -> Path:
        """Return the workflow-owned runtime root."""
        return self.system_root / "workflows"

    @property
    def marker_path(self) -> Path:
        """Return the localdata ownership marker path."""
        return self.system_root / DATA_MARKER

    def _migrate_legacy_visible_roots(self) -> None:
        """Move recognized flat Beta roots into the categorized portable layout."""
        migrations = {
            self.data_root / "projects": self.projects_root,
            self.data_root / "jobs": self.jobs_root,
            self.data_root / "resources": self.resources_root,
        }
        for source, target in migrations.items():
            if not source.exists():
                continue
            if target.exists():
                raise StorageError(
                    f"Cannot migrate legacy localdata because both paths exist: {source} and {target}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)

    def ensure(self) -> "StorageLayout":
        """Create canonical data-owned folders and a marker without touching unknown directories."""
        payload = {
            "schema_version": DATA_LAYOUT_SCHEMA,
            "product": "SAGE",
            "layout": "INPUTS_WORK_REPORTS",
            # The marker identifies its containing directory; an absolute path
            # would become stale whenever the portable bundle is moved.
            "data_root": ".",
        }
        if self.marker_path.is_file():
            try:
                existing = json.loads(self.marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StorageError(f"Invalid localdata marker: {self.marker_path}: {exc}") from exc
            if (
                not isinstance(existing, dict)
                or existing.get("product") != "SAGE"
                or existing.get("schema_version")
                not in LEGACY_DATA_LAYOUT_SCHEMAS | {DATA_LAYOUT_SCHEMA}
            ):
                raise StorageError(f"Directory is not a recognized localdata root: {self.data_root}")
        elif self.data_root.exists():
            # Validate before creating anything so an unrelated destination is never modified.
            visible_known = {
                "README.md", "inputs", "work", "plugins", "reports", "exports", ".system",
                # Recognized flat Beta roots are migrated below after validation.
                "projects", "jobs", "resources",
            }
            unknown_visible = [p.name for p in self.data_root.iterdir() if p.name not in visible_known]
            system_known = {
                "config", "state", "indexes", "cache", "locks", "transactions", "logs",
                "diagnostics", "temp", "runtime", "workflows", "jobs", "installers", DATA_MARKER,
            }
            unknown_system = (
                [p.name for p in self.system_root.iterdir() if p.name not in system_known]
                if self.system_root.is_dir() else []
            )
            if unknown_visible or unknown_system:
                details = ", ".join(sorted(unknown_visible + [f".system/{name}" for name in unknown_system]))
                raise StorageError(
                    f"Refusing to initialize non-empty unrecognized data directory: {self.data_root}; "
                    f"unknown entries: {details}"
                )
        self._migrate_legacy_visible_roots()
        for path in (
            self.inputs_root,
            self.work_root,
            self.projects_root,
            self.jobs_root / "bic",
            self.jobs_root / "saw",
            self.resources_root,
            self.styleguides_root,
            self.semantic_domains_root,
            self.plugins_root,
            self.reports_root,
            self.exports_root,
            self.config_root,
            self.state_root,
            self.indexes_root,
            self.cache_root,
            self.locks_root,
            self.transactions_root,
            self.logs_root,
            self.diagnostics_root,
            self.temp_root,
            self.runtime_root,
            self.workflow_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if not self.marker_path.is_file() or existing != payload:
            tmp = self.marker_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, self.marker_path)
        return self


def storage_layout(
    app_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    explicit: Path | str | None = None,
    create: bool = False,
) -> StorageLayout:
    """Return the canonical layout for one SAGE checkout."""
    app = _resolved(app_root)
    data = resolve_data_home(app, environ=environ, explicit=explicit)
    layout = StorageLayout(app_root=app, data_root=data)
    if create:
        layout.ensure()
    return layout


def resolve_declared_path(app_root: Path, value: str, label: str) -> Path:
    """Resolve one config path using explicit @data/@system ownership prefixes."""
    root = _resolved(app_root)
    text = str(value).strip()
    layout = storage_layout(root)
    prefixes = {
        "@data": layout.data_root,
        "@system": layout.system_root,
        "@projects": layout.projects_root,
        "@jobs": layout.jobs_root,
        "@resources": layout.resources_root,
        "@plugins": layout.plugins_root,
        "@reports": layout.reports_root,
        "@exports": layout.exports_root,
    }
    for prefix, base in prefixes.items():
        if text == prefix:
            return base.resolve()
        if text.startswith(prefix + "/") or text.startswith(prefix + "\\"):
            relative = text[len(prefix) + 1 :].replace("\\", "/")
            candidate = (base / Path(relative)).resolve()
            if not _is_relative_to(candidate, base.resolve()):
                raise StorageError(f"{label} escapes its governed {prefix} root: {value}")
            return candidate
    raw = Path(text).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not _is_relative_to(candidate, root):
        raise StorageError(f"{label} must use a governed @data/@system path for locations outside SAGE: {value}")
    return candidate

def declare_governed_path(app_root: Path, path: Path, label: str) -> str:
    """Encode a Core/localdata path as a portable governed reference."""
    root = _resolved(app_root)
    candidate = _resolved(path)
    if _is_relative_to(candidate, root):
        return candidate.relative_to(root).as_posix()
    layout = storage_layout(root)
    roots = (
        ("@projects", layout.projects_root),
        ("@jobs", layout.jobs_root),
        ("@resources", layout.resources_root),
        ("@plugins", layout.plugins_root),
        ("@reports", layout.reports_root),
        ("@exports", layout.exports_root),
        ("@system", layout.system_root),
        ("@data", layout.data_root),
    )
    for prefix, base in roots:
        resolved_base = base.resolve()
        if _is_relative_to(candidate, resolved_base):
            relative = candidate.relative_to(resolved_base).as_posix()
            return prefix if not relative else f"{prefix}/{relative}"
    raise StorageError(f"{label} is outside governed SAGE Core/localdata roots: {candidate}")


def resolve_persisted_path(app_root: Path, value: str, label: str) -> Path:
    """Resolve a portable declaration or safely rebase a legacy absolute data path.

    Pre-portable Beta records sometimes stored absolute paths.  When the bundle is
    moved, only paths with an explicit ``localdata``/``SAGEdata`` component may be
    rebased, and their suffix remains bounded by the current data root.
    """
    text = str(value).strip()
    raw = Path(text).expanduser()
    if not raw.is_absolute():
        return resolve_declared_path(app_root, text, label)
    try:
        declaration = declare_governed_path(app_root, raw, label)
    except StorageError as exc:
        parts = raw.parts
        anchor = next(
            (index for index, part in enumerate(parts) if part.casefold() in {"localdata", "sagedata"}),
            None,
        )
        if anchor is None:
            raise StorageError(f"{label} is outside the portable SAGE bundle: {raw}") from exc
        layout = storage_layout(app_root)
        suffix = parts[anchor + 1 :]
        legacy_roots = {
            "projects": layout.projects_root,
            "jobs": layout.jobs_root,
            "resources": layout.resources_root,
            "plugins": layout.plugins_root,
            "reports": layout.reports_root,
            "exports": layout.exports_root,
        }
        if suffix and suffix[0].casefold() in legacy_roots:
            candidate = legacy_roots[suffix[0].casefold()].joinpath(*suffix[1:]).resolve()
        else:
            candidate = layout.data_root.joinpath(*suffix).resolve()
        if not _is_relative_to(candidate, layout.data_root.resolve()):
            raise StorageError(f"{label} escapes portable localdata: {raw}") from exc
        return candidate
    return resolve_declared_path(app_root, declaration, label)
