"""Task-local verified phase checkpoints and recoverable final publication.

A crash before ledger publication can repeat a physical provider request. Orphan
attempts are never evidence. Callers hold the task execution lock before entering
this store; its separate nonreentrant ledger lock also protects direct callers.
Current phase and final validators remain controller authority, never providers.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
from uuid import uuid4

from sage.atomic import atomic_write_bytes, atomic_write_json
from sage.errors import LockError, ValidationError
from sage.locking import WorkspaceLock, _process_exists
from .model_tasks import ModelPhaseReceipt
from .telemetry import CallMeasurement

_VERSION = '1.0'
_OUTPUT = 'output/model-evidence.json'
_RECEIPT = 'validation/llm-execution-receipt.json'
_PHASE_ROOT = 'validation/nca-phases'


def _error(message: str) -> ValidationError:
    """Report fail-closed checkpoint corruption with a stable domain code."""
    return ValidationError(message, code='NCA_PHASE_CHECKPOINT_INVALID')


def _require(condition: bool, message: str) -> None:
    """Reject evidence that cannot satisfy a required replay invariant."""
    if not condition:
        raise _error(message)


def _plain(value: object) -> object:
    """Own JSON evidence without reserializing the exact raw provider string."""
    if isinstance(value, Mapping):
        _require(all(isinstance(key, str) for key in value), 'Non-string evidence key')
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _canonical(value: object) -> bytes:
    """Encode deterministic UTF-8 JSON for content identities and physical requests."""
    try:
        return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise _error('Evidence is not strict UTF-8 JSON') from exc


def _digest(value: bytes) -> str:
    """Hash exact bytes without newline or Unicode normalization."""
    return hashlib.sha256(value).hexdigest()


def _hash(value: object) -> bool:
    """Recognize only full lowercase SHA-256 identities."""
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _object(value: object, names: set[str]) -> Mapping[str, object]:
    """Require a closed object at a persisted evidence boundary."""
    _require(isinstance(value, Mapping) and set(value) == names, 'Unexpected checkpoint fields')
    return value


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys instead of silently replacing earlier evidence."""
    result = {}
    for key, value in pairs:
        _require(key not in result, 'Duplicate checkpoint JSON key')
        result[key] = value
    return result


def _decode(payload: bytes) -> object:
    """Decode strict UTF-8 evidence and reject nonstandard numeric constants."""
    def invalid(value: str) -> None:
        """Reject NaN and infinity in persisted JSON."""
        raise _error('Nonfinite checkpoint JSON value')
    try:
        return json.loads(payload.decode('utf-8'), object_pairs_hook=_unique, parse_constant=invalid)
    except (ValueError, UnicodeError) as exc:
        raise _error('Malformed checkpoint JSON') from exc


def _components(values: Mapping[str, bytes]) -> dict[str, str]:
    """Bind named original bytes, including component names, without accepting hashes as bytes."""
    _require(isinstance(values, Mapping) and bool(values), 'Missing phase byte components')
    _require(all(isinstance(name, str) and name and isinstance(value, bytes)
                 for name, value in values.items()), 'Phase components must be named bytes')
    return {name: _digest(value) for name, value in values.items()}


@dataclass(frozen=True)
class PhaseKey:
    """Canonical identity of one phase under sealed same-task evidence and contracts."""
    phase: str
    task_fingerprint: str
    input_ids: tuple[str, ...]
    input_sha256: str
    policy_sha256: str
    route_sha256: str
    contract_sha256: str
    validator_version: str

    def __post_init__(self) -> None:
        """Reject incomplete, ambiguous, or mutable identity fields."""
        _require(isinstance(self.phase, str) and re.fullmatch('[A-Z][A-Z0-9_]*', self.phase) is not None,
                 'Invalid phase name')
        _require(isinstance(self.input_ids, tuple) and bool(self.input_ids)
                 and all(isinstance(value, str) and value for value in self.input_ids)
                 and len(set(self.input_ids)) == len(self.input_ids), 'Invalid phase input identities')
        _require(all(_hash(getattr(self, name)) for name in ('task_fingerprint', 'input_sha256',
                 'policy_sha256', 'route_sha256', 'contract_sha256')), 'Invalid phase digest')
        _require(isinstance(self.validator_version, str) and bool(self.validator_version), 'Missing validator version')

    @classmethod
    def build(cls, *, phase: str, task_fingerprint: str, input_ids: tuple[str, ...],
              input_components: Mapping[str, bytes], policy_bytes: bytes,
              route: Mapping[str, object], contract_components: Mapping[str, bytes],
              validator_version: str) -> PhaseKey:
        """Hash original applicable source/package/mapping/profile and schema/Skill/version bytes.

        Components are explicit controller-owned sealed bytes, never mutable Job
        defaults. Include every applicable input and contract component. Mapping
        names are canonicalized; stream identities retain their original order.
        """
        _require(isinstance(policy_bytes, bytes) and isinstance(route, Mapping), 'Invalid policy or route bytes')
        return cls(phase, task_fingerprint, input_ids,
                   _digest(_canonical({'components': _components(input_components), 'input_ids': input_ids})),
                   _digest(policy_bytes), _digest(_canonical(route)),
                   _digest(_canonical(_components(contract_components))), validator_version)

    def to_dict(self) -> dict[str, object]:
        """Render the exact closed key using JSON array stream identities."""
        return _plain(asdict(self))

    @property
    def identity(self) -> str:
        """Name a ledger entry by every key field, preserving stream order."""
        return _digest(_canonical(self.to_dict()))

    @classmethod
    def from_dict(cls, value: object) -> PhaseKey:
        """Validate exact serialized identity fields before constructing a key."""
        raw = _object(value, {field.name for field in fields(cls)})
        _require(isinstance(raw['input_ids'], list), 'Phase input IDs are not an array')
        return cls(**{**raw, 'input_ids': tuple(raw['input_ids'])})


def _validate_physical(key: PhaseKey, artifact: object) -> Mapping[str, object]:
    """Verify receipt, exact response, physical request, route, and local item bindings."""
    value = _object(artifact, {'receipt', 'raw_response', 'request_id', 'route_snapshot', 'attempt', 'item_sha256'})
    receipt = _object(value['receipt'], {field.name for field in fields(ModelPhaseReceipt)})
    _require(isinstance(receipt['provider_metadata'], Mapping)
             and all(isinstance(item, str) and item for name, item in receipt.items()
                     if name != 'provider_metadata'), 'Invalid receipt field types')
    ModelPhaseReceipt(**receipt)
    _require(receipt['phase'] == key.phase, 'Receipt phase differs')
    _require(all(_hash(receipt[name]) for name in ('prompt_sha256', 'input_sha256', 'response_sha256')), 'Invalid receipt digest')
    raw = value['raw_response']
    _require(isinstance(raw, str) and _digest(raw.encode('utf-8')) == receipt['response_sha256'], 'Raw response differs from receipt')
    _decode(raw.encode('utf-8'))
    route = _object(value['route_snapshot'], {'route_id', 'provider', 'model', 'reasoning_effort',
        'capability_fingerprint', 'qualification_status', 'qualification_evidence_sha256', 'routing_policy_version'})
    _require(_digest(_canonical(route)) == key.route_sha256, 'Sealed route hash differs')
    _require(all(route[name] == receipt[name] for name in ('route_id', 'provider', 'model', 'reasoning_effort',
        'qualification_status')), 'Receipt route differs')
    attempt = _object(value['attempt'], {'measurement', 'request', 'raw_response', 'response_identity'})
    measurement = _object(attempt['measurement'], {field.name for field in fields(CallMeasurement)})
    _require(isinstance(measurement['unit_ids'], list), 'Measurement IDs are not an array')
    try:
        call = CallMeasurement(**{**measurement, 'unit_ids': tuple(measurement['unit_ids'])})
    except (TypeError, ValueError) as exc:
        raise _error('Invalid physical measurement') from exc
    _require(call.request_id == value['request_id'] and call.phase == key.phase
             and call.unit_ids == key.input_ids and not call.reused and call.status == 'VALIDATED',
             'Physical request association differs')
    _require(attempt['raw_response'] == raw and call.response_bytes == len(raw.encode('utf-8')),
             'Physical response bytes differ')
    request = _object(attempt['request'], {'prompt', 'schema', 'model', 'reasoning_effort', 'timeout_seconds'})
    _require(isinstance(request['prompt'], str), 'Invalid physical prompt')
    _require(_digest(request['prompt'].encode('utf-8')) == receipt['prompt_sha256']
             and call.request_bytes == len(_canonical(request)), 'Physical request bytes differ')
    prompt = _decode(request['prompt'].encode('utf-8'))
    _require(isinstance(prompt, Mapping) and prompt.get('phase') == key.phase
             and prompt.get('task_version') == receipt['task_version']
             and _digest(_canonical(prompt.get('input'))) == receipt['input_sha256'], 'Physical input or contract differs')
    _require(request['model'] == receipt['model'] and request['reasoning_effort'] ==
             (None if receipt['reasoning_effort'] == 'provider-default' else receipt['reasoning_effort']), 'Physical model differs')
    identity = _object(attempt['response_identity'], {'provider', 'model', 'reasoning_effort', 'metadata'})
    _require(identity['provider'] == receipt['provider'] and identity['metadata'] == receipt['provider_metadata']
             and identity['model'] in (None, '', receipt['model'])
             and identity['reasoning_effort'] in (None, '', receipt['reasoning_effort']),
             'Physical provider identity differs')
    items = value['item_sha256']
    _require(isinstance(items, Mapping) and set(items) <= set(key.input_ids)
             and all(_hash(item) for item in items.values()), 'Invalid local item hashes')
    # Batch validators reconcile the accepted subset and every item hash. Legacy
    # singleton correspondence/footnote phases use an empty local-item mapping.
    if receipt['task_version'] != 'nca-extraction-2.0':
        _require(not items, 'Local item hashes require batch extraction')
    return value


def _windows_process_api() -> tuple[Callable, Callable, Callable, Callable]:
    """Bind non-destructive Win32 process waiting with full-width HANDLE signatures."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel.OpenProcess, kernel.WaitForSingleObject, kernel.CloseHandle, ctypes.get_last_error


def _windows_process_exists(pid: int) -> bool:
    """Treat Windows owners as live unless a process handle or absence proves death.

    Signal zero is destructive on Windows. SYNCHRONIZE is sufficient to wait
    without query, termination, or modification rights. Invalid-parameter means
    absent only with a nonzero, representable DWORD PID and fixed valid arguments;
    denied, failed, or otherwise ambiguous queries never authorize recovery.
    """
    if type(pid) is not int or not 0 < pid <= 0xffffffff:
        return True
    try:
        open_process, wait, close, last_error = _windows_process_api()
        handle = open_process(0x00100000, False, pid)  # SYNCHRONIZE only.
        if not handle:
            return last_error() != 87  # ERROR_INVALID_PARAMETER, absent PID.
        try:
            state = wait(handle, 0)
        finally:
            closed = close(handle)
        return state != 0 or not closed  # Only WAIT_OBJECT_0 proves exit.
    except (OSError, AttributeError, ValueError, OverflowError):
        return True


class NcaWorkspaceLock(WorkspaceLock):
    """Guard NCA directory ownership with a persistent process-held advisory lock.

    Callers authenticate/confine the path first. The sibling ``<name>.guard``
    file is never unlinked: OS ownership releases automatically on process death,
    while strict directory-owner evidence determines whether recovery is safe.
    Hold this guard through directory release so competing recoverers cannot
    delete a newly acquired directory. Acquisition remains nonblocking.
    """

    def __init__(self, path: Path, operation: str) -> None:
        """Enable only strict NCA stale detection and retain the guard descriptor."""
        super().__init__(path, operation, break_stale=True)
        self.guard_path = path.with_name(path.name + '.guard')
        self._guard_fd: int | None = None

    def _existing_owner(self) -> dict[str, object]:
        """Treat absent, symlinked, duplicate-key, or malformed owner records as unknown."""
        if self.owner_file.is_symlink():
            return {}
        try:
            owner = _decode(self.owner_file.read_bytes())
        except (OSError, ValidationError):
            return {}
        return owner if isinstance(owner, dict) else {}

    def _is_stale(self, owner: dict[str, object]) -> bool:
        """Reclaim only a complete same-operation, same-host owner proven dead."""
        if set(owner) != {'pid', 'host', 'operation', 'acquired_utc'}:
            return False
        if (type(owner['pid']) is not int or owner['pid'] <= 0
                or owner['host'] != socket.gethostname() or owner['operation'] != self.operation
                or not isinstance(owner['acquired_utc'], str)):
            return False
        try:
            acquired = datetime.fromisoformat(owner['acquired_utc'])
            if acquired.tzinfo is None:
                return False
            exists = (_windows_process_exists(owner['pid']) if os.name == 'nt'
                      else _process_exists(owner['pid']))
            return not exists
        except (ValueError, OverflowError):
            return False

    def _close_guard(self) -> None:
        """Release process-held ownership by closing without replacing its guard inode."""
        if self._guard_fd is not None:
            descriptor, self._guard_fd = self._guard_fd, None
            os.close(descriptor)

    def acquire(self) -> NcaWorkspaceLock:
        """Serialize acquisition, strict stale recovery, and the entire protected section."""
        if self._guard_fd is not None:
            raise LockError('NCA lock is not reentrant')
        _require(not self.path.is_symlink() and not self.guard_path.is_symlink(), 'Symlink in NCA lock path')
        _require(all(not parent.is_symlink() for parent in self.path.parents), 'Symlink in NCA lock ancestor')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._guard_fd = os.open(self.guard_path,
                os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
            info = os.fstat(self._guard_fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Invalid NCA guard file')
            if os.name == 'nt':
                import msvcrt
                # Windows byte-range locking can lock beyond EOF. Initialize its
                # one persistent byte only after winning that range's ownership.
                msvcrt.locking(self._guard_fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._guard_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if info.st_size == 0:
                os.write(self._guard_fd, b'\0')
                os.fsync(self._guard_fd)
            super().acquire()
        except OSError as exc:
            self._close_guard()
            raise LockError('NCA lock guard is held or unavailable') from exc
        except BaseException:
            self._close_guard()
            raise
        return self

    def release(self) -> None:
        """Release directory ownership before allowing another guard holder to enter."""
        try:
            super().release()
        finally:
            self._close_guard()


class PhaseStore:
    """Serialize immutable attempts and accepted ledger membership inside one task."""

    def __init__(self, task_root: Path, *, task_fingerprint: str) -> None:
        """Require an existing non-symlink task and a full governed fingerprint."""
        _require(isinstance(task_root, Path) and task_root.is_dir() and not task_root.is_symlink(), 'Invalid task root')
        _require(_hash(task_fingerprint), 'Invalid task fingerprint')
        self.task_root = task_root.resolve()
        self.task_fingerprint = task_fingerprint

    def _path(self, relative: str) -> Path:
        """Reject traversal, symlinks, and non-directory ancestors before any I/O."""
        parts = Path(relative).parts
        _require(bool(parts) and not Path(relative).is_absolute() and all(part not in {'.', '..'} for part in parts), 'Path escapes task')
        _require(self.task_root.is_dir() and not self.task_root.is_symlink(), 'Task root changed')
        current = self.task_root
        for index, part in enumerate(parts):
            current = current / part
            _require(not current.is_symlink(), 'Symlink in task checkpoint path')
            if index < len(parts) - 1 and current.exists():
                _require(current.is_dir(), 'Non-directory checkpoint ancestor')
        _require(current.resolve().is_relative_to(self.task_root), 'Path escapes task')
        return current

    def _lock(self) -> WorkspaceLock:
        """Check all store ancestors before the existing lock helper can create paths."""
        for relative in (_PHASE_ROOT + '/attempts', _PHASE_ROOT + '/ledger.json', _PHASE_ROOT + '/publication'):
            self._path(relative)
        self._path('locks/nca-phases.lock.guard')
        return NcaWorkspaceLock(self._path('locks/nca-phases.lock'), 'NCA_PHASE_LEDGER')

    def _read(self, relative: str) -> object:
        """Read only confined strict JSON evidence, translating storage failures."""
        try:
            return _decode(self._path(relative).read_bytes())
        except OSError as exc:
            raise _error('Checkpoint file is unavailable') from exc

    def _key(self, key: PhaseKey) -> None:
        """Reject keys owned by another task before lookup or write."""
        _require(isinstance(key, PhaseKey) and key.task_fingerprint == self.task_fingerprint, 'Phase key belongs to another task')

    def _ledger(self) -> dict[str, object]:
        """Read and validate the entire closed membership ledger while already locked."""
        if not self._path(_PHASE_ROOT + '/ledger.json').exists():
            return {'schema_version': _VERSION, 'task_fingerprint': self.task_fingerprint, 'entries': {}, 'failures': []}
        ledger = _object(self._read(_PHASE_ROOT + '/ledger.json'), {'schema_version', 'task_fingerprint', 'entries', 'failures'})
        _require(ledger['schema_version'] == _VERSION and ledger['task_fingerprint'] == self.task_fingerprint,
                 'Ledger version or task differs')
        _require(isinstance(ledger['entries'], dict) and isinstance(ledger['failures'], list), 'Malformed ledger collections')
        ids = []
        for digest, row in ledger['entries'].items():
            row = _object(row, {'key', 'attempt_id', 'artifact_sha256'})
            key = PhaseKey.from_dict(row['key'])
            self._key(key)
            _require(digest == key.identity and _hash(row['artifact_sha256']), 'Ledger key or content hash differs')
            ids.append(row['attempt_id'])
        for row in ledger['failures']:
            row = _object(row, {'key', 'attempt_id', 'artifact_sha256'})
            self._key(PhaseKey.from_dict(row['key']))
            _require(_hash(row['artifact_sha256']), 'Invalid failure digest')
            ids.append(row['attempt_id'])
        _require(all(isinstance(value, str) and re.fullmatch('[0-9a-f]{32}', value) for value in ids)
                 and len(set(ids)) == len(ids), 'Invalid or repeated attempt identity')
        return dict(ledger)

    def _accepted(self, key: PhaseKey, row: Mapping[str, object], validate: Callable) -> object:
        """Revalidate one exact ledger-member attempt without reacquiring its lock."""
        raw = self._read(f"{_PHASE_ROOT}/attempts/{row['attempt_id']}.json")
        value = _object(raw, {'schema_version', 'task_fingerprint', 'key', 'attempt_id', 'status', 'artifact'})
        _require(value['schema_version'] == _VERSION and value['task_fingerprint'] == self.task_fingerprint
                 and value['key'] == key.to_dict() and value['attempt_id'] == row['attempt_id']
                 and value['status'] == 'CANDIDATE' and _digest(_canonical(value)) == row['artifact_sha256'],
                 'Published attempt identity or bytes differ')
        artifact = _validate_physical(key, value['artifact'])
        result = validate(artifact)
        _require(result is not None, 'Validator returned no accepted evidence')
        return result

    def lookup(self, key: PhaseKey, *, validate: Callable) -> object | None:
        """Return current validated evidence only for an exact accepted same-task key."""
        found = self.lookup_checkpoint(key, validate=validate)
        return None if found is None else found[1]

    def lookup_checkpoint(self, key: PhaseKey, *, validate: Callable) -> tuple[str, object] | None:
        """Return the immutable store ID together with freshly revalidated evidence."""
        self._key(key)
        with self._lock():
            ledger = self._ledger()
            row = ledger['entries'].get(key.identity)
            return None if row is None else (row['attempt_id'], self._accepted(key, row, validate))

    def _write_attempt(self, key: PhaseKey, artifact: Mapping[str, object], status: str) -> tuple[str, dict[str, object]]:
        """Create one unique immutable attempt; accepted files are never replaced."""
        attempt_id = uuid4().hex
        relative = f'{_PHASE_ROOT}/attempts/{attempt_id}.json'
        path = self._path(relative)
        _require(not path.exists(), 'Attempt identity already exists')
        value = {'schema_version': _VERSION, 'task_fingerprint': self.task_fingerprint,
                 'key': key.to_dict(), 'attempt_id': attempt_id, 'status': status, 'artifact': _decode(_canonical(artifact))}
        atomic_write_json(path, value)
        return attempt_id, value

    def commit(self, key: PhaseKey, artifact: Mapping[str, object], *, validate: Callable) -> str:
        """Write attempt, validate exact evidence, then atomically publish membership."""
        self._key(key)
        with self._lock():
            ledger = self._ledger()
            previous = ledger['entries'].get(key.identity)
            if previous is not None:
                self._accepted(key, previous, validate)
                stored = self._read(f"{_PHASE_ROOT}/attempts/{previous['attempt_id']}.json")
                _require(_canonical(stored['artifact']) == _canonical(artifact), 'Accepted phase evidence is immutable')
                return previous['attempt_id']
            attempt_id, value = self._write_attempt(key, artifact, 'CANDIDATE')
            row = {'key': key.to_dict(), 'attempt_id': attempt_id, 'artifact_sha256': _digest(_canonical(value))}
            self._accepted(key, row, validate)
            ledger['entries'][key.identity] = row
            atomic_write_json(self._path(_PHASE_ROOT + '/ledger.json'), ledger)
            return attempt_id

    def record_failure(self, key: PhaseKey, diagnostic: Mapping[str, object]) -> None:
        """Append independent diagnostic evidence without changing accepted membership."""
        self._key(key)
        _require(isinstance(diagnostic, Mapping), 'Failure diagnostic must be an object')
        with self._lock():
            ledger = self._ledger()
            attempt_id, value = self._write_attempt(key, diagnostic, 'FAILED')
            ledger['failures'].append({'key': key.to_dict(), 'attempt_id': attempt_id,
                                       'artifact_sha256': _digest(_canonical(value))})
            atomic_write_json(self._path(_PHASE_ROOT + '/ledger.json'), ledger)

    def failure_diagnostics(self) -> tuple[Mapping[str, object], ...]:
        """Expose only FAILED diagnostics authenticated by exact immutable ledger membership."""
        with self._lock():
            results = []
            for row in self._ledger()['failures']:
                key = PhaseKey.from_dict(row['key'])
                self._key(key)
                raw = self._read(f"{_PHASE_ROOT}/attempts/{row['attempt_id']}.json")
                value = _object(raw, {'schema_version', 'task_fingerprint', 'key', 'attempt_id', 'status', 'artifact'})
                _require(value['schema_version'] == _VERSION and value['task_fingerprint'] == self.task_fingerprint
                    and value['key'] == key.to_dict() and value['attempt_id'] == row['attempt_id']
                    and value['status'] == 'FAILED' and _digest(_canonical(value)) == row['artifact_sha256']
                    and isinstance(value['artifact'], Mapping), 'Failure diagnostic identity or bytes differ')
                results.append({'key': key.to_dict(), 'diagnostic': value['artifact']})
            return tuple(results)

    def _evidence(self, checkpoints: Mapping[str, PhaseKey], validate_phase: Callable) -> dict[str, object]:
        """Require exactly the caller's current checkpoint identities and revalidate each."""
        _require(isinstance(checkpoints, Mapping) and bool(checkpoints), 'Publication requires checkpoints')
        ledger = self._ledger()
        evidence = {}
        for checkpoint, key in checkpoints.items():
            self._key(key)
            row = ledger['entries'].get(key.identity)
            _require(row is not None and row['attempt_id'] == checkpoint, 'Publication checkpoint is not accepted')
            def validate(value: Mapping[str, object]) -> object:
                """Invoke the controller's current validator with this exact phase key."""
                return validate_phase(key, value)
            evidence[checkpoint] = self._accepted(key, row, validate)
        return evidence

    def _final(self, output: object, receipt: object, evidence: Mapping[str, object], validate_final: Callable, output_bytes: bytes) -> object:
        """Bind task/output identity and require controller derivation from current evidence."""
        _require(isinstance(output, Mapping) and isinstance(receipt, Mapping), 'Invalid final objects')
        _require(receipt.get('task_fingerprint') == self.task_fingerprint
                 and receipt.get('output_sha256') == {_OUTPUT: _digest(output_bytes)}, 'Final execution receipt differs')
        result = validate_final(output, receipt, evidence)
        _require(result is not None, 'Final validator returned no accepted evidence')
        return result

    def prepare_publication(self, output: Mapping[str, object], receipt: Mapping[str, object], *,
                            checkpoints: Mapping[str, PhaseKey], validate_phase: Callable, validate_final: Callable) -> str:
        """Durably stage both canonical byte payloads and their checkpoint-bound manifest.

        The final validator must derive or reconcile both objects from revalidated
        checkpoint evidence. A schema-only validator is insufficient authority.
        """
        with self._lock():
            evidence = self._evidence(checkpoints, validate_phase)
            payloads = {}
            for name, value in (('output', output), ('receipt', receipt)):
                payloads[name] = (json.dumps(_decode(_canonical(value)), ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
            self._final(_decode(payloads['output']), _decode(payloads['receipt']), evidence, validate_final, payloads['output'])
            manifest = {'schema_version': _VERSION, 'task_fingerprint': self.task_fingerprint,
                'checkpoints': {checkpoint: key.to_dict() for checkpoint, key in checkpoints.items()},
                'files': {'output': {'path': _OUTPUT, 'sha256': _digest(payloads['output'])},
                          'receipt': {'path': _RECEIPT, 'sha256': _digest(payloads['receipt'])}}}
            manifest_path = self._path(_PHASE_ROOT + '/publication/manifest.json')
            if manifest_path.exists():
                _require(self._read(_PHASE_ROOT + '/publication/manifest.json') == manifest, 'Publication is immutable')
            # Never replace an existing staged file, including an orphan from a
            # preparation crash. An exact byte match can finish that preparation.
            for name, payload in payloads.items():
                path = self._path(f'{_PHASE_ROOT}/publication/{name}.json')
                if path.exists():
                    _require(path.read_bytes() == payload, 'Staged publication bytes differ')
                else:
                    atomic_write_bytes(path, payload)
            if not manifest_path.exists():
                atomic_write_json(manifest_path, manifest)
            return _digest(_canonical(manifest))

    def recover_publication(self, *, checkpoints: Mapping[str, PhaseKey], validate_phase: Callable,
                            validate_final: Callable) -> object | None:
        """Verify both staged files and current evidence before finishing canonical writes."""
        with self._lock():
            manifest_path = self._path(_PHASE_ROOT + '/publication/manifest.json')
            if not manifest_path.exists():
                _require(not any(self._path(path).exists() for path in (_OUTPUT, _RECEIPT)), 'Partial final files lack publication authority')
                return None
            manifest = _object(self._read(_PHASE_ROOT + '/publication/manifest.json'),
                               {'schema_version', 'task_fingerprint', 'checkpoints', 'files'})
            _require(manifest['schema_version'] == _VERSION and manifest['task_fingerprint'] == self.task_fingerprint,
                     'Publication task or version differs')
            evidence = self._evidence(checkpoints, validate_phase)
            _require(manifest['checkpoints'] == {checkpoint: key.to_dict() for checkpoint, key in checkpoints.items()},
                     'Current publication checkpoint set differs')
            files = _object(manifest['files'], {'output', 'receipt'})
            payloads = {}
            for name, canonical in (('output', _OUTPUT), ('receipt', _RECEIPT)):
                row = _object(files[name], {'path', 'sha256'})
                _require(row['path'] == canonical and _hash(row['sha256']), 'Publication destination differs')
                try:
                    payloads[name] = self._path(f'{_PHASE_ROOT}/publication/{name}.json').read_bytes()
                except OSError as exc:
                    raise _error('Staged final file is unavailable') from exc
                _require(_digest(payloads[name]) == row['sha256'], 'Staged final bytes differ')
                destination = self._path(canonical)
                if destination.exists():
                    _require(destination.read_bytes() == payloads[name], 'Existing final output differs')
            result = self._final(_decode(payloads['output']), _decode(payloads['receipt']), evidence, validate_final, payloads['output'])
            for name, canonical in (('output', _OUTPUT), ('receipt', _RECEIPT)):
                destination = self._path(canonical)
                if not destination.exists():
                    atomic_write_bytes(destination, payloads[name])
            return result
