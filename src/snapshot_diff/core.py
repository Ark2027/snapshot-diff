"""Compare two versions of a dataset that share no primary key.

The problem this exists for: you have last quarter's export and this quarter's,
the rows have no stable id, and you need to know what actually changed. A naive
diff on the whole row reports a corrected typo as one deletion plus one
insertion, so routine cleanup is indistinguishable from records appearing and
vanishing. On a few thousand rows that noise buries the handful of differences
that matter.

The idea here is small. If two rows agree on every identifying field but one,
that is almost certainly the same record with a correction to that field, not
two unrelated events. So:

    agree on all fields            -> unchanged
    agree on all but one field     -> corrected, and we name the field
    anything left over             -> genuinely added or removed

Everything is counted rather than set-matched, because duplicate rows are real
and collapsing them silently loses information.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Sequence

Row = tuple[Any, ...]


def normalize_text(value: Any) -> str:
    """Casefold and strip punctuation so "Acme Co." and "acme co" agree."""
    return re.sub(r"[^a-z0-9]+", " ", str(value if value is not None else "").lower()).strip()


def normalize_number(value: Any, places: int = 2) -> float:
    """Round to a fixed precision so 1000 and 1000.001 agree."""
    if value is None or value == "":
        return 0.0
    try:
        return round(float(str(value).replace(",", "").replace("$", "").strip()), places)
    except (TypeError, ValueError):
        return 0.0


def normalize_date(value: Any) -> str:
    """Reduce to an ISO date so 2024-01-05, 1/5/2024 and a timestamp agree."""
    if value is None or value == "":
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(text[:19] if " " in text else text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text  # unparseable values still compare equal to themselves


NORMALIZERS = {"text": normalize_text, "number": normalize_number, "date": normalize_date}


@dataclass(frozen=True)
class KeyField:
    """One identifying column, and how to compare it."""

    name: str
    kind: str = "text"  # text | number | date

    def normalize(self, value: Any) -> Any:
        try:
            return NORMALIZERS[self.kind](value)
        except KeyError:
            raise ValueError(f"unknown field kind {self.kind!r}, expected one of {sorted(NORMALIZERS)}") from None


@dataclass
class Correction:
    """One record present in both versions with a single field changed."""

    field_name: str
    before: Row
    after: Row
    count: int = 1


@dataclass
class DiffResult:
    fields: Sequence[KeyField]
    unchanged: int = 0
    corrections: list[Correction] = field(default_factory=list)
    added: Counter = field(default_factory=Counter)
    removed: Counter = field(default_factory=Counter)

    @property
    def corrected(self) -> int:
        return sum(c.count for c in self.corrections)

    @property
    def added_count(self) -> int:
        return sum(self.added.values())

    @property
    def removed_count(self) -> int:
        return sum(self.removed.values())

    def corrections_by_field(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.corrections:
            out[c.field_name] = out.get(c.field_name, 0) + c.count
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "unchanged": self.unchanged,
            "corrected": self.corrected,
            "corrections_by_field": self.corrections_by_field(),
            "added": self.added_count,
            "removed": self.removed_count,
        }

    def as_rows(self, counter: Counter) -> list[dict[str, Any]]:
        """Expand a counter back into labelled dicts for reporting."""
        names = [f.name for f in self.fields]
        return [dict(zip(names, key)) for key, n in counter.items() for _ in range(n)]


def build_key(record: dict[str, Any], fields: Sequence[KeyField]) -> Row:
    return tuple(f.normalize(record.get(f.name)) for f in fields)


def _count_keys(records: Iterable[dict[str, Any]], fields: Sequence[KeyField]) -> Counter:
    return Counter(build_key(r, fields) for r in records)


def _differs_in_one_field(a: Row, b: Row) -> int | None:
    """Return the index of the single differing field, or None."""
    differing = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    return differing[0] if len(differing) == 1 else None


def _mask(key: Row, index: int) -> Row:
    """The key with one position removed, used to bucket near-matches."""
    return key[:index] + key[index + 1:]


def compare(
    before: Iterable[dict[str, Any]],
    after: Iterable[dict[str, Any]],
    fields: Sequence[KeyField],
) -> DiffResult:
    """Diff two versions of a dataset on the given identifying fields."""
    if len(fields) < 2:
        raise ValueError("at least two key fields are needed to tell a correction from a new record")

    old = _count_keys(before, fields)
    new = _count_keys(after, fields)
    result = DiffResult(fields=fields)

    exact = old & new
    result.unchanged = sum(exact.values())
    old -= exact
    new -= exact

    # Pair up what is left. A pair differing in exactly one field is the same
    # record with that field corrected.
    #
    # The obvious way to do this is to compare every leftover against every other
    # leftover, which is quadratic and gets unpleasant fast: on a run where
    # nothing matched at all, 1,600 rows a side took about 1.5 seconds and each
    # doubling roughly quadrupled it. That is a search where an index will do.
    #
    # So instead, for each candidate, record it under one masked key per field
    # position, with that position blanked out. Two keys differing in exactly
    # one position share a masked key at that position, and identical pairs were
    # already removed above, so a bucket hit is exactly the relationship wanted.
    # That makes the pass linear in rows times fields.
    buckets: dict[tuple[int, Row], list[Row]] = {}
    for new_key in sorted(new):
        for i in range(len(fields)):
            buckets.setdefault((i, _mask(new_key, i)), []).append(new_key)

    # Still greedy: where several leftovers could pair, it takes the first rather
    # than searching for a globally optimal assignment. Sorting keeps the result
    # stable across runs, which matters more here than optimality.
    for old_key in sorted(old):
        while old[old_key] > 0:
            pairing = None
            for i in range(len(fields)):
                for new_key in buckets.get((i, _mask(old_key, i)), ()):
                    if new[new_key] > 0:
                        pairing = (new_key, i)
                        break
                if pairing:
                    break
            if pairing is None:
                break
            new_key, index = pairing
            n = min(old[old_key], new[new_key])
            old[old_key] -= n
            new[new_key] -= n
            result.corrections.append(
                Correction(field_name=fields[index].name, before=old_key, after=new_key, count=n)
            )

    result.removed = +old  # drops zero and negative counts
    result.added = +new
    return result
