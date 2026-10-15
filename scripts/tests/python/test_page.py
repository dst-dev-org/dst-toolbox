"""Independent metadata/link/size cases, including LF/CRLF and long lines."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2]
FORMAT = SCRIPTS / 'tests/fixtures/page-policy.md'
SPEC = importlib.util.spec_from_file_location("dst_page", SCRIPTS / "tools/verify/validate_page.py")
page = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(page)

TEXT = '''---
title: Synthetic
created: "2026-10-11"
updated: "2026-10-11"
type: component
summary: Test
aliases: [test]
tags: [component]
dst_build: "fixture:one"
sources: [components/test.lua]
reliability: verified
validation: source-reviewed
status: active
---

# Test

## Example
'''


class PageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.wiki = Path(self.temp.name) / "wiki"
        self.target = self.wiki / "reference/components/test.md"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(TEXT.encode())

    def check(self, text=None, limits=None):
        if text is not None:
            self.target.write_bytes(text.encode("utf-8"))
        return page.check_page(self.target, self.wiki, limits, format_path=FORMAT)

    def test_lf_and_crlf_count_physical_lines_and_bytes(self):
        lf = self.check()
        crlf = self.check(TEXT.replace("\n", "\r\n"))
        self.assertTrue(lf["passed"] and crlf["passed"])
        self.assertEqual(lf["size"]["lines"], crlf["size"]["lines"])
        self.assertEqual(crlf["size"]["utf8_bytes"] - lf["size"]["utf8_bytes"], TEXT.count("\n"))

    def test_long_line_and_code_block_exceed_byte_budget(self):
        limits = page.load_limits(FORMAT)
        limits["page"] = (200, 1024)
        for payload in ("字" * 400, "```lua\n" + "字" * 400 + "\n```\n"):
            report = self.check(TEXT + payload, limits)
            issue = next(i for i in report["issues"] if i["code"] == "size-bytes")
            self.assertEqual(issue["byte"], 1024)
            self.assertLess(report["size"]["lines"], 200)

    def test_first_overlimit_line_is_reported(self):
        limits = page.load_limits(FORMAT)
        limits["page"] = (20, 16000)
        report = self.check(TEXT + "\n" * 10, limits)
        self.assertEqual(next(i for i in report["issues"] if i["code"] == "size-lines")["line"], 21)

    def test_missing_link_and_heading(self):
        report = self.check(TEXT + "[[reference/components/missing]]\n[[reference/components/test#missing]]\n")
        self.assertEqual({i["code"] for i in report["issues"]}, {"link", "link-anchor"})
        self.assertTrue(self.check(TEXT + "[[reference/components/test#example]]\n")["passed"])

    def test_code_links_are_not_navigation(self):
        self.assertTrue(self.check(TEXT + "```lua\n-- [[reference/components/missing]]\n```\n")["passed"])

    def test_duplicate_metadata_and_unknown_status(self):
        self.assertFalse(self.check(TEXT.replace("title: Synthetic", "title: A\ntitle: B"))["passed"])
        self.assertFalse(self.check(TEXT.replace("status: active", "status: invented"))["passed"])

    def test_unsafe_source_and_link_escape(self):
        report = self.check(TEXT.replace("components/test.lua", "../outside.lua") + "[[../outside]]\n")
        self.assertEqual({i["code"] for i in report["issues"]}, {"source-path", "link"})

    def test_log_is_excluded(self):
        target = self.wiki / "log.md"
        target.write_text("maintenance\n")
        with self.assertRaisesRegex(ValueError, "log is excluded"):
            page.check_page(target, self.wiki, format_path=FORMAT)

    def test_limits_are_read_from_authoritative_table(self):
        self.assertEqual(page.load_limits(FORMAT)["page"], (200, 16 * 1024))
        self.assertEqual(page.load_limits(FORMAT)["cookbook"], (300, 24 * 1024))

    def test_type_checks_semantic_category_inside_reference(self):
        for category in ("api", "prefabs", "stategraphs"):
            target = self.wiki / "reference" / category / "test.md"
            target.parent.mkdir(parents=True)
            target.write_text(TEXT, encoding="utf-8")
            self.assertIn("type differs", str(page.check_page(target, self.wiki, format_path=FORMAT)["issues"]))
        target = self.wiki / "reference/api/modinfo/fields.md"
        target.parent.mkdir(parents=True)
        target.write_text(TEXT.replace("type: component", "type: api").replace("tags: [component]", "tags: [modding]"), encoding="utf-8")
        self.assertTrue(page.check_page(target, self.wiki, format_path=FORMAT)["passed"])


if __name__ == "__main__":
    unittest.main()
