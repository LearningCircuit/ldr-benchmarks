#!/usr/bin/env python3
"""
Push leaderboards/ CSVs and the HF-specific README to the
local-deep-research/ldr-benchmarks Hugging Face dataset.

Only the aggregated CSVs and the HF README are uploaded. The raw YAML
result files are NOT mirrored — the GitHub repo remains the single
source of truth for raw data. This keeps the HF dataset small and
avoids re-hosting per-question examples.

Environment:
    HF_TOKEN   (required) write token for the HF dataset repo
    HF_REPO    (optional) defaults to "local-deep-research/ldr-benchmarks"

Usage:
    python scripts/sync_to_hf.py
    python scripts/sync_to_hf.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from huggingface_hub import HfApi
except ImportError:
    sys.exit("Missing dependency: pip install huggingface_hub")


DEFAULT_REPO = "local-deep-research/ldr-benchmarks"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--leaderboards-dir", default="leaderboards", type=Path)
    ap.add_argument("--hf-readme", default="hf_README.md", type=Path,
                    help="Path to the HF-specific README to upload as README.md")
    ap.add_argument("--repo", default=os.environ.get("HF_REPO", DEFAULT_REPO))
    ap.add_argument("--dry-run", action="store_true",
                    help="List files that would be uploaded without uploading")
    ap.add_argument("--commit-message", default="Sync leaderboards from GitHub")
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token and not args.dry_run:
        print("ERROR: HF_TOKEN env var not set", file=sys.stderr)
        return 1

    if not args.leaderboards_dir.exists():
        print(f"ERROR: leaderboards dir not found: {args.leaderboards_dir}",
              file=sys.stderr)
        return 1

    csv_files = sorted(args.leaderboards_dir.glob("*.csv"))
    if not csv_files:
        print(f"ERROR: no CSV files in {args.leaderboards_dir}", file=sys.stderr)
        return 1

    uploads: list[tuple[Path, str]] = []
    for csv in csv_files:
        uploads.append((csv, f"leaderboards/{csv.name}"))

    if args.hf_readme.exists():
        uploads.append((args.hf_readme, "README.md"))
    else:
        print(f"WARN: HF README not found at {args.hf_readme} — skipping",
              file=sys.stderr)

    print(f"Target repo: {args.repo} (dataset)")
    for src, dest in uploads:
        print(f"  {src}  ->  {dest}")

    if args.dry_run:
        print("\n(dry run — no upload performed)")
        return 0

    api = HfApi(token=token)
    for src, dest in uploads:
        api.upload_file(
            path_or_fileobj=str(src),
            path_in_repo=dest,
            repo_id=args.repo,
            repo_type="dataset",
            commit_message=args.commit_message,
        )
        print(f"  ✓ uploaded {dest}")

    print("\nSync complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
