"""Coverage checks: graded output, aliases, back-link states, budgets and CLI."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2]
SCRIPT = SCRIPTS / "tools/verify/verify_page_coverage.py"
SPEC = importlib.util.spec_from_file_location("dst_page_coverage", SCRIPT)
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)

FENCE = chr(96) * 3
FORMAT = """# Synthetic coverage policy

| 文件类别 | 最多行数 | 最大字节 |
|---|---:|---:|
| 根导航 | 10 | 1 KiB |
| 索引 | 20 | 2 KiB |
| 知识页 | 30 | 3 KiB |
| cookbook | 40 | 4 KiB |
"""


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dst-page-coverage-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wiki = self.root / "wiki"
        self.wiki.mkdir()
        self.format = self.root / "format.md"
        self.format.write_text(FORMAT, encoding="utf-8")

    def write(self, rel, text):
        path = self.wiki / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def prefab(self, name, aliases=(), status="active", back=None, body="正文。"):
        lines = ["---", f"title: {name}", "type: prefab", f"status: {status}"]
        if aliases:
            lines.append("aliases: [" + ", ".join(
                json.dumps(alias, ensure_ascii=False) for alias in aliases) + "]")
        lines += ["---", "", f"# {name}", "", body, ""]
        if back:
            lines += [back, ""]
        self.write(f"reference/prefabs/{name}.md", "\n".join(lines) + "\n")

    def index(self, names, rel="reference/prefabs/index.md"):
        rows = "".join(f"| [[reference/prefabs/{name}|{name}]] | x | 别名 / active |\n"
                       for name in names)
        self.write(rel, "---\ntitle: 索引\ntype: index\n---\n# 索引\n\n"
                        "| 页面入口 | 需求摘要 | 别名 / 状态 |\n|---|---|---|\n" + rows)

    def table_index(self, rel, rows, width=1):
        body = "".join(f"| 条目 {number} {'x' * width} | 说明 |\n" for number in range(rows))
        self.write(rel, "---\ntitle: 索引\ntype: index\n---\n# 索引\n\n"
                        "| 列 | 列 |\n|---|---|\n" + body)

    def reg(self, payload, name="registrations.json"):
        path = self.root / name
        path.write_text(payload if isinstance(payload, str)
                        else json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def args(self, registrations=None, **overrides):
        values = {"wiki_root": self.wiki, "format": self.format,
                  "registrations": registrations, "rows_warn": 60, "bytes_warn": 12288,
                  "strict": False, "fail_on": "error", "severity": None, "code": None,
                  "page": None, "changed": None, "missing_scope": "prefab",
                  "scope": "prefab", "json": False, "limit": 500}
        values.update(overrides)
        return argparse.Namespace(**values)

    def build(self, registrations=None, **overrides):
        return coverage.build(self.args(registrations, **overrides))

    def line_of(self, rel, needle):
        text = (self.wiki / rel).read_text(encoding="utf-8")
        return next(number for number, line in enumerate(text.splitlines(), 1)
                    if needle in line)

    def cli(self, *args):
        # File handles instead of pipes: sandboxed grandchildren may be denied CreatePipe.
        out_path, err_path = self.root / "cli-out.txt", self.root / "cli-err.txt"
        with out_path.open("w", encoding="utf-8") as out, err_path.open("w", encoding="utf-8") as err:
            result = subprocess.run([sys.executable, "-B", "-I", str(SCRIPT), *map(str, args)],
                                    cwd=self.root, stdout=out, stderr=err)
        return subprocess.CompletedProcess(result.args, result.returncode,
                                           out_path.read_text(encoding="utf-8"),
                                           err_path.read_text(encoding="utf-8"))

    def test_alias_conflict_needs_a_confirmed_registration(self):
        self.prefab("a", ["shared_reg"])
        self.prefab("b", ["shared_reg"])
        self.prefab("c", ["candidate_reg"])
        self.prefab("d", ["candidate_reg"])
        self.prefab("old", ["shared_reg"], status="archived")
        self.index(["a", "b", "c", "d", "old"])
        report = self.build(self.reg({"entries": [
            {"name": "shared_reg", "status": "confirmed"},
            {"name": "candidate_reg", "status": "candidate"}]}))
        conflicts = [item for item in report["findings"] if item["code"].startswith("alias-")]
        self.assertEqual([item["code"] for item in conflicts], ["alias-conflict"])
        conflict = conflicts[0]
        self.assertEqual(conflict["severity"], "error")
        self.assertEqual(conflict["name"], "shared_reg")
        self.assertEqual(conflict["pages"], ["reference/prefabs/a.md", "reference/prefabs/b.md"])
        self.assertIn("a.md", conflict["message"])
        self.assertIn("b.md", conflict["message"])
        self.assertNotIn("old.md", conflict["message"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"]["alias_ownership"], "confirmed")
        self.assertEqual(report["checks"]["coverage_gaps"], "checked")

    def test_shared_aliases_are_only_suspected_without_a_list(self):
        aliases = ["lower_name", "Ice Box", "SKIN_NAME", "DoDelta"]
        self.prefab("one", aliases)
        self.prefab("two", aliases)
        self.index(["one", "two"])
        report = self.build(scope="all", severity=["warning", "info"])
        by_name = {item["name"]: item for item in report["findings"]
                   if item["code"].startswith("alias-")}
        self.assertEqual(set(by_name), set(aliases))
        self.assertEqual(by_name["lower_name"]["code"], "alias-suspected-conflict")
        self.assertEqual(by_name["lower_name"]["severity"], "warning")
        for name in ("Ice Box", "SKIN_NAME", "DoDelta"):
            self.assertEqual(by_name[name]["code"], "alias-shared-phrase")
            self.assertEqual(by_name[name]["severity"], "info")
        self.assertEqual(report["checks"]["alias_ownership"], "suspected-only")
        self.assertEqual(report["checks"]["coverage_gaps"], "skipped")

    def test_backlink_segments_ignore_prose_and_fenced_blocks(self):
        text = ("# t\n\n- 接口返回 [[wrong]]\n\n> 返回 [[leaf|L]]、[[hub]]。\n\n"
                + FENCE + "md\n返回 [[fenced]]\n" + FENCE + "\n")
        segments = coverage.backlink_segments(text)
        self.assertEqual([number for number, _ in segments], [5])
        self.assertEqual(coverage.parse_targets(segments), [("leaf", 5), ("hub", 5)])

    def test_backlink_states_are_distinguished(self):
        self.prefab("good", back="返回 [[reference/prefabs/index|索引]]。")
        self.prefab("bad", back="返回 [[reference/index|参考]]。")
        self.prefab("none")
        self.prefab("plain", back="返回 索引。")
        self.prefab("markdown", back="返回 [索引](reference/prefabs/index.md)。")
        self.prefab("lonely")
        self.index(["good", "bad", "none", "plain", "markdown"])
        report = self.build()
        items = {(item["page"], item["code"]): item for item in report["findings"]}
        self.assertFalse(any(page.endswith("good.md") for page, _ in items))
        bad = items[("reference/prefabs/bad.md", "backlink-mismatch")]
        self.assertEqual(bad["severity"], "warning")
        self.assertEqual(bad["name"], "reference/prefabs/index")
        self.assertEqual(bad["line"], self.line_of("reference/prefabs/bad.md", "返回"))
        self.assertIn("backlink-missing", report["counts"]["by_code"])
        self.assertIn("backlink-unrecognized", report["counts"]["by_code"])
        self.assertEqual(report["unresolved"]["backlink_missing"], 1)
        self.assertEqual(report["unresolved"]["backlink_unrecognized"], 2)
        self.assertEqual(report["unresolved"]["backlink_ambiguous"], 1)
        self.assertEqual(report["unresolved"]["backlinks"], 3)
        groups = {(group["code"], group["key"]): group for group in report["groups"]}
        self.assertEqual(groups[("backlink-mismatch", "reference/prefabs/index")]["count"], 1)
        self.assertEqual(groups[("backlink-missing", "reference/prefabs")]["count"], 1)

    def test_missing_backlink_defaults_to_prefab_pages(self):
        self.prefab("prefab_missing")
        self.index(["prefab_missing"])
        self.write("reference/components/component_missing.md",
                   "---\ntitle: component_missing\ntype: component\nstatus: active\n---\n"
                   "# component_missing\n\n正文。\n")
        self.write("reference/components/index.md",
                   "---\ntitle: 组件索引\ntype: index\n---\n# 组件索引\n\n"
                   "| 入口 |\n|---|\n| [[reference/components/component_missing|c]] |\n")
        report = self.build(severity=["info"])
        pages = {item["page"] for item in report["findings"]
                 if item["code"] == "backlink-missing"}
        self.assertEqual(pages, {"reference/prefabs/prefab_missing.md"})
        self.assertEqual(report["unresolved"]["backlink_missing"], 1)
        full = self.build(severity=["info"], missing_scope="all", scope="all")
        pages = {item["page"] for item in full["findings"]
                 if item["code"] == "backlink-missing"}
        self.assertEqual(pages, {"reference/prefabs/prefab_missing.md",
                                 "reference/components/component_missing.md"})
        self.assertEqual(full["unresolved"]["backlink_missing"], 2)

    def test_case_variants_are_hints_not_ownership(self):
        self.prefab("one", ["test_fx"])
        self.prefab("two", ["TEST_FX"])
        self.index(["one", "two"])
        registrations = self.reg({"entries": [{"name": "test_fx", "status": "confirmed"}]})
        report = self.build(registrations, severity=["error", "warning", "info"])
        codes = {item["code"] for item in report["findings"]}
        self.assertNotIn("alias-conflict", codes)
        self.assertIn("alias-case-variant", codes)
        self.assertEqual(report["counts"]["error"], 0)

    def test_coverage_ignores_component_and_archived_pages(self):
        self.write("reference/components/component_cover.md",
                   "---\ntitle: component_cover\ntype: component\nstatus: active\n"
                   "aliases: [test_fx]\n---\n# component_cover\n")
        self.prefab("archived_cover", ["test_fx"], status="archived")
        self.index(["archived_cover"])
        registrations = self.reg({"entries": [{"name": "test_fx", "status": "confirmed"}]})
        report = self.build(registrations)
        gaps = [item for item in report["findings"] if item["code"] == "coverage-gap"]
        self.assertEqual([item["name"] for item in gaps], ["test_fx"])

    def test_coverage_case_variant_is_not_exact(self):
        self.prefab("upper_only", ["TEST_FX"])
        self.index(["upper_only"])
        registrations = self.reg({"entries": [{"name": "test_fx", "status": "confirmed"}]})
        report = self.build(registrations)
        gap = next(item for item in report["findings"] if item["code"] == "coverage-gap")
        self.assertIn("case-variant", gap["message"])

    def test_changed_scope_keeps_conflicts_with_second_owner(self):
        self.prefab("owner_a", ["shared_reg"])
        self.prefab("owner_b", ["shared_reg"])
        self.index(["owner_a", "owner_b"])
        registrations = self.reg({"entries": [{"name": "shared_reg", "status": "confirmed"}]})
        changed = self.root / "changed.txt"
        changed.write_text("reference/prefabs/owner_b.md\n", encoding="utf-8")
        report = self.build(registrations, changed=changed)
        conflicts = [item for item in report["findings"] if item["code"] == "alias-conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["pages"],
                         ["reference/prefabs/owner_a.md", "reference/prefabs/owner_b.md"])

    def test_html_comments_do_not_supply_backlinks(self):
        body = ("正文。\n\n<!--\n返回 [[reference/prefabs/index|索引]]。\n-->\n\n"
                "返回 [[reference/index|参考]]。")
        self.prefab("comment", back=None, body=body)
        self.index(["comment"])
        report = self.build()
        item = next(item for item in report["findings"]
                    if item["code"] == "backlink-mismatch")
        self.assertEqual(item["page"], "reference/prefabs/comment.md")

    def test_crlf_preserves_backlink_line_numbers(self):
        rel = "reference/prefabs/bad.md"
        self.prefab("bad", back="返回 [[reference/index|参考]]。")
        self.index(["bad"])
        path = self.wiki / rel
        path.write_bytes(path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
        report = self.build()
        item = next(item for item in report["findings"] if item["code"] == "backlink-mismatch")
        self.assertEqual(item["line"], self.line_of(rel, "返回"))

    def test_index_rows_count_table_data_only(self):
        text = ("---\ntitle: x\ntype: index\n---\n# x\n\n| a | b |\n|---|---|\n"
                "| 1 | 2 |\n| 3 | 4 |\n\n" + FENCE + "md\n| fake | x |\n|---|---|\n| y | z |\n"
                + FENCE + "\n\n| c | d |\n|---|---|\n| 5 | 6 |\n")
        self.assertEqual(coverage.index_rows(text), 3)

    def test_index_budget_reminder_and_hard_limits(self):
        limits = coverage.page.load_limits(self.format)
        self.table_index("reference/prefabs/small.md", 4)
        records = coverage.read_pages(self.wiki)
        reminder = coverage.check_index_budgets(records, limits, 3, 10 ** 9, "all")[0]
        self.assertEqual(reminder["code"], "index-budget-reminder")
        self.assertIn("table data rows", reminder["message"])
        self.assertIn("physical lines", reminder["message"])

        self.table_index("reference/prefabs/huge.md", 25)
        records = coverage.read_pages(self.wiki)
        errors = {item["page"]: item for item in
                  coverage.check_index_budgets(records, limits, 3, 10 ** 9, "all")
                  if item["code"] == "index-budget"}
        self.assertEqual(errors["reference/prefabs/huge.md"]["line"], 21)

        self.table_index("reference/prefabs/wide.md", 6, width=400)
        records = coverage.read_pages(self.wiki)
        wide = next(item for item in coverage.check_index_budgets(records, limits, 3, 10 ** 9, "all")
                    if item["page"] == "reference/prefabs/wide.md")
        self.assertEqual(wide["code"], "index-budget")
        self.assertGreaterEqual(wide["line"], 1)
        self.assertLessEqual(wide["line"], 14)

        self.table_index("index.md", 12)
        records = coverage.read_pages(self.wiki)
        root = next(item for item in coverage.check_index_budgets(records, limits, 3, 10 ** 9, "all")
                    if item["page"] == "index.md")
        self.assertEqual(root["line"], 11)

    def test_coverage_gap_is_warning_until_strict(self):
        self.prefab("covered_stem")
        self.prefab("alias_page", ["covered_alias"])
        self.index(["covered_stem", "alias_page"])
        registrations = coverage.load_registrations(self.reg({"entries": [
            {"name": "covered_stem", "status": "confirmed"},
            {"name": "covered_alias", "status": "confirmed"},
            {"name": "missing_reg", "status": "confirmed"},
            {"name": "cand", "status": "candidate"},
            {"name": "unknown", "status": "unresolved"}]}))
        records = coverage.read_pages(self.wiki)
        findings = coverage.check_coverage(records, registrations, False)
        self.assertEqual([(item["name"], item["severity"]) for item in findings],
                         [("missing_reg", "warning")])
        findings = coverage.check_coverage(records, registrations, True)
        self.assertEqual([(item["name"], item["severity"]) for item in findings],
                         [("missing_reg", "error")])

    def test_report_counts_groups_and_detail_limit(self):
        self.prefab("one", back="返回 [[reference/index|参考]]。")
        self.prefab("two", back="返回 [[reference/index|参考]]。")
        self.index(["one", "two"])
        report = self.build(limit=1)
        for key in ("snapshot", "scope", "checks", "counts", "unresolved", "hits_total",
                    "shown", "truncated", "omitted", "findings", "groups", "passed",
                    "exit_reason"):
            self.assertIn(key, report)
        self.assertEqual(set(report["findings"][0]),
                         {"code", "severity", "page", "name", "line", "message", "pages"})
        self.assertEqual(report["counts"]["total"], 2)
        self.assertEqual(report["counts"]["warning"], 2)
        self.assertEqual(report["hits_total"], 2)
        self.assertEqual(report["shown"], 1)
        self.assertEqual(report["omitted"], 1)
        self.assertTrue(report["truncated"])
        self.assertTrue(report["passed"])
        self.assertEqual(report["exit_reason"], "non-blocking")
        self.assertEqual(report["groups"][0]["count"], 2)
        self.assertEqual(report["groups"][0]["key"], "reference/prefabs/index")

    def test_info_is_aggregated_until_requested(self):
        for name in ("one", "two", "three"):
            self.prefab(name)
        self.index(["one", "two", "three"])
        report = self.build()
        self.assertEqual(report["counts"]["total"], 3)
        self.assertEqual(report["shown"], 0)
        self.assertEqual(report["omitted"], 3)
        self.assertFalse(report["truncated"])
        self.assertEqual(report["groups"][0]["code"], "backlink-missing")
        self.assertEqual(report["groups"][0]["count"], 3)
        expanded = self.build(severity=["info"])
        self.assertEqual(expanded["shown"], 3)
        self.assertEqual(expanded["omitted"], 0)
        by_code = self.build(code=["backlink-missing"])
        self.assertEqual(by_code["shown"], 3)
        limited = self.build(code=["backlink-missing"], limit=1)
        self.assertEqual(limited["shown"], 1)
        self.assertTrue(limited["truncated"])

    def test_changed_scope_filters_detail_only(self):
        self.prefab("one", back="返回 [[reference/index|参考]]。")
        self.prefab("two", back="返回 [[reference/index|参考]]。")
        self.index(["one", "two"])
        changed = self.root / "changed.txt"
        changed.write_text("reference/prefabs/one.md\n", encoding="utf-8")
        report = self.build(changed=changed)
        self.assertEqual(report["scope"]["changed"], 1)
        self.assertEqual([item["page"] for item in report["findings"]],
                         ["reference/prefabs/one.md"])
        self.assertEqual(report["counts"]["total"], 2)
        outside = self.root / "outside.txt"
        outside.write_text(str(self.root / "elsewhere.md"), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.build(changed=outside)

    def test_default_scope_reports_only_prefab_pages(self):
        self.prefab("one", ["shared phrase"],
                    back="返回 [[reference/prefabs/index|索引]]。")
        self.prefab("two", ["shared phrase"],
                    back="返回 [[reference/prefabs/index|索引]]。")
        self.index(["one", "two"])
        self.write("reference/components/bad.md",
                   "---\ntitle: bad\ntype: component\nstatus: active\n---\n"
                   "# bad\n\n正文。\n\n返回 [[reference/index|参考]]。\n")
        self.write("reference/components/index.md",
                   "---\ntitle: 组件索引\ntype: index\n---\n# 组件索引\n\n"
                   "| 入口 |\n|---|\n| [[reference/components/bad|bad]] |\n")
        self.table_index("reference/prefabs/big.md", 25)
        report = self.build(severity=["warning", "info"])
        self.assertEqual(report["counts"]["total"], 0)
        self.assertEqual(report["checks"]["indexes"], "skipped")
        self.assertEqual(report["checks"]["page_scope"], "prefab")
        full = self.build(scope="all", severity=["error", "warning", "info"])
        codes = {item["code"] for item in full["findings"]}
        self.assertIn("backlink-mismatch", codes)
        self.assertIn("index-budget", codes)
        self.assertIn("alias-shared-phrase", codes)

    def test_fail_on_threshold(self):
        self.prefab("bad", back="返回 [[reference/index|参考]]。")
        self.index(["bad"])
        warning = self.build()
        self.assertTrue(warning["passed"])
        self.assertEqual(warning["exit_reason"], "non-blocking")
        strict = self.build(fail_on="warning")
        self.assertFalse(strict["passed"])
        self.assertEqual(strict["exit_reason"], "warning")
        info_only = self.build()  # no info findings here
        self.assertTrue(info_only["passed"])

    def test_clean_report_and_checks(self):
        self.prefab("only", back="返回 [[reference/prefabs/index|索引]]。")
        self.index(["only"])
        report = self.build()
        self.assertEqual((report["hits_total"], report["shown"], report["truncated"],
                          report["omitted"]), (0, 0, False, 0))
        self.assertTrue(report["passed"])
        self.assertEqual(report["exit_reason"], "clean")
        self.assertEqual(report["snapshot"], "unknown")
        self.assertEqual(report["checks"], {
            "page_scope": "prefab", "alias_ownership": "suspected-only",
            "coverage_gaps": "skipped", "backlinks": "checked",
            "indexes": "skipped", "snapshot_source": "none"})
        report = self.build(self.reg({"snapshot": "fixture:1", "entries": []}))
        self.assertEqual(report["snapshot"], "fixture:1")
        self.assertEqual(report["checks"]["snapshot_source"], "registrations")
        self.assertEqual(report["checks"]["coverage_gaps"], "checked")

    def test_registration_input_schema_and_errors(self):
        registrations = coverage.load_registrations(self.reg(["a", "b"]))
        self.assertEqual([entry["status"] for entry in registrations["entries"]],
                         ["unresolved", "unresolved"])
        registrations = coverage.load_registrations(self.reg({
            "snapshot": "s", "prefabs": [{"id": "x"}, {"name": "y", "status": "confirmed"}]}))
        self.assertEqual(registrations["snapshot"], "s")
        self.assertEqual([(entry["name"], entry["status"]) for entry in registrations["entries"]],
                         [("x", "unresolved"), ("y", "confirmed")])
        for payload in (["X", "x"], [{"name": "x", "status": "bogus"}], {"snapshot": "s"},
                        {"snapshot": 1, "entries": []}, "{"):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    coverage.load_registrations(self.reg(payload))
        with self.assertRaises(ValueError):
            coverage.load_registrations(self.root / "missing.json")

    def test_cli_exit_codes_json_and_failure_paths(self):
        self.prefab("good", back="返回 [[reference/prefabs/index|索引]]。")
        self.index(["good"])
        clean = self.cli("--wiki-root", self.wiki, "--format", self.format, "--json")
        self.assertEqual(clean.returncode, 0, clean.stderr)
        data = json.loads(clean.stdout)
        self.assertTrue(data["passed"])
        self.assertEqual(data["hits_total"], 0)

        self.prefab("bad", back="返回 [[reference/index|参考]]。")
        self.index(["good", "bad"])
        warning = self.cli("--wiki-root", self.wiki, "--format", self.format, "--json")
        self.assertEqual(warning.returncode, 0)
        self.assertEqual(json.loads(warning.stdout)["counts"]["warning"], 1)
        strict = self.cli("--wiki-root", self.wiki, "--format", self.format,
                          "--json", "--fail-on", "warning")
        self.assertEqual(strict.returncode, 1)
        self.assertFalse(json.loads(strict.stdout)["passed"])

        self.table_index("reference/prefabs/huge.md", 25)
        error = self.cli("--wiki-root", self.wiki, "--format", self.format,
                         "--json", "--scope", "all")
        self.assertEqual(error.returncode, 1)
        self.assertTrue(json.loads(error.stdout)["counts"]["error"] >= 1)

        broken = self.reg({"entries": [{"name": "x", "status": "bogus"}]})
        failed = self.cli("--wiki-root", self.wiki, "--format", self.format,
                          "--registrations", broken)
        self.assertEqual(failed.returncode, 2)
        self.assertIn("FAIL:", failed.stderr)
        missing = self.cli("--wiki-root", self.wiki, "--format", self.root / "missing.md")
        self.assertEqual(missing.returncode, 2)

    def test_detail_filters_from_cli(self):
        self.prefab("one")
        self.prefab("two")
        self.index(["one", "two"])
        report = self.cli("--wiki-root", self.wiki, "--format", self.format,
                          "--json", "--severity", "info")
        self.assertEqual(report.returncode, 0)
        data = json.loads(report.stdout)
        self.assertEqual(data["counts"]["info"], 2)
        self.assertEqual(data["shown"], 2)
        limited = self.cli("--wiki-root", self.wiki, "--format", self.format,
                           "--json", "--severity", "info", "--limit", "1")
        data = json.loads(limited.stdout)
        self.assertEqual(data["shown"], 1)
        self.assertTrue(data["truncated"])

    def test_checker_is_read_only(self):
        self.prefab("a", ["x"])
        self.index(["a"])
        registrations = self.reg({"entries": [{"name": "missing", "status": "confirmed"}]})
        before = {path.relative_to(self.root).as_posix(): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        self.build(registrations)
        after = {path.relative_to(self.root).as_posix(): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
