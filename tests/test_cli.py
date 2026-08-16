"""Tests for loading files and for the command line.

These use the bundled fixtures, so they also serve as a check that the example
in the README still produces the numbers the README claims.
"""
import io as _io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from snapshot_diff.cli import main, parse_field
from snapshot_diff.io import load

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ARGS = ["-f", "Business Name", "-f", "Date:date", "-f", "Amount:number"]


def run(argv):
    out, err = _io.StringIO(), _io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class FieldParsingTests(unittest.TestCase):
    def test_kind_defaults_to_text(self):
        self.assertEqual(parse_field("Business Name").kind, "text")

    def test_kind_is_parsed(self):
        self.assertEqual(parse_field("Date:date").kind, "date")
        self.assertEqual(parse_field("Amount:number").kind, "number")

    def test_unknown_kind_is_rejected(self):
        import argparse
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_field("Amount:money")


class LoadingTests(unittest.TestCase):
    def test_csv_round_trip(self):
        rows = load(FIXTURES / "before.csv")
        self.assertEqual(len(rows), 12)
        self.assertIn("Business Name", rows[0])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load(FIXTURES / "does-not-exist.csv")

    def test_unsupported_extension_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as handle:
            path = Path(handle.name)
        try:
            with self.assertRaises(ValueError):
                load(path)
        finally:
            path.unlink(missing_ok=True)


class CommandLineTests(unittest.TestCase):
    def test_fixtures_produce_the_documented_result(self):
        # If this breaks, the README is wrong.
        code, out, _ = run([str(FIXTURES / "before.csv"), str(FIXTURES / "after.csv"), *ARGS, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["unchanged"], 8)
        self.assertEqual(payload["corrected"], 3)
        self.assertEqual(payload["added"], 1)
        self.assertEqual(payload["removed"], 1)
        self.assertEqual(payload["corrections_by_field"],
                         {"Amount": 1, "Business Name": 1, "Date": 1})

    def test_text_output_is_readable(self):
        code, out, _ = run([str(FIXTURES / "before.csv"), str(FIXTURES / "after.csv"), *ARGS])
        self.assertEqual(code, 0)
        for expected in ("unchanged", "corrected", "added", "removed", "corrections:"):
            self.assertIn(expected, out)

    def test_a_single_field_is_refused_with_guidance(self):
        code, _, err = run([str(FIXTURES / "before.csv"), str(FIXTURES / "after.csv"), "-f", "Business Name"])
        self.assertEqual(code, 2)
        self.assertIn("at least two", err)

    def test_unknown_column_lists_what_is_available(self):
        code, _, err = run([str(FIXTURES / "before.csv"), str(FIXTURES / "after.csv"),
                            "-f", "Nope", "-f", "Date:date"])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)
        self.assertIn("available columns", err)

    def test_missing_file_exits_cleanly(self):
        code, _, err = run([str(FIXTURES / "nope.csv"), str(FIXTURES / "after.csv"), *ARGS])
        self.assertEqual(code, 1)
        self.assertIn("error", err.lower())

    def test_show_limit_is_respected(self):
        _, out, _ = run([str(FIXTURES / "before.csv"), str(FIXTURES / "after.csv"), *ARGS, "--show", "1"])
        self.assertIn("and 2 more", out)


if __name__ == "__main__":
    unittest.main()
