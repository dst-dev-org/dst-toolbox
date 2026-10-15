"""Projection failures and signatures using synthetic, source-independent input."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "dst_export", SCRIPTS / "tools/maintenance/export_luacats.py")
export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export)
CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "contract_tests", Path(__file__).with_name("test_contract.py"))
contract_tests = importlib.util.module_from_spec(CONTRACT_SPEC)
CONTRACT_SPEC.loader.exec_module(contract_tests)


class LuaCATSTests(unittest.TestCase):
    def setUp(self):
        fixture = contract_tests.ContractTests()
        fixture.setUp()
        self.addCleanup(fixture.temp.cleanup)
        self.bundle = fixture.bundle
        self.roots = fixture.roots
        # Independent synthetic review; no external candidates are needed.
        self.bundle["candidates"].update(source_id=None, anchors=[], claims=[])
        self.bundle["projection_checks"].update(excluded_candidate_ids=[], luacats_review_ids=[])
        self.bundle["resolved"] = export.contract.resolve(self.bundle)

    def render(self):
        self.bundle["resolved"] = export.contract.resolve(self.bundle)
        return export.render(self.bundle, "component_widget")

    def method(self, returns):
        symbol = {"id": "test.lua#Widget/method:Use", "kind": "method", "name": "Use",
                  "scope": "Widget", "owner_id": "test.lua#module/class:Widget",
                  "anchor_id": "field", "parameters": [{"name": "num", "kind": "named"}],
                  "calling": "colon", "base_expression": None}
        self.bundle["facts"]["symbols"].append(symbol)
        proto = self.bundle["reviews"]["entries"][0]
        for facet, value in [
            ("param:num:type", {"kind": "type", "expression": "number"}),
            ("param:num:optional", {"kind": "optional", "accepts_omitted": True, "accepts_nil": True}),
            ("returns", returns),
        ]:
            review = deepcopy(proto)
            review.update(id=facet, target={"symbol_id": symbol["id"], "facet": facet}, value=value)
            self.bundle["reviews"]["entries"].append(review)

    def load(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for key in ("facts", "manifest", "reviews"):
                (root / (key + ".json")).write_bytes(export.contract.canonical(self.bundle[key]))
            return export.load_bundle(root / "facts.json", root / "manifest.json",
                                      root / "reviews.json", self.roots["dst"])

    def test_no_editor_base_or_optional_hooks(self):
        text, report = self.render()
        self.assertIn("---@field count number", text)
        self.assertNotIn("component_base", text)
        self.assertNotIn("OnUpdate", text)
        self.assertEqual(report["missing_facets"], [])
        self.load()

    def test_optional_parameter_and_no_return_slot(self):
        self.method({"kind": "returns", "slots": [], "variadic": None, "can_fall_through": True})
        text, _ = self.render()
        self.assertIn("---@param num? number", text)
        self.assertNotIn("---@return nil", text)

    def test_save_fall_through_is_nilable(self):
        self.method({"kind": "returns", "slots": [{"type": "{uses: number}"}],
                     "variadic": None, "can_fall_through": True})
        text, _ = self.render()
        self.assertIn("---@return ({uses: number})|nil", text)

    def test_unverified_type_does_not_emit_any(self):
        self.bundle["reviews"]["entries"][0]["state"] = "pending"
        text, report = self.render()
        self.assertNotIn("---@field count", text)
        self.assertEqual(report["unresolved"][0]["status"], "unknown")
        self.assertTrue(report["missing_facets"])

    def test_incomplete_method_is_not_a_type_projection(self):
        self.method({"kind": "returns", "slots": [], "variadic": None, "can_fall_through": True})
        self.bundle["reviews"]["entries"][1]["state"] = "pending"
        text, report = self.render()
        self.assertNotIn("function component:Use", text)
        self.assertEqual(report["selected_review_ids"], ["review-number"])

    def test_conflict_is_rejected(self):
        second = deepcopy(self.bundle["reviews"]["entries"][0])
        second.update(id="another", value={"kind": "type", "expression": "string"})
        self.bundle["reviews"]["entries"].append(second)
        with self.assertRaisesRegex(ValueError, "conflicting reviews"):
            self.load()

    def test_stale_review_is_rejected(self):
        self.bundle["reviews"]["entries"][0]["state"] = "stale"
        with self.assertRaisesRegex(ValueError, "stale review"):
            self.load()

    def test_changed_source_is_rejected(self):
        (self.roots["dst"] / "test.lua").write_bytes(b"-- changed\n")
        with self.assertRaisesRegex(ValueError, "source file hash mismatch"):
            self.load()

    def test_real_inheritance_is_not_silently_discarded(self):
        self.bundle["facts"]["symbols"][0]["base_expression"] = "RealBase"
        with self.assertRaisesRegex(ValueError, "real source inheritance"):
            self.render()


if __name__ == "__main__":
    unittest.main()
