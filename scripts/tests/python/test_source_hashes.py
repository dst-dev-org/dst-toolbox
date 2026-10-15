"""Baseline manifest guarantees: scoped record, bound cache, archive handling and CLI."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/verify/validate_source_hashes.py"
SPEC = importlib.util.spec_from_file_location("dst_source_hashes", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

CONTENT = b"local x = 1\n\nend\nreturn x\n"
MANIFEST = "wiki/source-baseline.json"
CACHE = "output/source-baseline-cache.json"


class SourceHashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dst-source-hashes-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.knowledge = self.root / "knowledge"
        self.scripts = self.knowledge / "raw/current/scripts"
        self.wiki = self.knowledge / "wiki"
        self.page = self.wiki / "reference/components/example.md"
        self.other = self.wiki / "reference/components/second.md"
        self.page.parent.mkdir(parents=True)
        (self.wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        self.source = self.scripts / "components/test.lua"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(CONTENT)
        (self.knowledge / "raw/current/BUILD.txt").write_bytes(b"25643519\n")
        self.hashes = checker.file_hashes(self.source)

    def write_page(self, path=None, body="# Example\n", sources='["components/test.lua"]',
                   hashes=None, status="active"):
        frontmatter = '---\ntitle: "example"\ndst_build: "steam-buildid:25643519"\n'
        if sources is not None:
            frontmatter += f"sources: {sources}\n"
        if hashes:
            frontmatter += f"source_hashes:\n{hashes}"
        frontmatter += f"status: {status}\n---\n\n" + body
        (path or self.page).write_text(frontmatter, encoding="utf-8")

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-I", str(SCRIPT), *args],
                              cwd=self.root, capture_output=True, text=True, encoding="utf-8")

    def manifest(self):
        return json.loads((self.knowledge / MANIFEST).read_text(encoding="utf-8"))

    def digest_tree(self):
        skip = {"source-baseline.json", "source-baseline-cache.json"}
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file() and p.name not in skip}

    def test_record_dry_run_plans_without_writing_anything(self):
        self.write_page()
        before = self.digest_tree()
        result = self.cli("record", "--knowledge-root", str(self.knowledge))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["write"])
        self.assertEqual(report["counts"]["recorded"], 1)
        self.assertEqual(self.digest_tree(), before)

    def test_record_write_builds_manifest_and_is_idempotent(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        entry = self.manifest()["pages"]["reference/components/example.md"]
        self.assertEqual(entry["sources"], ["components/test.lua"])
        self.assertEqual(entry["files"]["components/test.lua"],
                         {"raw": f"sha256:{self.hashes[0]}", "normalized": f"sha256:{self.hashes[1]}"})
        self.assertEqual(entry["combined"],
                         checker.combined_hash({"components/test.lua": self.hashes}))
        again = json.loads(self.cli("record", "--knowledge-root", str(self.knowledge), "--write").stdout)
        self.assertEqual(again["counts"]["already_recorded"], 1)

    def test_scoped_record_preserves_other_baselines(self):
        self.write_page()
        self.other.write_text('---\ntitle: "second"\nsources: ["components/test.lua"]\n---\nx\n',
                              encoding="utf-8")
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        before = self.manifest()["pages"]["reference/components/second.md"]
        self.source.write_bytes(CONTENT + b"return 2\n")
        result = self.cli("record", "--knowledge-root", str(self.knowledge), "--write",
                          "reference/components/example.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["scoped"])
        self.assertEqual(report["counts"]["refreshed"], 1)
        self.assertEqual(self.manifest()["pages"]["reference/components/second.md"], before)
        full = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge),
                                   "--fresh-hours", "0").stdout)
        changed = {item["page"] for item in full["changed"]}
        self.assertEqual(changed, {"reference/components/second.md"})
        self.assertFalse(full["passed"])

    def test_full_rebuild_keeps_baselines_of_pages_skipped_for_missing_sources(self):
        self.write_page()
        self.other.write_text('---\ntitle: "second"\nsources: ["components/gone.lua"]\n---\nx\n',
                              encoding="utf-8")
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        gone = self.scripts / "components/gone.lua"
        gone.write_bytes(b"return 1\n")
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        baseline = self.manifest()["pages"]["reference/components/second.md"]
        gone.unlink()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.assertEqual(self.manifest()["pages"]["reference/components/second.md"], baseline)
        report = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge),
                                     "--fresh-hours", "0").stdout)
        self.assertEqual(report["counts"]["deleted"], 1)
        self.assertEqual(report["counts"]["unrecorded_pages"], 0)

    def test_broken_manifest_fails_check_and_record_repairs_it(self):
        self.write_page()
        (self.knowledge / MANIFEST).write_text("{not json", encoding="utf-8")
        result = self.cli("check", "--knowledge-root", str(self.knowledge))
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertTrue(report["manifest_state"].startswith("unreadable"))
        self.assertEqual(report["invalid"][0]["page"], "(manifest)")
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge)).returncode, 0)

    def test_cache_binds_to_snapshot_root_and_fingerprint(self):
        old = self.root / "oldsnap/scripts"
        (old / "components").mkdir(parents=True)
        (old / "components/test.lua").write_bytes(CONTENT)
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge)).returncode, 0)
        self.assertTrue(self.manifest().get("last_check") is None)
        self.assertTrue((self.knowledge / CACHE).is_file())
        other_root = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge),
                                         "--source-root", str(old)).stdout)
        self.assertFalse(other_root["cached"])
        self.source.write_bytes(CONTENT)
        touched = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge)).stdout)
        self.assertFalse(touched["cached"])
        self.assertEqual(touched["counts"]["unchanged"], 1)
        recached = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge)).stdout)
        self.assertTrue(recached["cached"])

    def test_check_is_read_only_for_tracked_files_and_cache_lives_in_output(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        before = self.digest_tree()
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge)).returncode, 0)
        self.assertEqual(self.digest_tree(), before)
        self.assertNotIn("last_check", self.manifest())
        self.assertTrue((self.knowledge / CACHE).is_file())
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.root / "absent")).returncode, 2)

    def test_cache_invalidates_after_page_membership_or_sources_change(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.cli("check", "--knowledge-root", str(self.knowledge))
        self.write_page(self.other)
        added = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge)).stdout)
        self.assertFalse(added["cached"])
        self.assertEqual(added["counts"]["unrecorded_pages"], 1)
        self.other.unlink()
        self.write_page(sources='["components/other.lua"]')
        changed = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge)).stdout)
        self.assertFalse(changed["cached"])
        self.assertFalse(changed["passed"])
        self.assertEqual(changed["counts"]["sources_changed"], 1)
        self.assertEqual(changed["sources_changed"],
                         [{"page": "reference/components/example.md"}])
        self.assertEqual(changed["counts"]["affected_pages"], 1)
        self.page.unlink()
        removed = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge)).stdout)
        self.assertFalse(removed["cached"])
        self.assertEqual(removed["counts"]["stale_entries"], 1)

    def test_cache_invalidates_after_manifest_edit_or_corruption(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.cli("check", "--knowledge-root", str(self.knowledge))
        manifest = self.manifest()
        hashes = manifest["pages"]["reference/components/example.md"]["files"]["components/test.lua"]
        hashes.update(raw="sha256:" + "0" * 64, normalized="sha256:" + "0" * 64)
        path = self.knowledge / MANIFEST
        path.write_text(json.dumps(manifest), encoding="utf-8")
        edited = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge)).stdout)
        self.assertFalse(edited["cached"])
        self.assertFalse(edited["passed"])
        self.assertEqual(edited["counts"]["changed"], 1)
        path.write_text("{broken", encoding="utf-8")
        broken = self.cli("check", "--knowledge-root", str(self.knowledge))
        self.assertEqual(broken.returncode, 1, broken.stderr)
        report = json.loads(broken.stdout)
        self.assertFalse(report["cached"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["counts"]["invalid_pages"], 1)

    def test_scoped_record_refuses_to_replace_a_damaged_manifest(self):
        self.write_page()
        path = self.knowledge / MANIFEST
        damaged = b'{"format_version":1,"pages": {"recoverable": '
        path.write_bytes(damaged)
        result = self.cli("record", "--knowledge-root", str(self.knowledge), "--write",
                          "reference/components/example.md")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["passed"])
        self.assertEqual(path.read_bytes(), damaged)

    def test_malformed_json_structures_report_errors_without_tracebacks(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        baseline = self.manifest()
        page = "reference/components/example.md"
        for where, value in (("root", []), ("root", None), ("root", 7),
                             ("entry", []), ("sources", {}), ("files", []),
                             ("hashes", []), ("hashes", {"raw": [], "normalized": 5}),
                             ("combined", {})):
            with self.subTest(where=where, value=value):
                manifest = json.loads(json.dumps(baseline))
                if where == "root":
                    manifest = value
                elif where == "entry":
                    manifest["pages"][page] = value
                elif where == "hashes":
                    manifest["pages"][page]["files"]["components/test.lua"] = value
                else:
                    manifest["pages"][page][where] = value
                (self.knowledge / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
                result = self.cli("check", "--knowledge-root", str(self.knowledge))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(json.loads(result.stdout)["passed"])
                self.assertNotIn("Traceback", result.stderr)

    def test_invalid_cache_structures_fall_back_to_a_real_check(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        cache = self.knowledge / CACHE
        cache.parent.mkdir(parents=True, exist_ok=True)
        for value in ([], None, {"time": [], "passed": True}):
            with self.subTest(value=value):
                cache.write_text(json.dumps(value), encoding="utf-8")
                result = self.cli("check", "--knowledge-root", str(self.knowledge))
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertFalse(report["cached"])
                self.assertEqual(report["counts"]["comparisons"], 1)

    def test_failed_record_preserves_the_existing_manifest(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        path = self.knowledge / MANIFEST
        before = path.read_bytes()
        self.page.write_text("---\nunterminated\n", encoding="utf-8")
        result = self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_scoped_check_skips_the_cache(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        report = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge),
                                     "reference/components/example.md").stdout)
        self.assertTrue(report["scoped"])
        self.assertEqual(report["counts"]["comparisons"], 1)
        self.assertFalse((self.knowledge / CACHE).is_file())

    def test_archived_pages_are_excluded_from_drift_and_manifest(self):
        self.write_page(status="archived")
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.assertEqual(self.manifest()["pages"], {})
        self.source.unlink()
        result = self.cli("check", "--knowledge-root", str(self.knowledge), "--fresh-hours", "0")
        self.assertEqual(result.returncode, 0, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["archived_pages"], 1)
        self.assertEqual(report["counts"]["deleted"], 0)
        self.assertTrue(report["passed"])

    def test_archiving_an_existing_page_removes_only_its_baseline(self):
        self.write_page()
        self.write_page(self.other)
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        other_before = self.manifest()["pages"]["reference/components/second.md"]
        self.cli("check", "--knowledge-root", str(self.knowledge))
        self.write_page(status="archived")
        result = self.cli("check", "--knowledge-root", str(self.knowledge))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["cached"])
        self.assertEqual(report["counts"]["archived_pages"], 1)
        self.assertEqual(report["counts"]["stale_entries"], 0)
        result = self.cli("record", "--knowledge-root", str(self.knowledge), "--write",
                          "reference/components/example.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"]["removed_archived"], 1)
        self.assertNotIn("reference/components/example.md", self.manifest()["pages"])
        self.assertEqual(self.manifest()["pages"]["reference/components/second.md"], other_before)
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge)).returncode, 0)

    def test_unrecorded_stale_and_sources_changed_fail_expectedly(self):
        self.write_page()
        self.other.write_text('---\ntitle: "second"\nsources: ["components/test.lua"]\n---\nx\n',
                              encoding="utf-8")
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        extra = self.wiki / "reference/components/third.md"
        extra.write_text('---\ntitle: "third"\nsources: ["components/test.lua"]\n---\nx\n',
                         encoding="utf-8")
        self.page.unlink()
        (self.scripts / "components/other.lua").write_bytes(b"return 2\n")
        self.other.write_text('---\ntitle: "second"\n'
                              'sources: ["components/test.lua", "components/other.lua"]\n---\nx\n',
                              encoding="utf-8")
        result = self.cli("check", "--knowledge-root", str(self.knowledge), "--fresh-hours", "0")
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["stale_entries"], 1)
        self.assertEqual(report["stale_entries"][0]["page"], "reference/components/example.md")
        self.assertEqual(report["counts"]["unrecorded_pages"], 1)
        self.assertEqual(report["counts"]["sources_changed"], 1)
        self.assertEqual(report["sources_changed"][0]["page"], "reference/components/second.md")
        self.assertEqual(report["counts"]["affected_pages"], 1)
        self.assertEqual(report["affected_pages"],
                         [{"page": "reference/components/second.md", "sources_changed": 1}])

    def test_snapshot_case_change_is_caught_or_reported_missing(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.source.rename(self.source.with_name("Test.lua"))
        report = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge),
                                     "--fresh-hours", "0").stdout)
        self.assertFalse(report["passed"])
        if os.path.normcase("A") == os.path.normcase("a"):
            self.assertEqual(report["counts"]["case_mismatch"], 1)
            self.assertEqual(report["case_mismatch"],
                             [{"page": "reference/components/example.md",
                               "source": "components/test.lua"}])
            self.assertEqual(report["counts"]["affected_pages"], 1)
            self.assertEqual(report["affected_pages"],
                             [{"page": "reference/components/example.md", "case_mismatch": 1}])
        else:
            self.assertEqual(report["counts"]["deleted"], 1)

    def test_record_refuses_wrong_case_citations(self):
        if os.path.normcase("A") != os.path.normcase("a"):
            self.skipTest("requires a case-insensitive filesystem")
        self.write_page(sources='["components/Test.lua"]')
        result = self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["pages_skipped_missing_files"], 1)
        self.assertEqual(report["skipped_missing_files"][0]["missing"], ["components/Test.lua"])
        self.assertEqual(self.manifest()["pages"], {})

    def test_cache_rejected_when_rule_version_missing(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge)).returncode, 0)
        cache = json.loads((self.knowledge / CACHE).read_text(encoding="utf-8"))
        self.assertEqual(cache.get("rule_version"), checker.RULE_VERSION)
        self.assertEqual(json.loads(self.cli("check", "--knowledge-root", str(self.knowledge)).stdout)["cached"], True)
        cache.pop("rule_version")
        (self.knowledge / CACHE).write_text(json.dumps(cache), encoding="utf-8")
        report = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge),
                                     "--fresh-hours", "24").stdout)
        self.assertFalse(report["cached"])
        self.assertTrue(report["counts"]["comparisons"] >= 1)
        rewritten = json.loads((self.knowledge / CACHE).read_text(encoding="utf-8"))
        self.assertEqual(rewritten.get("rule_version"), checker.RULE_VERSION)

    def test_source_root_must_exist(self):
        self.write_page()
        result = self.cli("check", "--knowledge-root", str(self.knowledge),
                          "--source-root", str(self.root / "no-such-scripts"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("source root", result.stderr)

    def test_snapshot_version_follows_selected_root(self):
        old = self.root / "oldsnap"
        (old / "scripts/components").mkdir(parents=True)
        (old / "scripts/components/test.lua").write_bytes(CONTENT)
        (old / "BUILD.txt").write_bytes(b"12345\n")
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        report = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge),
                                     "--source-root", str(old / "scripts")).stdout)
        self.assertEqual(report["snapshot_version"]["value"], "12345")
        self.assertEqual(report["snapshot_version"]["installed_current"]["value"], "25643519")

    def test_record_refuses_while_lock_held(self):
        self.write_page()
        lock = self.knowledge / "output" / ".source-baseline.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("0", encoding="utf-8")
        result = self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("lock", result.stderr)
        self.assertFalse((self.knowledge / MANIFEST).exists())
        lock.unlink()
        self.assertEqual(self.cli("record", "--knowledge-root", str(self.knowledge), "--write").returncode, 0)

    def test_scoped_record_merges_with_manifest_updated_after_read(self):
        self.write_page()
        self.write_page(self.other)
        self.assertEqual(self.cli("record", "--knowledge-root", str(self.knowledge), "--write").returncode, 0)
        # simulate a stale read taken before the other task committed its update:
        # the manifest snapshot held by this record no longer contains page B
        stale = self.manifest()
        stale["pages"].pop("reference/components/second.md")
        self.source.write_bytes(CONTENT + b"return 2\n")
        real_load = checker.load_json
        state = {"stale_done": False}

        def shim(path, fallback):
            data, st = real_load(path, fallback)
            if path.name == "source-baseline.json" and not state["stale_done"]:
                state["stale_done"] = True
                return stale, "ok"
            return data, st

        checker.load_json = shim
        try:
            report = checker.scan("record", Path(self.knowledge), None, None,
                                  selected=["reference/components/example.md"], write=True)
        finally:
            checker.load_json = real_load
        self.assertEqual(report["counts"]["refreshed"], 1)
        pages = self.manifest()["pages"]
        self.assertIn("reference/components/example.md", pages)
        self.assertIn("reference/components/second.md", pages)

    def test_scoped_record_refuses_manifest_corrupted_during_lock(self):
        self.write_page()
        self.write_page(self.other)
        self.assertEqual(self.cli("record", "--knowledge-root", str(self.knowledge), "--write").returncode, 0)
        before = (self.knowledge / MANIFEST).read_bytes()
        stale = self.manifest()
        real_load = checker.load_json
        state = {"calls": 0}

        def shim(path, fallback):
            data, st = real_load(path, fallback)
            if path.name == "source-baseline.json":
                state["calls"] += 1
                if state["calls"] == 2:  # lock-time re-read hits corruption
                    return None, "unreadable: simulated corruption"
            return data, st

        checker.load_json = shim
        try:
            with self.assertRaises(ValueError) as ctx:
                checker.scan("record", Path(self.knowledge), None, None,
                             selected=["reference/components/example.md"], write=True)
        finally:
            checker.load_json = real_load
        self.assertIn("changed while recording", str(ctx.exception))
        self.assertEqual((self.knowledge / MANIFEST).read_bytes(), before)

    def test_full_rebuild_repairs_structurally_broken_manifest(self):
        self.write_page()
        self.write_page(self.other)
        (self.knowledge / MANIFEST).write_text('{"format_version": 1, "pages": []}', encoding="utf-8")
        self.assertEqual(self.cli("record", "--knowledge-root", str(self.knowledge), "--write").returncode, 0)
        pages = self.manifest()["pages"]
        self.assertEqual(sorted(pages), ["reference/components/example.md", "reference/components/second.md"])
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge)).returncode, 0)

    def test_line_ending_change_passes_and_real_change_fails(self):
        self.write_page()
        self.cli("record", "--knowledge-root", str(self.knowledge), "--write")
        self.source.write_bytes(CONTENT.replace(b"\n", b"\r\n"))
        report = json.loads(self.cli("check", "--knowledge-root", str(self.knowledge)).stdout)
        self.assertEqual(report["counts"]["line_ending_only"], 1)
        self.assertTrue(report["passed"])
        self.source.write_bytes(CONTENT + b"return 2\n")
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge)).returncode, 1)

    def test_legacy_frontmatter_blocks_are_stripped_by_record(self):
        legacy = ('  components/test.lua: {raw: "sha256:' + "0" * 64 +
                  '", normalized: "sha256:' + "0" * 64 + '"}\n')
        self.write_page(hashes=legacy)
        dry = self.cli("record", "--knowledge-root", str(self.knowledge),
                       "reference/components/example.md")
        self.assertEqual(json.loads(dry.stdout)["counts"]["legacy_frontmatter"], 1)
        result = self.cli("record", "--knowledge-root", str(self.knowledge), "--write",
                          "reference/components/example.md")
        text = self.page.read_text(encoding="utf-8")
        self.assertNotIn("source_hashes:", text)
        self.assertIn("status: active", text)
        self.assertEqual(json.loads(result.stdout)["counts"]["stripped"], 1)

    def test_config_option_resolves_the_knowledge_root(self):
        self.write_page()
        config = self.root / "alt-config.json"
        config.write_text(json.dumps({"knowledge_root": str(self.knowledge)}), encoding="utf-8")
        result = self.cli("record", "--config", str(config))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"]["recorded"], 1)

    def test_selection_and_roots_are_validated(self):
        self.write_page()
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge),
                                  "reference/components/absent.md").returncode, 2)
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge),
                                  "reference/components/example.lua").returncode, 2)
        outside = self.root / "outside.md"
        outside.write_text("x\n", encoding="utf-8")
        self.assertEqual(self.cli("check", "--knowledge-root", str(self.knowledge),
                                  str(outside)).returncode, 2)

    def test_parse_flow_list_and_normalize(self):
        self.assertEqual(checker.parse_flow_list('["a", \'b\', c]', "x"), ["a", "b", "c"])
        self.assertEqual(checker.parse_flow_list("[]", "x"), [])
        self.assertEqual(checker.parse_flow_list('["path/with, comma.lua"]', "x"),
                         ["path/with, comma.lua"])
        self.assertEqual(checker.normalize(b"\xef\xbb\xbfa\r\nb\rc\n\n"), b"a\nb\nc")


if __name__ == "__main__":
    unittest.main()
