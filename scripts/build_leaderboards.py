#!/usr/bin/env python3
"""
Regenerate leaderboards/*.csv from results/**/*.yaml.

Usage:
    python scripts/build_leaderboards.py [--results-dir results] [--out-dir leaderboards]

Expects result YAMLs matching the LDR benchmark export schema
(see community_benchmark_results/benchmark_template.yaml in the LDR repo).

Writes one CSV per dataset plus an aggregated all.csv. Any strategy
key under `results:` other than `dataset` / `total_questions` is
treated as a strategy sub-block, so new LDR strategies are picked up
automatically without changes to this script.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypedDict

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")


class BenchmarkEntry(TypedDict):
    canonical_id: str
    path_slug: str
    accepted_names: set[str]


def infer_contributor_from_git(path: Path) -> str:
    """Return the author name of the commit that first added `path` to git,
    or an empty string if git is unavailable or the file is not tracked.

    Uses the first commit that touched the file (git log --follow --diff-filter=A)
    rather than the latest one, so a later style-fix commit doesn't steal
    authorship from the original contributor.
    """
    try:
        # --follow handles renames; --diff-filter=A restricts to the commit
        # that ADDED the file; we take the last line (oldest matching commit).
        result = subprocess.run(
            [
                "git", "log",
                "--follow",
                "--diff-filter=A",
                "--format=%an",
                "--",
                str(path.resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=str(path.resolve().parent),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    authors = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return authors[-1] if authors else ""


RESERVED_RESULT_KEYS = {"dataset", "total_questions"}

# Whitelist mirroring LDR's DatasetRegistry. Must stay in sync with
# scripts/validate_yamls.py. Keeping it duplicated rather than importing
# so each script stays runnable standalone.
BENCHMARKS: list[BenchmarkEntry] = [
    {
        "canonical_id": "simpleqa",
        "path_slug": "simpleqa",
        "accepted_names": {"simpleqa"},
    },
    {
        "canonical_id": "browsecomp",
        "path_slug": "browsecomp",
        "accepted_names": {"browsecomp"},
    },
    {
        "canonical_id": "xbench_deepsearch",
        "path_slug": "xbench-deepsearch",
        "accepted_names": {"xbench_deepsearch", "xbench-deepsearch", "xbenchdeepsearch"},
    },
]


def lookup_benchmark_slug(name: str) -> str:
    """Return the canonical path_slug for a benchmark name, or a slugified
    fallback if the name isn't in the whitelist (so unknown benchmarks still
    produce a CSV rather than getting silently dropped)."""
    if not name:
        return "unknown"
    key = re.sub(r"[^a-z0-9]+", "", str(name).lower())
    for b in BENCHMARKS:
        candidates = set(b["accepted_names"]) | {b["path_slug"], b["canonical_id"]}
        if any(re.sub(r"[^a-z0-9]+", "", c.lower()) == key for c in candidates):
            return b["path_slug"]
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-") or "unknown"

COLUMNS = [
    "dataset",
    "model",
    "model_provider",
    "quantization",
    "strategy",
    "search_engine",
    "accuracy_pct",
    "accuracy_raw",
    "correct",
    "total",
    "iterations",
    "questions_per_iteration",
    "avg_time_per_question",
    "total_tokens_used",
    "temperature",
    "context_window",
    "max_tokens",
    "hardware_gpu",
    "hardware_ram",
    "hardware_cpu",
    "evaluator_model",
    "evaluator_provider",
    "ldr_version",
    "date_tested",
    "contributor",
    "contributor_source",
    "notes",
    "source_file",
]


def parse_accuracy(raw: object) -> tuple[float | None, int | None, int | None]:
    """Return (percent, correct, total) from fields like '91.2% (182/200)'."""
    if raw is None:
        return None, None, None
    if isinstance(raw, (int, float)):
        return float(raw), None, None  # type: ignore[unreachable]
    s = str(raw).strip()
    pct_match = re.search(r"([\d.]+)\s*%", s)
    frac_match = re.search(r"\(?\s*(\d+)\s*/\s*(\d+)\s*\)?", s)
    pct = float(pct_match.group(1)) if pct_match else None
    correct = int(frac_match.group(1)) if frac_match else None
    total = int(frac_match.group(2)) if frac_match else None
    if pct is None and correct is not None and total:
        pct = round(100.0 * correct / total, 2)
    return pct, correct, total


def iter_strategy_blocks(
    results_block: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (strategy_key, strategy_dict) for every strategy in results."""
    for key, value in results_block.items():
        if key in RESERVED_RESULT_KEYS:
            continue
        if isinstance(value, dict):
            yield key, value


def rows_from_yaml(path: Path) -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[skip] {path}: failed to parse YAML ({e})", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        print(f"[skip] {path}: top-level YAML is not a mapping", file=sys.stderr)
        return []

    results_block = data.get("results") or {}
    if not isinstance(results_block, dict):
        print(f"[skip] {path}: results is not a mapping", file=sys.stderr)
        return []

    hardware = data.get("hardware") or {}
    if not isinstance(hardware, dict):
        hardware = {}
    config = data.get("configuration") or {}
    evaluator = data.get("evaluator") or {}
    versions = data.get("versions") or {}
    test_details = data.get("test_details") or {}

    date_tested = data.get("date_tested") or test_details.get("date_tested", "")

    # Resolve contributor: prefer explicit YAML field, fall back to git
    # blame of the file (first commit to add it). The `contributor_source`
    # column records which path was used so reviewers can tell self-reported
    # contributors from git-inferred ones.
    explicit_contributor = (data.get("contributor") or "").strip()
    if explicit_contributor:
        contributor = explicit_contributor
        contributor_source = "yaml"
    else:
        git_contributor = infer_contributor_from_git(path)
        if git_contributor:
            contributor = git_contributor
            contributor_source = "git"
        else:
            contributor = ""
            contributor_source = ""

    rows: list[dict[str, Any]] = []
    for strategy_key, strategy_block in iter_strategy_blocks(results_block):
        pct, correct, total = parse_accuracy(strategy_block.get("accuracy"))
        rows.append({
            "dataset": str(results_block.get("dataset", "")).strip(),
            "model": data.get("model", ""),
            "model_provider": data.get("model_provider", ""),
            "quantization": data.get("quantization", "") or "",
            "strategy": strategy_key,
            "search_engine": data.get("search_engine", ""),
            "accuracy_pct": pct if pct is not None else "",
            "accuracy_raw": strategy_block.get("accuracy", ""),
            "correct": correct if correct is not None else "",
            "total": total if total is not None else results_block.get("total_questions", ""),
            "iterations": strategy_block.get("iterations", ""),
            "questions_per_iteration": strategy_block.get("questions_per_iteration", ""),
            "avg_time_per_question": strategy_block.get("avg_time_per_question", ""),
            "total_tokens_used": strategy_block.get("total_tokens_used", "") or "",
            "temperature": config.get("temperature", ""),
            "context_window": config.get("context_window", ""),
            "max_tokens": config.get("max_tokens", ""),
            "hardware_gpu": hardware.get("gpu", "") or "",
            "hardware_ram": hardware.get("ram", "") or "",
            "hardware_cpu": hardware.get("cpu", "") or "",
            "evaluator_model": evaluator.get("model", ""),
            "evaluator_provider": evaluator.get("provider", ""),
            "ldr_version": versions.get("ldr_version", ""),
            "date_tested": date_tested,
            "contributor": contributor,
            "contributor_source": contributor_source,
            "notes": (data.get("notes", "") or "").strip().splitlines()[0] if data.get("notes") else "",
            "source_file": str(path.as_posix()),
        })
    if not rows:
        print(f"[warn] {path}: no strategy blocks found under results:", file=sys.stderr)
    return rows


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unknown"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def sort_key(r: dict[str, Any]) -> tuple[float, str, str]:
        pct = r["accuracy_pct"]
        pct_val = -float(pct) if pct not in ("", None) else 1.0
        return (pct_val, str(r.get("date_tested", "")), str(r.get("model", "")))
    rows_sorted = sorted(rows, key=sort_key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows_sorted)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-dir", default="results", type=Path)
    ap.add_argument("--out-dir", default="leaderboards", type=Path)
    args = ap.parse_args()

    if not args.results_dir.exists():
        print(f"results dir not found: {args.results_dir}", file=sys.stderr)
        return 1

    yaml_files = sorted(args.results_dir.rglob("*.yaml")) + sorted(args.results_dir.rglob("*.yml"))
    if not yaml_files:
        print(f"no YAML files found under {args.results_dir}")
        # Still write empty leaderboards so the files exist.
        write_csv(args.out_dir / "all.csv", [])
        return 0

    all_rows: list[dict[str, Any]] = []
    per_dataset: dict[str, list[dict[str, Any]]] = {}
    for path in yaml_files:
        for row in rows_from_yaml(path):
            all_rows.append(row)
            per_dataset.setdefault(lookup_benchmark_slug(row["dataset"]), []).append(row)

    write_csv(args.out_dir / "all.csv", all_rows)
    for dataset_slug, rows in per_dataset.items():
        write_csv(args.out_dir / f"{dataset_slug}.csv", rows)

    print(f"wrote all.csv ({len(all_rows)} rows)")
    for dataset_slug, rows in sorted(per_dataset.items()):
        print(f"wrote {dataset_slug}.csv ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
