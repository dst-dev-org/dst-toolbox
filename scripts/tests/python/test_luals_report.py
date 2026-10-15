"""Independent result invariants: deliberate failures alone must not pass a probe."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "luals_probe", Path(__file__).resolve().parents[2] / "tools/verify/verify_luacats.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def diagnostic(line, code):
    return {"range": {"start": {"line": line, "character": 4}}, "code": code}


class LuaLSReportTests(unittest.TestCase):
    def setUp(self):
        self.negative = "file:///synthetic/equippable-negative.lua"
        self.data = {self.negative: [
            diagnostic(2, "assign-type-mismatch"), diagnostic(3, "assign-type-mismatch"),
            diagnostic(4, "param-type-mismatch"), diagnostic(5, "param-type-mismatch"),
            diagnostic(6, "undefined-field"), diagnostic(7, "need-check-nil")]}

    def test_exact_negative_errors_pass_regardless_of_order(self):
        self.data[self.negative].reverse()
        self.assertTrue(probe.assess(self.data, "equippable")["passed"])

    def test_missing_nil_detection_and_no_errors_fail(self):
        for data in ({}, {self.negative: self.data[self.negative][:-1]}):
            self.assertFalse(probe.assess(data, "equippable")["passed"])

    def test_extra_negative_error_fails(self):
        self.data[self.negative].append(diagnostic(9, "syntax-check"))
        self.assertFalse(probe.assess(self.data, "equippable")["passed"])

    def test_error_moved_to_wrong_line_fails(self):
        self.data[self.negative][-1] = diagnostic(8, "need-check-nil")
        self.assertFalse(probe.assess(self.data, "equippable")["passed"])

    def test_positive_or_declaration_error_fails(self):
        for filename in ("equippable-positive.lua", "equippable.lua"):
            data = deepcopy(self.data)
            data[f"file:///synthetic/{filename}"] = [diagnostic(0, "undefined-doc-name")]
            self.assertFalse(probe.assess(data, "equippable")["passed"])

    def test_unexpected_source_cannot_be_ignored(self):
        self.data["file:///synthetic/another.lua"] = [diagnostic(0, "syntax-check")]
        with self.assertRaisesRegex(ValueError, "unexpected diagnostic source"):
            probe.assess(self.data, "equippable")

    def test_finiteuses_existing_expectations_preserved(self):
        data = {"file:///synthetic/finiteuses-negative.lua": [
            diagnostic(2, "param-type-mismatch"), diagnostic(3, "param-type-mismatch"),
            diagnostic(4, "undefined-field")]}
        self.assertTrue(probe.assess(data, "finiteuses")["passed"])


if __name__ == "__main__":
    unittest.main()
