#!/usr/bin/env python3
"""
Validate community benchmark YAML submissions under results/.

Exit code:
    0 - all files OK
    1 - at least one file failed validation

Checks:
- File is valid YAML and a mapping at the top level
- Required top-level keys present: model, model_provider, search_engine, results
- results has `dataset` and at least one strategy sub-block
- Each strategy block has `accuracy` that parses
- Path matches `results/{dataset_slug}/{strategy_slug}/{search_engine}/{file}`
- Dataset + strategy + search_engine in the path match the YAML contents
- For BrowseComp and xbench datasets: no `examples:` key allowed
- No obviously sensitive strings (api key patterns, emails in notes)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")


# Whitelist of supported benchmarks. Mirrors LDR's DatasetRegistry
# (src/local_deep_research/benchmarks/datasets/__init__.py). To add a
# new benchmark here, add its canonical_id to match LDR's registry,
# list the display names contributors may write in `results.dataset:`,
# set the path_slug used in results/{slug}/..., and set restricted=True
# if per-question examples must not be shared publicly.
BENCHMARKS = [
    {
        "canonical_id": "simpleqa",
        "path_slug": "simpleqa",
        "accepted_names": {"simpleqa"},
        "restricted": False,
    },
    {
        "canonical_id": "browsecomp",
        "path_slug": "browsecomp",
        "accepted_names": {"browsecomp"},
        "restricted": True,
    },
    {
        "canonical_id": "xbench_deepsearch",
        "path_slug": "xbench-deepsearch",
        "accepted_names": {"xbench_deepsearch", "xbench-deepsearch", "xbenchdeepsearch"},
        "restricted": True,
    },
]

# Derived lookup tables.
_BENCHMARK_BY_NAME: dict[str, dict] = {}
for _b in BENCHMARKS:
    for _n in _b["accepted_names"]:
        _BENCHMARK_BY_NAME[_n] = _b
    _BENCHMARK_BY_NAME[_b["path_slug"]] = _b


def lookup_benchmark(name: str) -> dict | None:
    """Look up a benchmark whitelist entry by any accepted form of the name."""
    if not name:
        return None
    key = re.sub(r"[^a-z0-9]+", "", str(name).lower())
    # Try each entry's normalized accepted names + path_slug.
    for b in BENCHMARKS:
        candidates = set(b["accepted_names"]) | {b["path_slug"], b["canonical_id"]}
        if any(re.sub(r"[^a-z0-9]+", "", c.lower()) == key for c in candidates):
            return b
    return None


REQUIRED_TOP_LEVEL = ["model", "model_provider", "search_engine", "results"]
RESERVED_RESULT_KEYS = {"dataset", "total_questions"}

SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI-style API key"),
    (re.compile(r"hf_[A-Za-z0-9]{20,}"), "Hugging Face token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key ID"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub personal access token"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"), "Bearer token"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "Email address"),
]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def parse_accuracy(raw) -> bool:
    if raw is None:
        return False
    if isinstance(raw, (int, float)):
        return True
    return bool(re.search(r"[\d.]+", str(raw)))


def check_file(path: Path, results_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return [f"could not read file: {e}"]

    # Sensitive-string scan on raw text
    for pattern, label in SENSITIVE_PATTERNS:
        if pattern.search(text):
            errors.append(f"possible {label} found in file content")

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return errors + [f"invalid YAML: {e}"]
    if not isinstance(data, dict):
        return errors + ["top-level YAML must be a mapping"]

    for key in REQUIRED_TOP_LEVEL:
        if key not in data:
            errors.append(f"missing required top-level key: {key}")

    results_block = data.get("results") or {}
    if not isinstance(results_block, dict):
        errors.append("results: must be a mapping")
        return errors

    dataset = str(results_block.get("dataset", "")).strip()
    if not dataset:
        errors.append("results.dataset is missing or empty")
    benchmark_entry = lookup_benchmark(dataset) if dataset else None
    if dataset and benchmark_entry is None:
        allowed = ", ".join(sorted(b["canonical_id"] for b in BENCHMARKS))
        errors.append(
            f"results.dataset '{dataset}' is not in the supported benchmark "
            f"whitelist. Allowed: {allowed}. To add a new benchmark, update "
            f"BENCHMARKS in scripts/validate_yamls.py."
        )

    strategy_blocks = [
        k for k, v in results_block.items()
        if k not in RESERVED_RESULT_KEYS and isinstance(v, dict)
    ]
    if not strategy_blocks:
        errors.append("results has no strategy sub-block (expected at least one)")

    for strat in strategy_blocks:
        block = results_block[strat]
        if "accuracy" not in block:
            errors.append(f"results.{strat}.accuracy is missing")
        elif not parse_accuracy(block.get("accuracy")):
            errors.append(f"results.{strat}.accuracy could not be parsed: {block.get('accuracy')!r}")

    # Path convention: results/{dataset}/{strategy}/{search_engine}/{file}.yaml
    try:
        rel = path.resolve().relative_to(results_root.resolve())
    except ValueError:
        rel = None
        errors.append(
            f"file is not under results dir '{results_root}' — cannot verify "
            f"path convention results/{{dataset}}/{{strategy}}/{{search_engine}}/{{file}}.yaml"
        )
    if rel is not None:
        parts = rel.parts
        if len(parts) != 4:
            errors.append(
                f"path should be results/{{dataset}}/{{strategy}}/{{search_engine}}/{{file}}.yaml "
                f"(got depth {len(parts)})"
            )
        else:
            path_dataset, path_strategy, path_search, _ = parts
            expected_slug = benchmark_entry["path_slug"] if benchmark_entry else slugify(dataset)
            if dataset and expected_slug != path_dataset:
                errors.append(
                    f"path dataset '{path_dataset}' does not match results.dataset "
                    f"'{dataset}' (expected '{expected_slug}')"
                )
            if strategy_blocks:
                strategy_slugs = {slugify(s) for s in strategy_blocks}
                if slugify(path_strategy) not in strategy_slugs:
                    errors.append(
                        f"path strategy '{path_strategy}' does not match any strategy "
                        f"block in the file ({sorted(strategy_blocks)})"
                    )
            search_engine = str(data.get("search_engine", "")).strip()
            if search_engine and slugify(search_engine) != path_search:
                errors.append(
                    f"path search_engine '{path_search}' does not match "
                    f"search_engine '{search_engine}'"
                )

    # Restricted benchmarks must not contain examples
    if benchmark_entry and benchmark_entry["restricted"]:
        if "examples" in data:
            errors.append(
                f"dataset '{benchmark_entry['canonical_id']}' is restricted — "
                f"per-question examples are not allowed for this benchmark. "
                f"Remove the 'examples:' block before submitting."
            )

    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-dir", default="results", type=Path)
    ap.add_argument("paths", nargs="*", type=Path,
                    help="Specific YAML files to check (default: all under results/)")
    args = ap.parse_args()

    if args.paths:
        yaml_files = [p for p in args.paths if p.suffix.lower() in {".yaml", ".yml"}]
    else:
        if not args.results_dir.exists():
            print(f"results dir not found: {args.results_dir}", file=sys.stderr)
            return 1
        yaml_files = sorted(args.results_dir.rglob("*.yaml")) + sorted(args.results_dir.rglob("*.yml"))

    if not yaml_files:
        print("no YAML files to validate")
        return 0

    failed = 0
    for path in yaml_files:
        errs = check_file(path, args.results_dir)
        if errs:
            failed += 1
            print(f"\n❌ {path}")
            for e in errs:
                print(f"   - {e}")
        else:
            print(f"✓ {path}")

    print(f"\n{len(yaml_files) - failed}/{len(yaml_files)} files valid")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
