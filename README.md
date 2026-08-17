# snapshot-diff

[![tests](https://github.com/Ark2027/snapshot-diff/actions/workflows/tests.yml/badge.svg)](https://github.com/Ark2027/snapshot-diff/actions/workflows/tests.yml)

Diffs two versions of a dataset that have no ID column, so a fixed typo stops looking like a row being deleted and re-added.

## Why

I was auditing two years of quarterly reporting, trying to answer what should have been a simple question: what actually changed between last quarter's export and this one? The rows had no stable id, so I diffed on name plus date plus amount.

The output was useless. Every fixed typo showed up as one deletion and one insertion. A date corrected from the 14th to the 19th looked like a record vanishing and an unrelated one appearing. Across a few thousand rows the handful of differences I cared about were buried under routine cleanup.

The fix turned out to be small: **if two rows agree on every identifying field but one, that's almost certainly the same record with a correction, not two unrelated events.**

```
agree on all fields         ->  unchanged
agree on all but one        ->  corrected, and we name the field
anything left over          ->  genuinely added or removed
```

That's the whole idea. The rest is plumbing.

## Try it

```bash
pip install -e .
snapshot-diff fixtures/before.csv fixtures/after.csv \
  -f "Business Name" -f "Date:date" -f "Amount:number"
```

```
  unchanged        8
  corrected        3   (Amount: 1, Business Name: 1, Date: 1)
  added            1
  removed          1
  --------------------------
  total           13

  corrections:
    Amount: 59000.0 -> 61500.0
    Date: '2024-02-14' -> '2024-02-19'
    Business Name: 'verdent landscaping' -> 'verdant landscaping'

  added:
    Business Name='southwest roofing co', Date='2024-03-31', Amount=33000.0

  removed:
    Business Name='copper ridge fitness', Date='2024-03-25', Amount=22000.0
```

A plain row diff on those same fixtures reports **four deletions and four insertions**. Three of those four pairs were someone fixing a typo.

## Field kinds

Each key field is compared as `text`, `number` or `date`, because "changed" means different things for each:

| kind | treats as equal |
|---|---|
| `text` | `Acme Co.` / `acme co` / `ACME  CO` |
| `number` | `15000` / `$15,000` / `15000.004` |
| `date` | `2024-01-22` / `1/22/2024` / `2024-01-22 09:15:00` |

This matters more than it sounds. Two of the twelve fixture rows differ only in formatting, and without normalization they'd show up as six spurious events.

Anything a date parser can't read is kept as-is rather than collapsed to empty, so odd values still compare equal to themselves instead of all matching each other.

## As a library

```python
from snapshot_diff import KeyField, compare, load

fields = [KeyField("Business Name", "text"), KeyField("Date", "date"), KeyField("Amount", "number")]
result = compare(load("before.csv"), load("after.csv"), fields)

print(result.summary())
print(result.corrections_by_field())     # {"Date": 1, "Amount": 1, ...}
for c in result.corrections:
    print(c.field_name, c.before, "->", c.after)
```

## Notes

**Duplicates survive.** Rows are counted, not set-matched. If a record legitimately appears twice, it stays twice, and a duplicate being dropped is reported as a removal rather than silently absorbed.

**Two key fields minimum.** With one field there's no way to distinguish a corrected value from an unrelated record, so asking for it raises instead of returning something meaningless.

**No dependencies** for CSV. `openpyxl` only if you want Excel:

```bash
pip install -e ".[excel]"
snapshot-diff q1.xlsx q2.xlsx --sheet Originations -f "Name" -f "Date:date" -f "Amount:number"
```

## What I'd change

The pairing is greedy. When several leftover rows could pair with each other it takes the first match rather than searching for a globally optimal assignment. For the sizes I built this for the difference is immaterial, and a greedy pass is much easier to reason about than a matching algorithm, but on a dataset with many near-identical rows it could pair the wrong two. Sorting keeps the result stable across runs, which I cared about more.

Finding those pairs used to mean comparing every leftover against every other leftover. That is quadratic, and I only noticed how badly when I timed it: with no overlap at all, 1,600 rows a side took about 1.5 seconds and every doubling roughly quadrupled it.

It is an index lookup, not a search. Two keys that differ in exactly one position are identical once you remove that position, so each candidate goes into one bucket per field with that field blanked out. Same answers, and the same 1,600-row case now takes 34ms. 5,000 a side runs in about 126ms.

It also only recognises a change in *one* field as a correction. Two fields changing is treated as a different record, which is the safe call but will miss a record where someone fixed a typo and a date in the same pass.

## Tests

```bash
python tests/test_core.py
python tests/test_cli.py
```

35 tests, standard library only. The CLI tests assert the exact numbers this README shows, so if the output above ever stops being true the suite fails.

## License

MIT
