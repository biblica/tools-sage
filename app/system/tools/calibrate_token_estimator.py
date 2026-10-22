#!/usr/bin/env python3
"""Token-estimator calibration: one weight table per governed tokenizer, from real token counts.

No hand labelling: every number is a real token count or a deterministic fit.

1. count -- each sample is a fixed character window of one Scripture book (fit: John, or Psalms for
            Hebrew; held-out: Romans, or Isaiah for Hebrew). Real tokens are counted for each
            tokenizer:
            * o200k  -- the Codex tokenizer, counted locally with tiktoken (an optional developer
                        dependency, never part of SAGE's runtime);
            * codex:<model> -- counted per Codex model through `codex exec --json` on the
                        Operator's ChatGPT workspace: the `turn.completed` usage of a prompt carrying
                        the sample minus that of the same prompt with no sample (input tokens,
                        which include cached input). Not yet run: the workspace was out of credits
                        on 2026-10-22, so the usage shape is verified on the first run;
            * claude:<model> -- counted per Claude model (tokenizers differ between model
                        lines) through SAGE's own sealed Claude executor on the Operator's
                        subscription: the usage of a prompt carrying the sample minus the usage of
                        the same prompt with no sample (input + cache creation + cache reads).
            Counts are cached in counts.json by sample text hash, so a re-run never spends quota
            twice.
2. fit   -- per tokenizer, the two-stage fit of TOKEN-ESTIMATOR-CALIBRATION.md. ASCII: the space
            weight stays at its v2 value (per character, letters and spaces are almost collinear, so
            least squares drives one of them to zero), punctuation is fitted by least squares on
            the Latin-script samples, and the letter weight is then raised to cover the worst Latin
            sample. Every other script's weight comes from that script's samples (the highest value,
            so estimates err high; Arabic letters/marks and Hebrew letters/cantillation are solved
            jointly). Each tokenizer keeps its own table: SAGE estimates with the table of the
            selected provider and routed model. The report gives held-out accuracy per table, the
            current o200k table checked against fresh o200k counts, and how many times more tokens
            each tokenizer spends than o200k on the same Scripture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sage import evidence  # noqa: E402
from sage.stc import strip_hebrew_cantillation  # noqa: E402

BUNDLED = ROOT / "resources" / "scripture" / "original-language"
FIT_CHARS = 3500
HELDOUT_CHARS = 2500
FLOOR_CLASSES = {"latin_ext": 0.5, "symbol": 0.5, "ascii_space": 0.4702}
ASCII_CLASSES = ("ascii_alnum", "ascii_punct")
# (label, Paratext project folder or "@GRK"/"@HEB", script group). Latin samples fit the ASCII weights.
SAMPLES: tuple[tuple[str, str, str], ...] = (
    ("English", "usNIVv2", "latin"), ("French", "freBDS15", "latin"), ("German", "deHFAv3", "latin"),
    ("Indonesian", "idKKHv0", "latin"), ("Swahili", "swhNEN14", "latin"), ("Cebuano", "cebAPDv4", "latin"),
    ("Spanish", "spaNVIv3", "latin"),
    ("Arabic", "arNAV12", "arabic"), ("Persian", "faPCBv3", "arabic"), ("Urdu", "urUCV24", "arabic"),
    ("Russian", "ruCARS23", "cyrillic"), ("Ukrainian", "ukrNPUv1", "cyrillic"),
    ("Hindi", "hiHCVv3", "devanagari"), ("Bengali", "bnBSVv1", "bengali"), ("Punjabi", "paPCVv1", "gurmukhi"),
    ("Oriya", "orNIBVv1", "oriya"), ("Malayalam", "mlMSVv1", "malayalam"), ("Sinhala", "siSCVv0", "sinhala"),
    ("Thai", "thNCVv2", "thai"), ("Lao", "loLCVv1", "lao"), ("Tigrinya", "tirTSVv1", "ethiopic"),
    ("Chinese", "zhsCCBv4", "cjk"), ("Greek", "@GRK", "greek"), ("Hebrew", "@HEB", "hebrew"),
)
SCRIPT_CLASSES = {"arabic": ("arabic", "arabic_mark"), "hebrew": ("hebrew", "hebrew_cantillation")}


def _book_file(folder: Path, book: str) -> Path:
    """Return the one SFM file of `book` in a Paratext or bundled folder."""
    matches = sorted(path for path in folder.iterdir()
                     if path.suffix.lower() == ".sfm" and re.search(book, path.name, re.IGNORECASE))
    if not matches:
        raise SystemExit(f"no {book} book in {folder}")
    return matches[0]


def _window(path: Path, size: int) -> str:
    """Return the first `size` characters of a book from its first chapter, cut at a line end."""
    text = path.read_bytes().decode("utf-8")
    start = text.find("\\c 1")
    body = text[start if start >= 0 else 0:]
    cut = body.rfind("\n", 0, size)
    return body[: cut if cut > 0 else size]


def build_samples(projects_root: Path) -> list[dict[str, Any]]:
    """Return every fit and held-out sample text with its identity and script group."""
    rows: list[dict[str, Any]] = []
    for label, source, script in SAMPLES:
        if source.startswith("@"):
            folder = BUNDLED / source[1:].lower()
        else:
            folder = projects_root / source
        fit_book, heldout_book = ("PSA", "ISA") if script == "hebrew" else ("JHN", "ROM")
        for split, book, size in (("fit", fit_book, FIT_CHARS), ("heldout", heldout_book, HELDOUT_CHARS)):
            text = _window(_book_file(folder, book), size)
            rows.append({"label": label, "source": source, "script": script, "split": split, "book": book, "text": text})
            if script == "hebrew":
                rows.append({"label": label + " (no cantillation)", "source": source, "script": script,
                             "split": split, "book": book, "text": strip_hebrew_cantillation(text)})
    for row in rows:
        row["id"] = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()[:16]
        row["classes"] = dict(Counter(evidence.character_class(char) for char in row["text"]))
    return rows


def o200k_counter() -> Callable[[str], int]:
    """Return a local o200k_base token counter (requires tiktoken in the calling environment)."""
    try:
        import tiktoken
    except ModuleNotFoundError:
        raise SystemExit("o200k counting needs tiktoken: run this tool from an environment with `pip install tiktoken`")
    encoding = tiktoken.get_encoding("o200k_base")
    return lambda text: len(encoding.encode(text))


def claude_counter(model: str) -> Callable[[str], int]:
    """Return a Claude token counter that measures usage through SAGE's sealed executor."""
    from sage.executors.base import ProviderRequest
    from sage.executors.claude_cli import ClaudeCLIExecutor

    executor = ClaudeCLIExecutor()
    status = executor.status(model=model, reasoning_effort="low")
    if not status.ready:
        raise SystemExit(f"Claude is not ready: {status.diagnostic}")
    schema = {"type": "object", "additionalProperties": False, "required": ["status"],
              "properties": {"status": {"type": "string", "enum": ["OK"]}}}

    def prompt_tokens(text: str) -> int:
        """Return the total prompt tokens Claude reports for one calibration prompt."""
        prompt = "Calibration sample; do not analyze it. Reply with status OK.\n\n" + text
        response = executor.execute_prevalidated(
            ProviderRequest(prompt=prompt, schema=schema, model=model, reasoning_effort="low", timeout_seconds=600),
            status,
        )
        usage = response.metadata["usage"]
        return sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))

    baseline = prompt_tokens("")
    return lambda text: prompt_tokens(text) - baseline


def codex_counter(model: str) -> Callable[[str], int]:
    """Return a Codex token counter that reads `codex exec --json` turn usage."""
    import subprocess
    import tempfile

    from sage.executors.codex_cli import CodexCLIExecutor

    executor = CodexCLIExecutor()
    if not executor.quick_status().ready:
        raise SystemExit("Codex CLI is not signed in with ChatGPT")

    def prompt_tokens(text: str) -> int:
        """Return the input tokens Codex reports for one calibration prompt."""
        prompt = "Calibration sample; do not analyze it. Reply with status OK.\n\n" + text
        with tempfile.TemporaryDirectory(prefix="sage-calibrate-") as tmp:
            schema = Path(tmp) / "schema.json"
            schema.write_text(json.dumps({"type": "object", "additionalProperties": False, "required": ["status"],
                                          "properties": {"status": {"type": "string", "enum": ["OK"]}}}), encoding="utf-8")
            args = ["--config", 'model_reasoning_effort="low"', "exec", "--json", "--ephemeral", "--ignore-user-config",
                    "--ignore-rules", "--color", "never", "--sandbox", "read-only", "--skip-git-repo-check",
                    "--output-schema", str(schema), "--model", model, "-"]
            completed = subprocess.run(executor._command_argv(args), input=prompt, capture_output=True, text=True,  # noqa: SLF001
                                       encoding="utf-8", env=executor._environment(), cwd=tmp, timeout=600)  # noqa: SLF001
        events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
        usage = next((event.get("usage") for event in events if event.get("type") == "turn.completed"), None)
        if not isinstance(usage, dict) or usage.get("input_tokens") is None:
            failure = next((event for event in events if event.get("type") in {"error", "turn.failed"}), events[-1:] or None)
            raise SystemExit(f"Codex reported no turn usage for {model}: {failure}")
        return int(usage["input_tokens"])

    baseline = prompt_tokens("")
    return lambda text: prompt_tokens(text) - baseline


def count(samples: list[dict[str, Any]], work: Path, tokenizer: str, counter: Callable[[str], int]) -> dict[str, Any]:
    """Count every sample once per tokenizer, reusing cached counts."""
    path = work / "counts.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    bucket = cache.setdefault(tokenizer, {})
    for row in samples:
        if row["id"] not in bucket:
            bucket[row["id"]] = counter(row["text"])
            path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
            print(f"{tokenizer:7} {row['label']:28} {row['split']:8} {bucket[row['id']]}", flush=True)
    return cache


def _solve(rows: list[list[float]], targets: list[float]) -> list[float]:
    """Least squares by normal equations (few unknowns), via Gauss-Jordan elimination."""
    size = len(rows[0])
    matrix = [[sum(r[i] * r[j] for r in rows) for j in range(size)] + [sum(r[i] * t for r, t in zip(rows, targets))]
              for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(matrix[r][col]))
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        for r in range(size):
            if r != col and matrix[col][col]:
                factor = matrix[r][col] / matrix[col][col]
                matrix[r] = [a - factor * b for a, b in zip(matrix[r], matrix[col])]
    return [matrix[i][size] / matrix[i][i] if matrix[i][i] else 0.0 for i in range(size)]


def fit(samples: list[dict[str, Any]], counts: dict[str, int]) -> dict[str, float]:
    """Fit one tokenizer's weights with the two-stage method."""
    train = [row for row in samples if row["split"] == "fit"]

    def residual(row: dict[str, Any], weights: dict[str, float]) -> float:
        """Return real tokens not explained by the already fitted classes."""
        known = sum(weights.get(name, 0.0) * amount for name, amount in row["classes"].items())
        return counts[row["id"]] - known

    weights: dict[str, float] = dict(FLOOR_CLASSES)
    latin = [row for row in train if row["script"] == "latin"]
    solved = _solve([[float(row["classes"].get(name, 0)) for name in ASCII_CLASSES] for row in latin],
                    [residual(row, weights) for row in latin])
    weights.update({name: round(max(value, 0.0), 4) for name, value in zip(ASCII_CLASSES, solved)})
    weights["ascii_alnum"] = round(max(
        (residual(row, {**weights, "ascii_alnum": 0.0}) / row["classes"]["ascii_alnum"]) for row in latin
    ), 4)
    for script in sorted({row["script"] for row in train} - {"latin"}):
        rows = [row for row in train if row["script"] == script]
        classes = SCRIPT_CLASSES.get(script, (script,))
        if len(classes) == 1:
            values = [residual(row, weights) / row["classes"][script] for row in rows if row["classes"].get(script)]
            weights[script] = round(max(values), 4)
        else:
            solved = _solve([[float(row["classes"].get(name, 0)) for name in classes] for row in rows],
                            [residual(row, weights) for row in rows])
            weights.update({name: round(max(value, 0.0), 4) for name, value in zip(classes, solved)})
    return weights


def estimate(row: dict[str, Any], weights: dict[str, float]) -> float:
    """Estimate one sample with a weight table (uncalibrated classes cost 1.0)."""
    return sum(weights.get(name, 1.0) * amount for name, amount in row["classes"].items())


def report(samples: list[dict[str, Any]], cache: dict[str, Any]) -> dict[str, Any]:
    """Fit every counted tokenizer and report held-out accuracy and token density versus o200k."""
    fitted = {tokenizer: fit(samples, counts) for tokenizer, counts in cache.items()}
    heldout = [row for row in samples if row["split"] == "heldout"]
    accuracy = {
        tokenizer: {row["label"]: round(estimate(row, fitted[tokenizer]) / counts[row["id"]], 2) for row in heldout}
        for tokenizer, counts in cache.items()
    }
    current = dict(evidence._TOKENS_PER_CHARACTER)
    result: dict[str, Any] = {"weights_by_tokenizer": fitted, "heldout_estimate_over_real": accuracy}
    if "o200k" in cache:
        result["current_table_heldout_over_o200k"] = {
            row["label"]: round(estimate(row, current) / cache["o200k"][row["id"]], 2) for row in heldout
        }
        result["tokens_relative_to_o200k"] = {
            tokenizer: round(statistics.median(counts[row["id"]] / cache["o200k"][row["id"]] for row in samples), 2)
            for tokenizer, counts in cache.items() if tokenizer != "o200k"
        }
    return result


def main(argv: list[str] | None = None) -> int:
    """Count real tokens per tokenizer, then fit and report one weight table per tokenizer."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--projects-root", type=Path, required=True, help="Paratext Projects folder")
    parser.add_argument("--work", type=Path, required=True, help="folder for counts.json and report.json")
    parser.add_argument("--tokenizer", action="append", choices=("o200k", "claude", "codex"), default=None)
    parser.add_argument("--codex-model", action="append", default=None,
                        help="Codex model to count (repeat; default gpt-6.1-sol and gpt-5.6-sol)")
    parser.add_argument("--claude-model", action="append", default=None,
                        help="Claude model to count (repeat; default claude-opus-5-5)")
    parser.add_argument("--step", choices=("count", "fit", "all"), default="all")
    args = parser.parse_args(argv)
    args.work.mkdir(parents=True, exist_ok=True)
    samples = build_samples(args.projects_root)
    cache: dict[str, Any] = {}
    if args.step in {"count", "all"}:
        for tokenizer in args.tokenizer or ["o200k", "claude"]:
            if tokenizer == "o200k":
                cache = count(samples, args.work, "o200k", o200k_counter())
                continue
            if tokenizer == "codex":
                for model in args.codex_model or ["gpt-6.1-sol", "gpt-5.6-sol"]:
                    cache = count(samples, args.work, f"codex:{model}", codex_counter(model))
                continue
            for model in args.claude_model or ["claude-opus-5-5"]:
                cache = count(samples, args.work, f"claude:{model}", claude_counter(model))
    if args.step in {"fit", "all"}:
        cache = json.loads((args.work / "counts.json").read_text(encoding="utf-8"))
        result = report(samples, {name: values for name, values in cache.items() if values})
        (args.work / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
