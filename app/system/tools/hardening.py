#!/usr/bin/env python3
"""Run deterministic, isolated SAGE hardening shards and formally combine their receipts."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True

APP_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = APP_ROOT.parent
ROOT = APP_ROOT
sys.path.insert(0, str(APP_ROOT / "system" / "src"))

from sage.storage import storage_layout
from bootstrap_runtime import hardening_worker_cap, load_host_capability
from build_release import _copy_source_tree, _source_tree_sha256

_PYTEST_TERMINAL_RE = re.compile(
    r"^(?:\d+ (?:passed|failed|skipped|deselected|xfailed|xpassed|warnings?|errors?)(?:, )?)+ in [0-9.]+s$"
)
_COLLECTED_RE = re.compile(r"(\d+) tests? collected")
_OUTCOME_RE = re.compile(r"(\d+) (passed|failed|skipped|deselected|xfailed|xpassed|warnings?|errors?)")
RECEIPT_SCHEMA_VERSION = "1.4"
MAX_PYTEST_NODES_PER_PROCESS = 8


def _scheduled_test_batches(
    root: Path,
    *,
    shard_count: int = 1,
    shard_index: int = 0,
) -> tuple[tuple[tuple[str, ...], ...], list[str], list[str]]:
    """Discover every test module and deterministically select one shard by sorted index."""
    discovered = sorted(path.relative_to(root).as_posix() for path in (root / "system" / "tests").glob("test_*.py"))
    errors: list[str] = []
    if shard_count < 1:
        errors.append("shard_count must be at least 1")
        return (), discovered, errors
    if shard_index < 0 or shard_index >= shard_count:
        errors.append(f"shard_index {shard_index} is outside 0..{shard_count - 1}")
        return (), discovered, errors
    scheduled = [path for position, path in enumerate(discovered) if position % shard_count == shard_index]
    batches = tuple((Path(path).stem.removeprefix("test_"), path) for path in scheduled)
    if len(scheduled) != len(set(scheduled)):
        errors.append("scheduled test inventory contains duplicates")
    return batches, discovered, errors


def _bounded_pytest_targets(test_path: str, node_ids: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Return deterministic pytest argv target groups bounded by node count for long modules."""
    if len(node_ids) <= MAX_PYTEST_NODES_PER_PROCESS:
        return ((test_path,),)
    return tuple(
        tuple(node_ids[offset : offset + MAX_PYTEST_NODES_PER_PROCESS])
        for offset in range(0, len(node_ids), MAX_PYTEST_NODES_PER_PROCESS)
    )


def _descendant_pids(parent_pid: int) -> list[int]:
    """Return the current POSIX descendant tree, including new process groups."""
    if os.name == "nt":
        return []
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid="],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, ppid = (int(parts[0]), int(parts[1]))
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    descendants: list[int] = []
    pending = list(children.get(parent_pid, ()))
    while pending:
        pid = pending.pop()
        descendants.append(pid)
        pending.extend(children.get(pid, ()))
    return descendants


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate the child and descendants without depending on pipe closure."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    else:
        descendants = _descendant_pids(process.pid)
        for pid in reversed(descendants):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def _cleanup_completed_process_group(process: subprocess.Popen[str]) -> None:
    """Kill POSIX descendants that outlive a completed command and could retain host handles."""
    if os.name == "nt":
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _pytest_terminal_status(stdout_path: Path) -> str | None:
    """Return PASS/FAIL once pytest has emitted its final terminal summary line."""
    try:
        lines = stdout_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-12:]):
        text = line.strip()
        if not _PYTEST_TERMINAL_RE.fullmatch(text):
            continue
        if re.search(r"\b(?:failed|errors?)\b", text):
            return "FAIL"
        return "PASS"
    return None


def run(command: list[str], cwd: Path, *, name: str, timeout: int = 300) -> dict:
    """Run one isolated command and capture its deterministic result."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTEST_ADDOPTS"] = "-p no:cacheprovider"
    env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
    env["SAGE_HARDENING_ACTIVE"] = "1"
    print(f"START {name}", flush=True)
    with tempfile.TemporaryDirectory(prefix=f"sage-{name}-capture-") as capture_dir:
        capture_root = Path(capture_dir)
        stdout_path = capture_root / "stdout.txt"
        stderr_path = capture_root / "stderr.txt"
        with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout
            timed_out = False
            summary_cleanup = False
            is_pytest = "pytest" in command or ("-m" in command and "pytest" in command)
            while True:
                polled = process.poll()
                if polled is not None:
                    returncode = polled
                    _cleanup_completed_process_group(process)
                    break
                terminal_status = _pytest_terminal_status(stdout_path) if is_pytest else None
                if terminal_status is not None:
                    try:
                        returncode = process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        _terminate_process_tree(process)
                        returncode = 0 if terminal_status == "PASS" else 1
                        summary_cleanup = True
                    break
                if time.monotonic() >= deadline:
                    _terminate_process_tree(process)
                    returncode = 124
                    timed_out = True
                    break
                time.sleep(0.1)
        result = {
            "name": name,
            "command": command,
            "returncode": returncode,
            "stdout": stdout_path.read_text(encoding="utf-8"),
            "stderr": stderr_path.read_text(encoding="utf-8"),
            "timed_out": timed_out,
            "summary_cleanup": summary_cleanup,
        }
    print(f"END {name} rc={result['returncode']}", flush=True)
    return result


def _collect_module_node_ids(target: Path, test_path: str, *, name: str) -> tuple[tuple[str, ...], dict]:
    """Collect exact pytest node IDs for one scheduled module without executing tests."""
    step = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            test_path,
        ],
        target,
        name=f"pytest_collect_{name}",
        timeout=180,
    )
    scheduled = Path(test_path).as_posix()
    parts = Path(scheduled).parts
    accepted_paths = {scheduled}
    if len(parts) > 1:
        accepted_paths.add(Path(*parts[1:]).as_posix())
    collected: list[str] = []
    for line in str(step.get("stdout", "")).splitlines():
        node = line.strip()
        if "::" not in node:
            continue
        reported_path, selector = node.split("::", 1)
        if reported_path not in accepted_paths:
            continue
        collected.append(f"{scheduled}::{selector}")
    nodes = tuple(collected)
    return nodes, step


def _aggregate_pytest_substeps(name: str, test_path: str, collect_step: dict, substeps: list[dict]) -> dict:
    """Aggregate bounded pytest subprocesses into one scheduled-module receipt step."""
    all_steps = [collect_step, *substeps]
    returncode = next((int(step.get("returncode", 1)) for step in all_steps if step.get("returncode") != 0), 0)
    stderr_parts = [str(step.get("stderr", "")) for step in all_steps if step.get("stderr")]
    return {
        "name": f"pytest_{name}",
        "command": [sys.executable, "-m", "pytest", "-q", test_path],
        "returncode": returncode,
        "stdout": "\n".join(str(step.get("stdout", "")).rstrip() for step in substeps if step.get("stdout")) + ("\n" if substeps else ""),
        "stderr": "\n".join(stderr_parts),
        "timed_out": any(bool(step.get("timed_out")) for step in all_steps),
        "summary_cleanup": any(bool(step.get("summary_cleanup")) for step in all_steps),
        "bounded_node_groups": len(substeps),
        "collected_node_ids": sum(1 for step in substeps for arg in step.get("command", []) if isinstance(arg, str) and "::" in arg),
        "substeps": all_steps,
    }


def _outcome_count(step: dict, outcome: str) -> int:
    """Extract a pytest outcome count from one module process terminal summary."""
    counts: dict[str, int] = {}
    for count, label in _OUTCOME_RE.findall(str(step.get("stdout", ""))):
        counts[label] = counts.get(label, 0) + int(count)
    return counts.get(outcome, 0)


def passed_count(step: dict) -> int:
    """Extract the total number of passed tests from pytest output."""
    return _outcome_count(step, "passed")


def _collect_test_count(root: Path) -> tuple[int | None, dict]:
    """Collect the exact test-case inventory without executing tests."""
    step = run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "system/tests"],
        root,
        name="pytest_collect",
        timeout=180,
    )
    matches = _COLLECTED_RE.findall(step.get("stdout", ""))
    count = int(matches[-1]) if matches else None
    return count, step


def _validation_steps(target: Path, *, prefix: str) -> list[dict]:
    """Run the release validators used on both sides of each hardening shard."""
    return [
        run(
            [sys.executable, "system/tools/validate_schemas.py"],
            target,
            name=f"{prefix}_schema_validation",
            timeout=180,
        ),
        run(
            [sys.executable, "system/tools/validate_package.py"],
            target,
            name=f"{prefix}_package_validation",
            timeout=180,
        ),
        run(
            [sys.executable, "system/tools/deep_audit.py", str(target), "--mode", "source"],
            target,
            name=f"{prefix}_deep_audit",
            timeout=180,
        ),
    ]


def _run_test_module_isolated(test_path: str, *, name: str, expected_hash: str) -> dict:
    """Run one test module in a clean source copy, splitting long files into bounded node groups."""
    with tempfile.TemporaryDirectory(prefix=f"sage-hardening-{name}-") as td:
        bundle_target = Path(td) / BUNDLE_ROOT.name
        bundle_target.mkdir(parents=True)
        unknown = _copy_source_tree(BUNDLE_ROOT, bundle_target)
        target = bundle_target / APP_ROOT.name
        if unknown:
            return {
                "name": f"pytest_{name}",
                "command": [],
                "returncode": 125,
                "stdout": "",
                "stderr": "Unclassified source-root entries: " + ", ".join(sorted(set(unknown))),
                "timed_out": False,
                "summary_cleanup": False,
                "workspace_source_sha256": "",
                "workspace_source_sha256_after": "",
                "workspace_governed_source_unchanged": False,
            }
        before_hash = _source_tree_sha256(target)
        if before_hash != expected_hash:
            return {
                "name": f"pytest_{name}",
                "command": [],
                "returncode": 125,
                "stdout": "",
                "stderr": f"Module workspace hash {before_hash} does not match shard source hash {expected_hash}",
                "timed_out": False,
                "summary_cleanup": False,
                "workspace_source_sha256": before_hash,
                "workspace_source_sha256_after": before_hash,
                "workspace_governed_source_unchanged": False,
            }
        node_ids, collect_step = _collect_module_node_ids(target, test_path, name=name)
        if collect_step["returncode"] != 0 or not node_ids:
            step = _aggregate_pytest_substeps(name, test_path, collect_step, [])
            if collect_step["returncode"] == 0 and not node_ids:
                step["returncode"] = 125
                step["stderr"] = (str(step.get("stderr") or "") + "\nNo pytest node IDs collected for scheduled module.\n").strip()
        else:
            targets = _bounded_pytest_targets(test_path, node_ids)
            substeps: list[dict] = []
            for index, target_args in enumerate(targets, start=1):
                suffix = "" if len(targets) == 1 else f"_part_{index:02d}_of_{len(targets):02d}"
                substeps.append(
                    run(
                        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *target_args],
                        target,
                        name=f"pytest_{name}{suffix}",
                        timeout=300,
                    )
                )
                if substeps[-1]["returncode"] != 0:
                    break
            step = _aggregate_pytest_substeps(name, test_path, collect_step, substeps)
        after_hash = _source_tree_sha256(target)
        unchanged = before_hash == after_hash == expected_hash
        step["workspace_source_sha256"] = before_hash
        step["workspace_source_sha256_after"] = after_hash
        step["workspace_governed_source_unchanged"] = unchanged
        if not unchanged and step["returncode"] == 0:
            step["returncode"] = 125
            step["stderr"] = (
                str(step.get("stderr") or "")
                + f"\nGoverned source mutated in isolated module workspace: {before_hash} -> {after_hash}\n"
            )
        return step


def run_shard(*, shard_count: int, shard_index: int) -> dict:
    """Run one isolated deterministic hardening shard and return its bound receipt."""
    original_hash_before = _source_tree_sha256(APP_ROOT)
    capability, capability_source = load_host_capability(APP_ROOT)
    worker_cap, worker_source = hardening_worker_cap(capability)
    with tempfile.TemporaryDirectory(prefix=f"sage-hardening-shard-{shard_index:02d}-") as td:
        bundle_target = Path(td) / BUNDLE_ROOT.name
        bundle_target.mkdir(parents=True)
        unknown = _copy_source_tree(BUNDLE_ROOT, bundle_target)
        target = bundle_target / APP_ROOT.name
        if unknown:
            return {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "status": "FAIL",
                "errors": [f"Unclassified source-root entry: {item}" for item in sorted(set(unknown))],
                "warnings": [],
                "shard_count": shard_count,
                "shard_index": shard_index,
                "source_tree_sha256": original_hash_before,
            }
        source_tree_sha256 = _source_tree_sha256(target)
        test_batches, discovered_tests, inventory_errors = _scheduled_test_batches(
            target, shard_count=shard_count, shard_index=shard_index
        )
        scheduled_tests = [path for batch in test_batches for path in batch[1:]]
        steps: list[dict] = []
        steps.append(
            run(
                [sys.executable, "system/tools/reset_project_state.py", "--settings", "ecosystem.yml"],
                target,
                name="reset_state",
            )
        )
        steps.extend(_validation_steps(target, prefix="pre"))
        test_cases_discovered, collection_step = _collect_test_count(target)
        steps.append(collection_step)

        worker_limit = min(worker_cap, len(test_batches)) if test_batches else 1
        with ThreadPoolExecutor(max_workers=worker_limit) as executor:
            futures = []
            for batch in test_batches:
                name, *test_paths = batch
                if len(test_paths) != 1:
                    raise RuntimeError(f"Hardening batch {name!r} must contain exactly one test module")
                futures.append(
                    executor.submit(
                        _run_test_module_isolated,
                        test_paths[0],
                        name=name,
                        expected_hash=source_tree_sha256,
                    )
                )
            steps.extend(future.result() for future in futures)
        steps.append(
            run(
                [sys.executable, "system/tools/reset_project_state.py", "--settings", "ecosystem.yml"],
                target,
                name="post_test_reset",
            )
        )
        steps.extend(_validation_steps(target, prefix="post"))
        target_hash_after = _source_tree_sha256(target)

    original_hash_after = _source_tree_sha256(APP_ROOT)
    pytest_steps = [step for step in steps if step["name"].startswith("pytest_") and step["name"] != "pytest_collect"]
    module_workspaces_unchanged = all(
        step.get("workspace_governed_source_unchanged") is True for step in pytest_steps
    )
    tests_passed = sum(_outcome_count(step, "passed") for step in pytest_steps)
    tests_failed = sum(_outcome_count(step, "failed") + _outcome_count(step, "errors") for step in pytest_steps)
    tests_skipped = sum(_outcome_count(step, "skipped") for step in pytest_steps)
    source_unchanged = (
        source_tree_sha256 == target_hash_after == original_hash_before == original_hash_after
        and module_workspaces_unchanged
    )
    errors = list(inventory_errors)
    if test_cases_discovered is None:
        errors.append("pytest collection count could not be determined")
    if not source_unchanged:
        errors.append("governed source hash changed during hardening")
    if any(step["returncode"] != 0 for step in steps):
        errors.append("one or more hardening steps failed")
    status = "PASS" if not errors else "FAIL"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "isolated_copy": True,
        "state_reset_before_test": True,
        "cache_provider_disabled": True,
        "source_tree_sha256": source_tree_sha256,
        "source_tree_sha256_after": target_hash_after,
        "original_source_tree_sha256_after": original_hash_after,
        "governed_source_unchanged": source_unchanged,
        "module_workspaces_isolated": True,
        "module_workspaces_unchanged": module_workspaces_unchanged,
        "shard_count": shard_count,
        "shard_index": shard_index,
        "pytest_batches": len(test_batches),
        "parallel_workers": worker_limit,
        "worker_policy_source": worker_source,
        "host_capability_source": capability_source,
        "host_capability": capability,
        "test_files_discovered": len(discovered_tests),
        "test_files_scheduled": len(scheduled_tests),
        "test_inventory_complete": not inventory_errors,
        "discovered_tests": discovered_tests,
        "scheduled_tests": scheduled_tests,
        "test_cases_discovered": test_cases_discovered,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "tests_skipped": tests_skipped,
        "errors": errors,
        "warnings": [],
        "steps": steps,
    }


def combine_reports(paths: list[Path], *, expected_source_sha256: str | None = None) -> dict:
    """Formally combine shard receipts and prove complete, exactly-once test-module coverage."""
    errors: list[str] = []
    warnings: list[str] = []
    receipts: list[dict] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Invalid shard receipt {path}: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"Invalid shard receipt root {path}")
            continue
        receipts.append(value)
    if not receipts:
        return {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "status": "FAIL",
            "formal_combine": "FAIL",
            "errors": errors or ["No shard receipts supplied"],
            "warnings": warnings,
        }

    # Validate shard identity and source binding before aggregating any test outcomes.
    shard_counts = {int(row.get("shard_count", -1)) for row in receipts}
    shard_indices = [int(row.get("shard_index", -1)) for row in receipts]
    source_hashes = {str(row.get("source_tree_sha256") or "") for row in receipts}
    discovered_sets = {tuple(row.get("discovered_tests") or []) for row in receipts}
    collected_counts = {row.get("test_cases_discovered") for row in receipts}

    if len(shard_counts) != 1:
        errors.append("Shard receipts disagree on shard_count")
        shard_count = -1
    else:
        shard_count = next(iter(shard_counts))
    if shard_count < 1:
        errors.append("Invalid shard_count in receipts")
    if len(receipts) != shard_count:
        errors.append(f"Expected {shard_count} shard receipts, received {len(receipts)}")
    expected_indices = list(range(max(shard_count, 0)))
    if sorted(shard_indices) != expected_indices:
        errors.append(f"Shard indices must be exactly {expected_indices}; received {sorted(shard_indices)}")
    if len(set(shard_indices)) != len(shard_indices):
        errors.append("Duplicate shard index detected")
    if len(source_hashes) != 1 or "" in source_hashes:
        errors.append("Shard receipts do not bind to one source hash")
        source_hash = ""
    else:
        source_hash = next(iter(source_hashes))
    current_hash = _source_tree_sha256(APP_ROOT)
    required_hash = expected_source_sha256 or current_hash
    if source_hash and source_hash != required_hash:
        errors.append(f"Receipt source hash {source_hash} does not match required source hash {required_hash}")
    if current_hash != required_hash:
        errors.append(f"Current governed source hash {current_hash} does not match required source hash {required_hash}")
    if len(discovered_sets) != 1:
        errors.append("Shard receipts disagree on discovered test-module inventory")
        discovered: list[str] = []
    else:
        discovered = list(next(iter(discovered_sets)))
    if len(collected_counts) != 1 or None in collected_counts:
        errors.append("Shard receipts disagree on discovered test-case count")
        test_cases_discovered = None
    else:
        test_cases_discovered = int(next(iter(collected_counts)))

    scheduled_all: list[str] = []
    by_index = {int(row.get("shard_index", -1)): row for row in receipts}
    if shard_count > 0 and discovered:
        for index in range(shard_count):
            expected = [path for position, path in enumerate(discovered) if position % shard_count == index]
            actual = list(by_index.get(index, {}).get("scheduled_tests") or [])
            if actual != expected:
                errors.append(f"Shard {index} scheduled inventory does not match deterministic assignment")
            scheduled_all.extend(actual)
    duplicates = sorted({path for path in scheduled_all if scheduled_all.count(path) > 1})
    missing = sorted(set(discovered) - set(scheduled_all))
    extras = sorted(set(scheduled_all) - set(discovered))
    if duplicates:
        errors.append("Test modules scheduled more than once: " + ", ".join(duplicates))
    if missing:
        errors.append("Discovered test modules not scheduled: " + ", ".join(missing))
    if extras:
        errors.append("Unknown scheduled test modules: " + ", ".join(extras))
    if len(scheduled_all) != len(discovered):
        errors.append("Scheduled test-module count does not equal discovered inventory")

    for row in receipts:
        index = row.get("shard_index")
        if row.get("status") != "PASS":
            errors.append(f"Shard {index} status is not PASS")
        if row.get("governed_source_unchanged") is not True:
            errors.append(f"Shard {index} did not prove governed-source immutability")
        if row.get("warnings"):
            warnings.extend(f"Shard {index}: {item}" for item in row.get("warnings", []))
        if row.get("errors"):
            errors.extend(f"Shard {index}: {item}" for item in row.get("errors", []))

    tests_passed = sum(int(row.get("tests_passed") or 0) for row in receipts)
    tests_failed = sum(int(row.get("tests_failed") or 0) for row in receipts)
    tests_skipped = sum(int(row.get("tests_skipped") or 0) for row in receipts)
    if tests_failed:
        errors.append(f"Hardening execution recorded {tests_failed} failed/error test outcomes")
    if test_cases_discovered is not None and tests_passed + tests_skipped != test_cases_discovered:
        errors.append(
            "Executed test outcomes do not cover the collected test-case inventory: "
            f"passed={tests_passed} skipped={tests_skipped} collected={test_cases_discovered}"
        )

    status = "PASS" if not errors and not warnings else "FAIL"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "formal_combine": status,
        "source_tree_sha256": source_hash,
        "current_source_tree_sha256": current_hash,
        "governed_source_unchanged": source_hash == current_hash == required_hash,
        "shard_count": shard_count,
        "shards_combined": len(receipts),
        "shard_results": [
            {
                "shard_index": row.get("shard_index"),
                "status": row.get("status"),
                "test_files_scheduled": row.get("test_files_scheduled"),
                "tests_passed": row.get("tests_passed"),
                "tests_skipped": row.get("tests_skipped"),
            }
            for row in sorted(receipts, key=lambda value: int(value.get("shard_index", -1)))
        ],
        "test_files_discovered": len(discovered),
        "test_files_scheduled": len(scheduled_all),
        "test_modules_scheduled_exactly_once": not duplicates and not missing and not extras and len(scheduled_all) == len(discovered),
        "test_cases_discovered": test_cases_discovered,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "tests_skipped": tests_skipped,
        "schema_validation": "PASS" if all(
            any(step.get("name") == "post_schema_validation" and step.get("returncode") == 0 for step in row.get("steps", []))
            for row in receipts
        ) else "FAIL",
        "package_validation": "PASS" if all(
            any(step.get("name") == "post_package_validation" and step.get("returncode") == 0 for step in row.get("steps", []))
            for row in receipts
        ) else "FAIL",
        "deep_audit": "PASS" if all(
            any(step.get("name") == "post_deep_audit" and step.get("returncode") == 0 for step in row.get("steps", []))
            for row in receipts
        ) else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "receipt_files": [str(path) for path in paths],
    }


def _output_path(raw: str | None) -> Path:
    """Resolve qualification output outside the Git-controlled Core tree by default."""
    if raw in (None, ""):
        output = storage_layout(APP_ROOT, create=True).diagnostics_root / "qualification" / "hardening-report.json"
    else:
        output = Path(raw).expanduser()
        if not output.is_absolute():
            output = storage_layout(APP_ROOT, create=True).diagnostics_root / "qualification" / output
        output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def main() -> int:
    """Run one hardening shard or formally combine a complete receipt set."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Receipt path; relative paths are placed under localdata/.system/diagnostics/qualification")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--combine", nargs="+", metavar="RECEIPT")
    parser.add_argument("--expected-source-sha256")
    args = parser.parse_args()

    if args.combine:
        report = combine_reports(
            [Path(value).resolve() for value in args.combine],
            expected_source_sha256=args.expected_source_sha256,
        )
    else:
        report = run_shard(shard_count=args.shard_count, shard_index=args.shard_index)

    output = _output_path(args.output)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report.get("status"),
        "source_tree_sha256": report.get("source_tree_sha256"),
        "tests_passed": report.get("tests_passed"),
        "tests_skipped": report.get("tests_skipped"),
        "report": str(output),
    }, indent=2))
    return 0 if report.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
