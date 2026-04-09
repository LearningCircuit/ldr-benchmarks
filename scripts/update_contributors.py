#!/usr/bin/env python3
"""
Regenerate the contributors list from leaderboards/all.csv.

Writes CONTRIBUTORS.md as the canonical list and replaces the
marker-delimited block in README.md and hf_README.md so the same
list is visible on both GitHub and the Hugging Face dataset card.

Marker format (in any markdown file we update):

    <!-- CONTRIBUTORS:START -->
    ... auto-generated content ...
    <!-- CONTRIBUTORS:END -->

Usage:
    python scripts/update_contributors.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

START_MARKER = "<!-- CONTRIBUTORS:START -->"
END_MARKER = "<!-- CONTRIBUTORS:END -->"


def load_contributors(csv_path: Path) -> list[tuple[str, int]]:
    """Return [(name, submission_count), ...] sorted by count desc, then name."""
    if not csv_path.exists():
        return []
    counts: Counter[str] = Counter()
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("contributor") or "").strip()
            if name:
                counts[name] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def render_block(contributors: list[tuple[str, int]]) -> str:
    """Render the markdown block that lives between the START/END markers."""
    if not contributors:
        return (
            "_No contributors yet — be the first by opening a PR with your "
            "benchmark YAML._\n"
        )
    lines = [
        "Thanks to everyone who has contributed benchmark runs:",
        "",
    ]
    for name, count in contributors:
        suffix = "submission" if count == 1 else "submissions"
        lines.append(f"- **{name}** — {count} {suffix}")
    lines.append("")
    return "\n".join(lines)


def render_contributors_md(contributors: list[tuple[str, int]]) -> str:
    """Render the standalone CONTRIBUTORS.md file."""
    return (
        "# Contributors\n"
        "\n"
        "Auto-generated from `leaderboards/all.csv` by "
        "`scripts/update_contributors.py`. Do not edit by hand — submit a "
        "benchmark YAML and your name will appear here on the next publish.\n"
        "\n"
        f"{START_MARKER}\n"
        f"{render_block(contributors)}"
        f"{END_MARKER}\n"
    )


def update_marker_block(path: Path, block: str) -> bool:
    """Replace the START/END marker block in `path`. Return True if changed.

    If the file exists but has no markers, the file is left untouched and a
    warning is printed (we don't want to silently rewrite arbitrary files).
    """
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if START_MARKER not in text or END_MARKER not in text:
        print(
            f"[warn] {path}: marker block not found, skipping. Add\n"
            f"  {START_MARKER}\n  {END_MARKER}\n"
            "to the file where you want the contributors list rendered.",
            file=sys.stderr,
        )
        return False
    before, _, rest = text.partition(START_MARKER)
    _, _, after = rest.partition(END_MARKER)
    new_text = f"{before}{START_MARKER}\n{block}{END_MARKER}{after}"
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=Path("leaderboards/all.csv"), type=Path)
    ap.add_argument(
        "--contributors-file",
        default=Path("CONTRIBUTORS.md"),
        type=Path,
    )
    ap.add_argument(
        "--update",
        nargs="*",
        type=Path,
        default=[Path("README.md"), Path("hf_README.md")],
        help="Markdown files whose marker block should be updated in place",
    )
    args = ap.parse_args()

    contributors = load_contributors(args.csv)
    print(f"found {len(contributors)} unique contributor(s) in {args.csv}")

    args.contributors_file.write_text(
        render_contributors_md(contributors),
        encoding="utf-8",
    )
    print(f"wrote {args.contributors_file}")

    block = render_block(contributors)
    for path in args.update:
        if update_marker_block(path, block):
            print(f"updated {path}")
        else:
            print(f"unchanged {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
