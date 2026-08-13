#!/usr/bin/env python3
"""Run isolated, cache-free SAGE hardening from a clean temporary source copy."""
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
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]

from build_release import _copy_source_tree, _source_tree_sha256

def _scheduled_test_batches(root: Path) -> tuple[tuple[tuple[str, ...], ...], list[str], list[str]]:
    """Discover every test module and isolate each module in its own pytest process."""
    discovered = sorted(path.relative_to(root).as_posix() for path in (root / "tests").glob("test_*.py"))
    batches = tuple((Path(path).stem.removeprefix("test_"), path) for path in discovered)
    scheduled = [path for batch in batches for path in batch[1:]]
    inventory_errors = sorted(set(discovered) - set(scheduled))
    return batches, discovered, inventory_errors


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


def run(command: list[str], cwd: Path, *, name: str, timeout: int = 300) -> dict:
    """Run one isolated command and capture its deterministic result."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_ADDOPTS"] = "-p no:cacheprovider"
    env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
    env["SAGE_HARDENING_ACTIVE"] = "1"
    print(f"START {name}", flush=True)
    with tempfile.TemporaryDirectory(prefix=f"sage-{name}-capture-") as capture_dir:
        capture_root = Path(capture_dir)
        stdout_path = capture_root / "stdout.txt"
        stderr_path = capture_root / "stderr.txt"
        # Named regular files match shell redirection and prevent output-pipe
        # ownership from affecting completion of descendant test processes.
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
            try:
                returncode = process.wait(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process)
                returncode = 124
                timed_out = True
        result = {
            "name": name,
            "command": command,
            "returncode": returncode,
            "stdout": stdout_path.read_text(encoding="utf-8"),
            "stderr": stderr_path.read_text(encoding="utf-8"),
            "timed_out": timed_out,
        }
    print(f"END {name} rc={result['returncode']}", flush=True)
    return result


def passed_count(step: dict) -> int:
    """Extract the total number of passed tests from pytest output."""
    matches = re.findall(r"(\d+) passed", str(step.get("stdout", "")))
    return int(matches[-1]) if matches else 0


def main() -> int:
    """Run the command-line entry point and return its process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="hardening-report.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="sage-hardening-") as td:
        target = Path(td) / ROOT.name
        target.mkdir(parents=True)
        unknown = _copy_source_tree(ROOT, target)
        if unknown:
            print("ERROR: Unclassified source-root entries:", file=sys.stderr)
            for item in sorted(set(unknown)):
                print(f"- {item}", file=sys.stderr)
            return 2
        source_tree_sha256 = _source_tree_sha256(target)
        test_batches, discovered_tests, inventory_errors = _scheduled_test_batches(target)
        if inventory_errors:
            print("ERROR: Hardening test inventory is inconsistent:", file=sys.stderr)
            for item in inventory_errors:
                print(f"- {item}", file=sys.stderr)
            return 2
        steps: list[dict] = []
        steps.append(
            run(
                [sys.executable, "scripts/reset_project_state.py", "--settings", "ecosystem.yml"],
                target,
                name="reset_state",
            )
        )
        steps.append(
            run(
                [sys.executable, "scripts/validate_package.py"],
                target,
                name="pre_package_validation",
            )
        )
        steps.append(
            run(
                [sys.executable, "scripts/deep_audit.py", str(target), "--mode", "source"],
                target,
                name="pre_deep_audit",
            )
        )
        # Test modules remain process-isolated, but independent modules run concurrently to keep
        # the release gate practical on macOS, Linux, and Windows without changing test scope.
        requested_workers = os.environ.get("SAGE_HARDENING_WORKERS", "4").strip()
        try:
            worker_cap = max(1, min(8, int(requested_workers)))
        except ValueError:
            worker_cap = 4
        worker_limit = min(worker_cap, len(test_batches)) if test_batches else 1
        with ThreadPoolExecutor(max_workers=worker_limit) as executor:
            futures = []
            for batch in test_batches:
                name, *test_paths = batch
                futures.append(
                    executor.submit(
                        run,
                        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *test_paths],
                        target,
                        name=f"pytest_{name}",
                        timeout=300,
                    )
                )
            steps.extend(future.result() for future in futures)
        steps.append(
            run(
                [sys.executable, "scripts/reset_project_state.py", "--settings", "ecosystem.yml"],
                target,
                name="post_test_reset",
            )
        )
        steps.append(
            run(
                [sys.executable, "scripts/validate_package.py"],
                target,
                name="post_package_validation",
            )
        )
        steps.append(
            run(
                [sys.executable, "scripts/deep_audit.py", str(target), "--mode", "source"],
                target,
                name="post_deep_audit",
            )
        )
        status = "PASS" if all(step["returncode"] == 0 for step in steps) else "FAIL"
        report = {
            "schema_version": "1.2",
            "status": status,
            "isolated_copy": True,
            "state_reset_before_test": True,
            "cache_provider_disabled": True,
            "source_tree_sha256": source_tree_sha256,
            "pytest_batches": len(test_batches),
            "parallel_workers": worker_limit,
            "test_files_discovered": len(discovered_tests),
            "test_files_scheduled": sum(len(batch) - 1 for batch in test_batches),
            "test_inventory_complete": True,
            "tests_passed": sum(passed_count(step) for step in steps if step["name"].startswith("pytest_")),
            "steps": steps,
        }
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "tests_passed": report["tests_passed"], "report": str(output)}, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
