"""Test baseline checking and facts comparison without a Lua parser or DST."""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[2]
TOOL_DIR = SCRIPTS / "tools/verify"
sys.path.insert(0, str(TOOL_DIR))
SPEC = importlib.util.spec_from_file_location("dst_baselines", TOOL_DIR / "check_baselines.py")
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dst-baseline-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.code = b'local function emit(inst)\n    inst:PushEvent("changed")\nend\n'
        (self.root / "mini.lua").write_bytes(self.code)
        self.symbol = "mini.lua#module/function:emit"
        def anchor(aid, start, end):
            return {"id": aid, "path": "mini.lua", "start": baseline.position(self.code, start),
                    "end": baseline.position(self.code, end),
                    "sha256": sha256(self.code[start:end]).hexdigest()}
        declaration = anchor("declaration", 0, len(self.code) - 1)
        token = b'inst:PushEvent("changed")'
        start = self.code.index(token)
        event = anchor("event", start, start + len(token))
        self.anchors = {a["id"]: a for a in (declaration, event)}
        self.case = {"path": "mini.lua", "sha256": sha256(self.code).hexdigest(),
                     "expected_status": "complete", "semantic_reviews": [], "checks": [
                         {"id": "item-event", "collection": "records", "anchor_id": "event",
                          "match": {"kind": "event_emit", "subject_symbol_id": self.symbol,
                                    "guards": [], "data": {"receiver": "inst", "literal_name": "changed"}}}],
                     "forbidden": [{"collection": "symbols", "match": {"name": "Fake"}}]}
        self.catalog = {"baseline_version": 1, "contract_version": "1.0.0",
                        "mode": "manual-expectations", "parser_executed": False,
                        "comparison": "required-subset-plus-forbidden", "revision": {
                            "scheme": "fixture", "value": "test-v1"},
                        "anchors": list(self.anchors.values()), "cases": [self.case]}
        self.facts = {"format_version": "1.0.0", "kind": "facts", "snapshot_id": "test-v1",
                      "primary_file": "mini.lua", "coverage": {
                          "status": "complete", "selection": {"symbols": [self.symbol],
                              "record_kinds": ["event_emit"], "description": "Independent test fixture."},
                          "truncated": False, "diagnostics": []},
                      "anchors": [dict(a, source_id="dst") for a in self.anchors.values()],
                      "symbols": [{"id": self.symbol, "kind": "function", "name": "emit",
                          "scope": "module", "owner_id": None, "anchor_id": "declaration",
                          "parameters": [{"name": "inst", "kind": "named"}],
                          "calling": "plain", "base_expression": None}],
                      "records": [{"id": "item-event", "kind": "event_emit",
                          "subject_symbol_id": self.symbol, "anchor_id": "event", "guards": [],
                          "data": {"receiver": "inst", "name_expression": '"changed"',
                              "literal_name": "changed", "payload_expression": None,
                              "callback_expression": None}}]}
        self.schema = json.loads((SCRIPTS / "schemas/contract.schema.json").read_text(encoding="utf-8"))

    def compare(self):
        baseline.check_facts(self.case, self.facts, self.anchors, self.root, self.schema)

    def test_valid_source_and_facts(self):
        baseline.validate_catalog(self.catalog, self.root)
        self.compare()

    def test_source_change_invalidates_baseline(self):
        (self.root / "mini.lua").write_bytes(self.code + b"-- changed\n")
        with self.assertRaisesRegex(baseline.ContractError, "source changed"):
            baseline.validate_catalog(self.catalog, self.root)

    def test_wrong_coordinates_fail_even_with_correct_slice_hash(self):
        self.facts["anchors"][1]["start"]["column"] += 1
        with self.assertRaisesRegex(baseline.ContractError, "coordinates differ"):
            self.compare()

    def test_event_receiver_cannot_change_to_owner(self):
        self.facts["records"][0]["data"]["receiver"] = "owner"
        with self.assertRaisesRegex(baseline.ContractError, "missing expected fact"):
            self.compare()

    def test_condition_cannot_be_dropped(self):
        self.case["checks"][0]["match"]["guards"] = [{"expression": "enabled", "branch": "then"}]
        with self.assertRaisesRegex(baseline.ContractError, "missing expected fact"):
            self.compare()

    def test_unsupported_extra_fields_fail_schema(self):
        self.facts["records"][0]["inferred_type"] = "verified"
        with self.assertRaisesRegex(baseline.ContractError, "facts schema"):
            self.compare()

    def test_forbidden_pseudo_code_symbol_is_rejected(self):
        fake = deepcopy(self.facts["symbols"][0])
        fake["name"] = "Fake"
        fake["id"] = "mini.lua#module/function:Fake"
        self.facts["symbols"].append(fake)
        with self.assertRaisesRegex(baseline.ContractError, "forbidden fact"):
            self.compare()

    def test_failed_parse_requires_empty_facts_and_error(self):
        self.case.update(expected_status="failed", checks=[], empty_facts=True, require_error_diagnostic=True)
        self.facts["coverage"].update(status="failed", selection={"symbols": [], "record_kinds": [],
                                                               "description": "Failed parse."}, diagnostics=[])
        self.facts.update(symbols=[], records=[], anchors=[])
        with self.assertRaisesRegex(baseline.ContractError, "error diagnostic"):
            self.compare()
        self.facts["coverage"]["diagnostics"].append({"code": "PARSE_ERROR", "severity": "error",
                                                     "message": "Synthetic parse failure.", "anchor_id": None})
        self.compare()


if __name__ == "__main__":
    unittest.main()
