"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import KeyField, compare
from .io import load

KINDS = ("text", "number", "date")


def parse_field(spec: str) -> KeyField:
    """Parse "name:kind" into a KeyField. Kind defaults to text."""
    name, _, kind = spec.partition(":")
    name = name.strip()
    kind = (kind or "text").strip().lower()
    if not name:
        raise argparse.ArgumentTypeError(f"empty field name in {spec!r}")
    if kind not in KINDS:
        raise argparse.ArgumentTypeError(f"unknown kind {kind!r} in {spec!r}; expected one of {', '.join(KINDS)}")
    return KeyField(name=name, kind=kind)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snapshot-diff",
        description="Compare two versions of a dataset that share no primary key.",
        epilog='example: snapshot-diff before.csv after.csv -f "Business Name" -f "Date:date" -f "Amount:number"',
    )
    parser.add_argument("before", type=Path, help="the earlier snapshot")
    parser.add_argument("after", type=Path, help="the later snapshot")
    parser.add_argument(
        "-f", "--field", dest="fields", action="append", required=True, type=parse_field,
        help='identifying column as "name" or "name:kind" where kind is text, number or date. Repeatable; at least two needed.',
    )
    parser.add_argument("--sheet", help="worksheet name or substring, for Excel input")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a readable summary")
    parser.add_argument("--show", type=int, default=5, help="how many example rows to print per section (default 5)")
    return parser


def render_text(result, show: int) -> str:
    s = result.summary()
    total = s["unchanged"] + s["corrected"] + s["added"] + s["removed"]
    lines = [
        "",
        f"  unchanged   {s['unchanged']:>6}",
        f"  corrected   {s['corrected']:>6}" + ("" if not s["corrections_by_field"] else
            "   (" + ", ".join(f"{k}: {v}" for k, v in sorted(s["corrections_by_field"].items())) + ")"),
        f"  added       {s['added']:>6}",
        f"  removed     {s['removed']:>6}",
        f"  {'-' * 26}",
        f"  total       {total:>6}",
    ]

    if result.corrections and show:
        lines += ["", "  corrections:"]
        names = [f.name for f in result.fields]
        for c in result.corrections[:show]:
            i = names.index(c.field_name)
            lines.append(f"    {c.field_name}: {c.before[i]!r} -> {c.after[i]!r}"
                         + (f"  (x{c.count})" if c.count > 1 else ""))
        if len(result.corrections) > show:
            lines.append(f"    ... and {len(result.corrections) - show} more")

    for label, counter in (("added", result.added), ("removed", result.removed)):
        rows = result.as_rows(counter)
        if rows and show:
            lines += ["", f"  {label}:"]
            for row in rows[:show]:
                lines.append("    " + ", ".join(f"{k}={v!r}" for k, v in row.items()))
            if len(rows) > show:
                lines.append(f"    ... and {len(rows) - show} more")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if len(args.fields) < 2:
        print("error: at least two --field arguments are needed to tell a correction from a new record",
              file=sys.stderr)
        return 2

    try:
        before = load(args.before, args.sheet)
        after = load(args.after, args.sheet)
    except (FileNotFoundError, ValueError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    missing = [
        f.name for f in args.fields
        if (before and f.name not in before[0]) or (after and f.name not in after[0])
    ]
    if missing:
        available = sorted(set((before[0] if before else {}))) or sorted(set((after[0] if after else {})))
        print(f"error: field(s) not found: {', '.join(missing)}", file=sys.stderr)
        print(f"       available columns: {', '.join(available)}", file=sys.stderr)
        return 1

    result = compare(before, after, args.fields)

    if args.json:
        print(json.dumps({
            **result.summary(),
            "corrections": [
                {"field": c.field_name,
                 "before": dict(zip([f.name for f in result.fields], c.before)),
                 "after": dict(zip([f.name for f in result.fields], c.after)),
                 "count": c.count}
                for c in result.corrections
            ],
            "added_rows": result.as_rows(result.added),
            "removed_rows": result.as_rows(result.removed),
        }, indent=2, default=str))
    else:
        print(render_text(result, args.show))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
