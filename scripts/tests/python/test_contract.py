"""Contract invariants using independent synthetic Lua, without game source."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import unittest

TOOL_DIR = Path(__file__).resolve().parents[2] / "tools/verify"
SPEC = importlib.util.spec_from_file_location("dst_contract", TOOL_DIR / "validate_examples.py")
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.game, self.external = root / "game", root / "external"
        self.game.mkdir()
        self.external.mkdir()
        self.code = b"local Widget = {}\nWidget.count = 1\nreturn Widget\n"
        self.annotation = b"---@field count string\n"
        (self.game / "test.lua").write_bytes(self.code)
        (self.external / "test.lua").write_bytes(self.annotation)
        self.roots = {"dst": self.game, "external": self.external}
        def anchor(aid, source, data, start, end):
            return {"id": aid, "source_id": source, "path": "test.lua",
                    "start": contract.position(data, start), "end": contract.position(data, end),
                    "sha256": contract.digest(data[start:end])}
        definition = anchor("class", "dst", self.code, 0, 18)
        field = anchor("field", "dst", self.code, 18, 35)
        ext = anchor("external-field", "external", self.annotation, 0, len(self.annotation))
        self.symbol_id = "test.lua#Widget/field:count"
        self.target = {"symbol_id": self.symbol_id, "facet": "field:type"}
        coverage = {"status": "complete", "selection": {"symbols": [self.symbol_id],
                    "record_kinds": [], "description": "Synthetic field declaration only."},
                    "truncated": False, "diagnostics": []}
        version = {"scheme": "fixture", "value": "fixture-v1"}
        source = lambda sid, kind, data: {"id": sid, "kind": kind, "root_hint": None,
                    "revision": version, "files": [{"path": "test.lua",
                    "sha256": contract.digest(data), "encoding": "utf-8"}]}
        review = {"id": "review-number", "target": self.target,
                  "value": {"kind": "type", "expression": "number"}, "state": "verified",
                  "verdict": "accept", "candidate_ids": [], "reviewed_snapshot_id": "fixture-v1",
                  "reviewer": "synthetic-test", "reviewed_at": "2026-10-10",
                  "scope": "Synthetic fixture only.", "evidence": [{"anchor_id": "field",
                  "expected_sha256": field["sha256"], "role": "implementation"}],
                  "runtime": [], "note": "Test data, not a DST technical claim."}
        self.bundle = {"format_version": "1.0.0", "kind": "example-bundle", "purpose": "Synthetic contract test.",
            "manifest": {"format_version": "1.0.0", "kind": "manifest", "snapshot": {"id": "fixture-v1", "version": version},
                "producer": {"name": "test", "version": "1", "mode": "synthetic", "dialect": "lua51", "parser": None},
                "sources": [source("dst", "game-source", self.code), source("external", "annotation-library", self.annotation)]},
            "facts": {"format_version": "1.0.0", "kind": "facts", "snapshot_id": "fixture-v1", "primary_file": "test.lua",
                "coverage": coverage, "anchors": [definition, field], "symbols": [
                    {"id": "test.lua#module/class:Widget", "kind": "class", "name": "Widget", "scope": "module",
                     "owner_id": None, "anchor_id": "class", "parameters": [], "calling": "none", "base_expression": None},
                    {"id": self.symbol_id, "kind": "field", "name": "count", "scope": "Widget",
                     "owner_id": "test.lua#module/class:Widget", "anchor_id": "field", "parameters": [], "calling": "none", "base_expression": None}], "records": []},
            "candidates": {"format_version": "1.0.0", "kind": "candidates", "source_id": "external", "target_file": "test.lua",
                "anchors": [ext], "claims": [{"id": "candidate-string", "target": self.target,
                "value": {"kind": "type", "expression": "string"}, "anchor_id": "external-field"}]},
            "reviews": {"format_version": "1.0.0", "kind": "reviews", "target_file": "test.lua", "anchors": [], "entries": [review]},
            "projection_checks": {"index_symbol_ids": [self.symbol_id], "luacats_review_ids": ["review-number"],
                "wiki_review_ids": [], "excluded_candidate_ids": ["candidate-string"]}}
        self.refresh()

    def refresh(self):
        self.bundle["resolved"] = contract.resolve(self.bundle)

    def validate(self):
        return contract.validate_bundle(self.bundle, self.roots)

    def clear_type_projection(self):
        self.bundle["projection_checks"]["luacats_review_ids"] = []

    def test_reference_and_no_external_library(self):
        self.validate()
        self.bundle["candidates"].update(source_id=None, anchors=[], claims=[])
        self.bundle["projection_checks"]["excluded_candidate_ids"] = []
        self.refresh()
        self.validate()

    def test_external_candidate_alone_is_unknown(self):
        self.bundle["reviews"]["entries"] = []
        self.clear_type_projection()
        self.refresh()
        self.validate()
        row = self.bundle["resolved"]["records"][0]
        self.assertEqual(row["status"], "unknown")
        self.assertIsNone(row["value"])

    def test_stale_cannot_generate_type(self):
        review = self.bundle["reviews"]["entries"][0]
        review["evidence"][0]["expected_sha256"] = "0" * 64
        self.refresh()
        with self.assertRaisesRegex(contract.ContractError, "invalid verified"):
            self.validate()
        review["state"] = "stale"
        self.clear_type_projection()
        self.refresh()
        self.validate()
        self.assertEqual(self.bundle["resolved"]["records"][0]["status"], "review-needed")
        self.bundle["projection_checks"]["luacats_review_ids"] = ["review-number"]
        with self.assertRaisesRegex(contract.ContractError, "unverified projection"):
            self.validate()

    def test_two_verified_values_are_conflict(self):
        second = deepcopy(self.bundle["reviews"]["entries"][0])
        second["id"] = "review-string"
        second["value"]["expression"] = "string"
        self.bundle["reviews"]["entries"].append(second)
        self.clear_type_projection()
        self.refresh()
        self.validate()
        self.assertEqual(self.bundle["resolved"]["records"][0]["status"], "conflict")
        self.assertIsNone(self.bundle["resolved"]["records"][0]["value"])
        self.assertEqual(len(self.bundle["resolved"]["conflicts"]), 1)

    def test_reject_and_independent_correction(self):
        rejection = deepcopy(self.bundle["reviews"]["entries"][0])
        rejection.update(id="reject-string", verdict="reject", candidate_ids=["candidate-string"],
                         value={"kind": "type", "expression": "string"})
        self.bundle["reviews"]["entries"].append(rejection)
        self.refresh()
        self.validate()
        row = self.bundle["resolved"]["records"][0]
        self.assertEqual(row["status"], "verified")
        self.assertEqual(row["rejected_candidate_ids"], ["candidate-string"])
        accepted = deepcopy(rejection)
        accepted.update(id="accept-string", verdict="accept")
        self.bundle["reviews"]["entries"] = [rejection, accepted]
        self.clear_type_projection()
        self.bundle["projection_checks"]["excluded_candidate_ids"] = []
        self.refresh()
        self.validate()
        self.assertEqual(self.bundle["resolved"]["records"][0]["status"], "conflict")

    def test_external_evidence_cannot_verify(self):
        review = self.bundle["reviews"]["entries"][0]
        review["evidence"] = [{"anchor_id": "external-field", "expected_sha256": contract.digest(self.annotation),
                               "role": "external-annotation"}]
        self.refresh()
        with self.assertRaisesRegex(contract.ContractError, "invalid verified"):
            self.validate()

    def test_source_and_anchor_integrity(self):
        self.validate()
        (self.game / "test.lua").write_bytes(self.code + b"-- changed\n")
        with self.assertRaisesRegex(contract.ContractError, "file hash mismatch"):
            self.validate()
        (self.game / "test.lua").write_bytes(self.code)
        for key, value, error in [("sha256", "0" * 64, "anchor hash mismatch"),
                                  ("start", {"byte": 18, "line": 2, "column": 2}, "coordinates mismatch")]:
            original = deepcopy(self.bundle["facts"]["anchors"][1])
            self.bundle["facts"]["anchors"][1][key] = value
            with self.assertRaisesRegex(contract.ContractError, error):
                self.validate()
            self.bundle["facts"]["anchors"][1] = original

    def test_cache_hash_includes_manifest(self):
        self.bundle["manifest"]["producer"]["version"] = "2"
        with self.assertRaisesRegex(contract.ContractError, "cache differs"):
            self.validate()
        self.refresh()
        self.validate()

    def test_unknown_type_and_bad_references(self):
        review = self.bundle["reviews"]["entries"][0]
        review["value"]["expression"] = None
        self.refresh()
        with self.assertRaisesRegex(contract.ContractError, "invalid verified"):
            self.validate()
        review["state"] = "pending"
        self.clear_type_projection()
        self.refresh()
        self.validate()
        self.bundle["facts"]["symbols"][1]["owner_id"] = "missing"
        self.refresh()
        with self.assertRaisesRegex(contract.ContractError, "missing symbol owner"):
            self.validate()

    def test_parse_failure_is_not_complete(self):
        self.bundle["facts"]["coverage"]["diagnostics"] = [
            {"code": "PARSE_ERROR", "severity": "error", "message": "Synthetic error", "anchor_id": None}]
        self.refresh()
        with self.assertRaisesRegex(contract.ContractError, "complete coverage"):
            self.validate()
        self.bundle["facts"]["coverage"]["status"] = "partial"
        self.refresh()
        self.validate()

    def test_format_version_and_unsafe_path_fail_closed(self):
        self.bundle["format_version"] = "2.0.0"
        with self.assertRaisesRegex(contract.ContractError, "schema"):
            self.validate()
        self.bundle["format_version"] = "1.0.0"
        self.bundle["facts"]["anchors"][0]["path"] = "../test.lua"
        with self.assertRaises(contract.ContractError):
            self.validate()

    def test_vararg_type_and_integer_serialization(self):
        symbol = self.bundle["facts"]["symbols"][1]
        symbol.update(kind="function", name="collect", scope="module", owner_id=None,
                      calling="plain", parameters=[{"name": "...", "kind": "vararg"}],
                      id="test.lua#module/function:collect")
        target = {"symbol_id": symbol["id"], "facet": "param:...:type"}
        self.bundle["facts"]["coverage"]["selection"]["symbols"] = [symbol["id"]]
        self.bundle["candidates"]["claims"][0]["target"] = target
        self.bundle["reviews"]["entries"][0]["target"] = target
        self.bundle["projection_checks"]["index_symbol_ids"] = [symbol["id"]]
        self.refresh()
        self.validate()
        self.bundle["facts"]["anchors"][1]["start"]["byte"] = 18.0
        self.refresh()
        with self.assertRaisesRegex(contract.ContractError, "must be integers"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
