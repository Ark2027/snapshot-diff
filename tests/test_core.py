"""Tests for the diff itself.

The cases that matter are the ones where a naive diff gets it wrong: a
reformatted date should be invisible, a corrected typo should be one correction
rather than a delete plus an insert, and duplicate rows should survive.
"""
import unittest

from snapshot_diff.core import (
    KeyField,
    compare,
    normalize_date,
    normalize_number,
    normalize_text,
)

FIELDS = (KeyField("name", "text"), KeyField("date", "date"), KeyField("amount", "number"))


def row(name, date, amount):
    return {"name": name, "date": date, "amount": amount}


class NormalizationTests(unittest.TestCase):
    def test_text_ignores_case_and_punctuation(self):
        self.assertEqual(normalize_text("Acme Co."), normalize_text("acme co"))
        self.assertEqual(normalize_text("A & B, LLC"), normalize_text("A  &  B ,  LLC"))
        self.assertEqual(normalize_text("  Trailing Space  "), "trailing space")

    def test_text_handles_none(self):
        self.assertEqual(normalize_text(None), "")

    def test_number_ignores_currency_formatting(self):
        self.assertEqual(normalize_number("$15,000"), 15000.0)
        self.assertEqual(normalize_number(15000), 15000.0)
        self.assertEqual(normalize_number("15000.004"), 15000.0)

    def test_number_survives_junk(self):
        self.assertEqual(normalize_number("not a number"), 0.0)
        self.assertEqual(normalize_number(None), 0.0)

    def test_date_accepts_common_formats(self):
        for value in ("2024-01-22", "1/22/2024", "2024/01/22", "01-22-2024", "2024-01-22 13:45:00"):
            self.assertEqual(normalize_date(value), "2024-01-22", msg=value)

    def test_unparseable_date_compares_equal_to_itself(self):
        # Better to keep an odd value intact than to collapse everything to empty.
        self.assertEqual(normalize_date("sometime in March"), normalize_date("sometime in March"))


class UnchangedTests(unittest.TestCase):
    def test_identical_rows(self):
        rows = [row("Cedar Bakery", "2024-01-15", 25000)]
        result = compare(rows, list(rows), FIELDS)
        self.assertEqual(result.unchanged, 1)
        self.assertEqual((result.corrected, result.added_count, result.removed_count), (0, 0, 0))

    def test_reformatting_is_not_a_change(self):
        # The whole point: a date written differently is not an edit.
        before = [row("Harbor Print Shop", "2024-02-03", 15000)]
        after = [row("harbor print shop", "2/3/2024", "$15,000")]
        result = compare(before, after, FIELDS)
        self.assertEqual(result.unchanged, 1)
        self.assertEqual(result.corrected, 0)

    def test_duplicates_are_preserved_not_collapsed(self):
        before = [row("Lantern Bakery", "2024-03-05", 27000)] * 2
        result = compare(before, list(before), FIELDS)
        self.assertEqual(result.unchanged, 2)

    def test_a_duplicate_being_dropped_is_a_removal(self):
        before = [row("Lantern Bakery", "2024-03-05", 27000)] * 2
        after = [row("Lantern Bakery", "2024-03-05", 27000)]
        result = compare(before, after, FIELDS)
        self.assertEqual(result.unchanged, 1)
        self.assertEqual(result.removed_count, 1)


class CorrectionTests(unittest.TestCase):
    def test_typo_fixed_is_one_correction_not_two_events(self):
        before = [row("Verdent Landscaping", "2024-03-11", 21000)]
        after = [row("Verdant Landscaping", "2024-03-11", 21000)]
        result = compare(before, after, FIELDS)
        self.assertEqual(result.corrected, 1)
        self.assertEqual((result.added_count, result.removed_count), (0, 0))
        self.assertEqual(result.corrections[0].field_name, "name")

    def test_each_field_can_be_the_corrected_one(self):
        base = row("Acme Co", "2024-01-15", 25000)
        for field_name, changed in (
            ("name", row("Acme Company", "2024-01-15", 25000)),
            ("date", row("Acme Co", "2024-01-20", 25000)),
            ("amount", row("Acme Co", "2024-01-15", 26000)),
        ):
            result = compare([base], [changed], FIELDS)
            self.assertEqual(result.corrected, 1, msg=field_name)
            self.assertEqual(result.corrections[0].field_name, field_name)

    def test_two_fields_changing_is_not_a_correction(self):
        # Too much has changed to claim it is the same record.
        before = [row("Acme Co", "2024-01-15", 25000)]
        after = [row("Beta Industries", "2024-06-01", 25000)]
        result = compare(before, after, FIELDS)
        self.assertEqual(result.corrected, 0)
        self.assertEqual((result.added_count, result.removed_count), (1, 1))

    def test_corrections_are_counted_by_field(self):
        before = [row("A Co", "2024-01-01", 100), row("B Co", "2024-02-01", 200)]
        after = [row("A Corp", "2024-01-01", 100), row("B Co", "2024-02-05", 200)]
        result = compare(before, after, FIELDS)
        self.assertEqual(result.corrections_by_field(), {"name": 1, "date": 1})


class AddRemoveTests(unittest.TestCase):
    def test_new_record(self):
        result = compare([], [row("New Co", "2024-01-01", 100)], FIELDS)
        self.assertEqual(result.added_count, 1)

    def test_vanished_record(self):
        result = compare([row("Gone Co", "2024-01-01", 100)], [], FIELDS)
        self.assertEqual(result.removed_count, 1)

    def test_both_empty(self):
        result = compare([], [], FIELDS)
        self.assertEqual(result.summary(), {
            "unchanged": 0, "corrected": 0, "corrections_by_field": {}, "added": 0, "removed": 0
        })


class ContractTests(unittest.TestCase):
    def test_one_key_field_is_refused(self):
        # With a single field there is no way to distinguish a corrected value
        # from an unrelated record, so asking is a mistake worth surfacing.
        with self.assertRaises(ValueError):
            compare([], [], (KeyField("name"),))

    def test_unknown_field_kind_is_refused(self):
        with self.assertRaises(ValueError):
            compare([row("A", "2024-01-01", 1)], [], (KeyField("name", "wat"), KeyField("date", "date")))

    def test_missing_column_is_treated_as_empty_not_a_crash(self):
        result = compare([{"name": "A Co"}], [{"name": "A Co"}], FIELDS)
        self.assertEqual(result.unchanged, 1)

    def test_result_is_stable_across_runs(self):
        before = [row("A Co", "2024-01-01", 100), row("B Co", "2024-02-01", 200)]
        after = [row("A Corp", "2024-01-01", 100), row("B Corp", "2024-02-01", 200)]
        first = compare(before, after, FIELDS).summary()
        second = compare(before, after, FIELDS).summary()
        self.assertEqual(first, second)


class ReportingTests(unittest.TestCase):
    def test_rows_expand_back_to_labelled_dicts(self):
        result = compare([], [row("New Co", "2024-01-01", 100)], FIELDS)
        rows = result.as_rows(result.added)
        self.assertEqual(rows[0]["name"], "new co")
        self.assertEqual(rows[0]["date"], "2024-01-01")

    def test_summary_totals_account_for_every_record(self):
        before = [row("A", "2024-01-01", 1), row("B", "2024-01-02", 2), row("C", "2024-01-03", 3)]
        after = [row("A", "2024-01-01", 1), row("B", "2024-01-09", 2), row("D", "2024-01-04", 4)]
        s = compare(before, after, FIELDS).summary()
        self.assertEqual(s["unchanged"] + s["corrected"] + s["added"] + s["removed"], 4)

class ScaleTests(unittest.TestCase):
    """The pairing pass used to compare every leftover against every other one.

    That is quadratic, and on a run where nothing matched it took about 1.5
    seconds for 1,600 rows a side. These pin the behavior that replaced it.
    """

    FIELDS = (KeyField("name"), KeyField("date", "date"), KeyField("amount", "number"))

    def _rows(self, n, prefix="biz", start=0):
        return [{"name": f"{prefix} {i}", "date": "2024-01-05", "amount": 1000 + i}
                for i in range(start, start + n)]

    def test_worst_case_completes_quickly(self) -> None:
        # Zero overlap, so every row on both sides is a leftover to be paired.
        # Quadratic behavior would take seconds here.
        import time

        before = self._rows(2000, "alpha")
        after = self._rows(2000, "bravo", start=100_000)
        started = time.perf_counter()
        result = compare(before, after, self.FIELDS)
        elapsed = time.perf_counter() - started

        self.assertEqual(result.added_count, 2000)
        self.assertEqual(result.removed_count, 2000)
        self.assertLess(elapsed, 2.0, "pairing should not be quadratic in the number of rows")

    def test_large_input_still_separates_corrections(self) -> None:
        before = self._rows(1000)
        after = self._rows(1000)
        for i in range(0, 1000, 10):          # 100 date corrections
            after[i]["date"] = "2024-06-30"
        after.append({"name": "genuinely new", "date": "2024-07-01", "amount": 5})

        result = compare(before, after, self.FIELDS)
        self.assertEqual(result.unchanged, 900)
        self.assertEqual(result.corrected, 100)
        self.assertEqual(result.corrections_by_field(), {"date": 100})
        self.assertEqual(result.added_count, 1)
        self.assertEqual(result.removed_count, 0)


if __name__ == "__main__":
    unittest.main()
