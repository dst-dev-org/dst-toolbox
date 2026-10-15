"""Source citation checks: boundaries, warnings, read-only behavior and CLI."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/verify/validate_source_links.py"
SPEC = importlib.util.spec_from_file_location("dst_source_links", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class SourceLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dst-source-links-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wiki = self.root / "knowledge with spaces/wiki"
        self.page = self.wiki / "reference/components/example.md"
        self.page.parent.mkdir(parents=True)
        self.source = self.wiki.parent / "raw/current/scripts/components/test.lua"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"local x = 1\n\nend\n-- WARNING: lifecycle boundary\nreturn x\n")
        self.page.write_text("# Example\n", encoding="utf-8")
        self.link = "../../../raw/current/scripts/components/test.lua"

    def check(self, text, **kwargs):
        self.page.write_text(text, encoding="utf-8")
        return checker.scan(self.wiki, **kwargs)

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-I", str(SCRIPT),
                               "--wiki-root", str(self.wiki), *args],
                              cwd=self.root, capture_output=True, text=True, encoding="utf-8")

    def test_lf_crlf_and_bom_preserve_line_numbers_and_context(self):
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline):
                self.source.write_bytes(b"\xef\xbb\xbf" + newline.join([b"local x = 1", b"", b"end", b"return x", b""]))
                self.page.write_bytes((f"# Example\n\n[blank]({self.link}#L2)\n").replace("\n", newline.decode()).encode())
                report = checker.scan(self.wiki, context=1)
                issue = report["issues"][0]
                self.assertEqual(issue["wiki_line"], 3)
                self.assertEqual(issue["lines"], [2, 2])
                self.assertEqual([x["text"] for x in issue["context"]], ["local x = 1", "", "end"])
                self.assertEqual(issue["source_lines"], 4)

    def test_file_range_and_warning_comments_are_valid(self):
        report = self.check(f"[file]({self.link}) [range]({self.link}#L1-L5) [comment]({self.link}#L4)\n")
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["file_only"], 1)
        self.assertEqual(report["counts"]["line_references"], 2)
        self.assertEqual(report["issues"], [])

    def test_blank_and_structural_are_warnings_not_semantic_errors(self):
        report = self.check(f"[blank]({self.link}#L2) [end]({self.link}#L3)\n")
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["warnings"], 2)
        self.assertEqual(report["counts"]["errors"], 0)
        self.assertEqual(set(report["by_code"]), {"source-blank", "source-structural"})

    def test_range_end_blank_is_reported_without_single_line_duplicates(self):
        report = self.check(f"[range]({self.link}#L1-L2) [single]({self.link}#L2)\n")
        self.assertTrue(report["passed"])
        self.assertEqual(report["by_code"], {"source-blank": 1, "source-end-blank": 1})
        self.assertEqual([i["anchor"] for i in report["issues"]], ["end", "start"])
        self.assertEqual(report["issues"][0]["lines"], [1, 2])
        both = self.check(f"[both]({self.link}#L2-L2)\n")
        self.assertEqual(both["counts"]["warnings"], 1)
        result = self.cli("--strict")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_both_blank_endpoints_are_independent_but_closing_end_is_normal(self):
        self.source.write_text("\nreturn x\n\n", encoding="utf-8")
        report = self.check(f"[range]({self.link}#L1-L3)\n")
        self.assertEqual([i["anchor"] for i in report["issues"]], ["start", "end"])
        for closing in ("end", "}", "end)"):
            with self.subTest(closing=closing):
                self.source.write_text("local x = 1\n" + closing + "\n", encoding="utf-8")
                report = self.check(f"[function]({self.link}#L1-L2)\n")
                self.assertEqual(report["issues"], [])

    def test_structural_endings_and_comments_are_only_review_candidates(self):
        for line, warning in (("end) -- callback", True), ("else", True), ("},", True),
                              ("-- WARNING: lifecycle", False), ("return {}", False),
                              ("local endpoint = true", False)):
            with self.subTest(line=line):
                self.source.write_text(line + "\n", encoding="utf-8")
                report = self.check(f"[candidate]({self.link}#L1)\n")
                self.assertTrue(report["passed"])
                self.assertEqual(report["counts"]["warnings"], int(warning))

    def test_invalid_ranges_missing_files_and_bad_fragments_are_errors(self):
        report = self.check("\n".join(f"[bad]({self.link}{fragment})" for fragment in
                                      ("#L0", "#L6", "#L4-L2", "#L1-L6", "#Lx", "#L1-L")) +
                            f"\n[missing]({self.link.replace('test.lua', 'absent.lua')}#L1)\n")
        self.assertFalse(report["passed"])
        self.assertEqual(report["counts"]["errors"], 7)
        self.assertEqual(report["by_code"], {"source-fragment": 2, "source-line": 3,
                                            "source-range": 1, "source-read": 1})

    def test_empty_source_and_invalid_utf8_are_reported(self):
        for content, code in ((b"", "source-line"), (b"\xff\n", "source-read")):
            self.source.write_bytes(content)
            report = self.check(f"[bad]({self.link}#L1)\n")
            self.assertEqual(report["issues"][0]["code"], code)

    def test_code_images_remote_and_non_lua_links_are_ignored(self):
        bad = f"[bad]({self.link}#L999)"
        report = self.check(f"`{bad}`\n````lua\n```\n{bad}\n````\n~~~\n{bad}\n~~~\n"
                            f"!{bad}\n[remote](https://example.com/test.lua#L999)\n"
                            f"[network](//example.com/test.lua#L999)\n[translation](strings.po#L999)\n"
                            f"[`valid label`]({self.link}#L1)\n")
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["references"], 1)

    def test_html_comments_preserve_line_numbers_and_same_line_links_lf_crlf(self):
        for newline in ("\n", "\r\n"):
            text = (f"# Example\n[before]({self.link}#L1) <!-- [hidden]({self.link}#L99)\n"
                    f"```\n[hidden]({self.link}#L99)\n"
                    f"--> [after]({self.link}#L2) <!-- second --> [last]({self.link}#L3)\n")
            self.page.write_bytes(text.replace("\n", newline).encode("utf-8"))
            before = self.page.read_bytes()
            report = checker.scan(self.wiki, context=0)
            self.assertEqual(report["counts"]["references"], 3)
            self.assertEqual(report["counts"]["errors"], 0)
            self.assertEqual([i["wiki_line"] for i in report["issues"]], [5, 5])
            self.assertEqual([i["lines"] for i in report["issues"]], [[2, 2], [3, 3]])
            self.assertEqual(self.page.read_bytes(), before)

    def test_comment_markers_in_code_do_not_hide_later_links(self):
        report = self.check(f"`<!--` [one]({self.link}#L1)\n"
                            f"``<!--`` [two]({self.link}#L1)\n"
                            f"```lua\n<!--\n```\n[three]({self.link}#L1)\n"
                            f"<!-- [hidden]({self.link}#L99) --> [four]({self.link}#L1)\n")
        self.assertEqual(report["counts"]["references"], 4)
        self.assertEqual(report["issues"], [])

    def test_indented_links_are_still_checked_and_unclosed_comment_is_masked(self):
        report = self.check(f"- list\n    [list link]({self.link}#L2)\n\n"
                            f"    [indented code]({self.link}#L3)\n"
                            f"<!-- unclosed\n[hidden]({self.link}#L99)\n")
        self.assertEqual(report["counts"]["references"], 2)
        self.assertEqual([i["wiki_line"] for i in report["issues"]], [2, 4])

    def test_quoted_encoded_and_parenthesized_paths(self):
        target = self.source.with_name("with space (copy).lua")
        target.write_text("return true\n", encoding="utf-8")
        prefix = self.link.rsplit("/", 1)[0]
        report = self.check(f"[one](<{prefix}/with space (copy).lua#L1>)\n"
                            f'[two]({prefix}/with%20space%20(copy).lua#L1 "title")\n')
        self.assertTrue(report["passed"], report["issues"])
        self.assertEqual(report["counts"]["references"], 2)
        self.assertEqual(report["counts"]["unique_targets"], 1)

    def test_historical_link_is_checked_without_remapping_to_current(self):
        old = self.wiki.parent / "raw/archive/build-old/scripts/test.lua"
        old.parent.mkdir(parents=True)
        old.write_text("local historical = true\nreturn historical\n", encoding="utf-8")
        report = self.check("[old](../../../raw/archive/build-old/scripts/test.lua#L2)\n")
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["warnings"], 0)

    def test_generated_or_demo_sources_warn_but_still_check_line_ranges(self):
        demo = self.wiki.parent / "output/demo.lua"
        demo.parent.mkdir()
        demo.write_text("return true\n", encoding="utf-8")
        report = self.check("[demo](../../../output/demo.lua#L1)\n"
                            "[bad demo](../../../output/demo.lua#L99)\n")
        self.assertEqual(report["by_code"], {"source-line": 1, "source-outside-raw": 2})
        self.assertFalse(report["passed"])
        report = self.check("[demo](../../../output/demo.lua#L1)\n")
        self.assertTrue(report["passed"])
        self.assertEqual(report["counts"]["warnings"], 1)
        self.assertEqual(self.cli("--strict").returncode, 1)

    def test_current_snapshot_version_is_context_not_an_archive_claim(self):
        build = self.wiki.parent / "raw/current/BUILD.txt"
        self.assertEqual(checker.scan(self.wiki)["current_snapshot_version"]["state"], "missing")
        for content, expected in ((b"\xef\xbb\xbf123\r\n", "123"), (b"unknown\n", "unknown"), (b"", "")):
            build.write_bytes(content)
            report = checker.scan(self.wiki)
            self.assertTrue(report["passed"])
            version = report["current_snapshot_version"]
            self.assertEqual(version["value"], expected)
            self.assertEqual(version["path"], "raw/current/BUILD.txt")
            self.assertEqual(version["state"], "recorded" if expected else "empty")
        build.write_bytes(b"\xff\n")
        report = checker.scan(self.wiki)
        self.assertTrue(report["passed"])
        self.assertEqual(report["current_snapshot_version"]["state"], "unreadable")

    def test_outside_root_is_rejected_without_reading_the_target(self):
        outside = self.root / "outside.lua"
        outside.write_bytes(b"\xff")
        report = self.check("[outside](../../../../outside.lua#L1)\n")
        self.assertEqual(report["issues"][0]["code"], "source-outside-root")
        self.assertEqual(report["counts"]["source_files"], 0)

    def test_range_context_is_bounded_and_long_lines_are_marked(self):
        self.source.write_text("\n" + "x" * 400 + "\n" + "return x\n" * 98, encoding="utf-8")
        report = self.check(f"[range]({self.link}#L1-L100)\n", context=1)
        context = report["issues"][0]["context"]
        self.assertEqual([x["line"] for x in context], [1, 2, 99, 100])
        self.assertTrue(context[1]["clipped"])
        self.assertEqual(len(context[1]["text"]), 240)

    def test_truncation_preserves_all_counts_and_duplicates_keep_wiki_locations(self):
        report = self.check((f"[blank]({self.link}#L2)\n" * 3) + f"[error]({self.link}#L99)\n",
                            max_issues=1)
        self.assertEqual(report["counts"]["warnings"], 3)
        self.assertEqual(report["counts"]["errors"], 1)
        self.assertEqual(report["counts"]["unique_targets"], 2)
        self.assertEqual(len(report["issues"]), 1)
        self.assertTrue(report["truncated"])
        self.assertEqual(report["omitted"], 3)
        self.assertEqual(report["by_page"], [{"page": "reference/components/example.md",
                                             "references": 4, "errors": 1, "warnings": 3}])

    def test_page_summaries_prioritize_errors_are_bounded_and_count_all_issues(self):
        self.page.write_text(f"[bad]({self.link}#L2)\n" * 3, encoding="utf-8")
        other = self.page.with_name("other.md")
        other.write_text(f"[bad]({self.link}#L99)\n", encoding="utf-8")
        report = checker.scan(self.wiki, max_issues=1)
        self.assertEqual(report["problem_pages"], 2)
        self.assertEqual(report["by_page_omitted"], 1)
        self.assertEqual(report["by_page"], [{"page": "reference/components/other.md",
                                             "references": 1, "errors": 1, "warnings": 0}])
        self.assertEqual(report["counts"]["warnings"], 3)
        self.assertEqual(report["omitted"], 3)

    def test_default_scan_excludes_log_archive_and_engineering_docs(self):
        for name in ("log.md", "log-archive/old.md", "docs/report.md"):
            path = self.wiki / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[bad](missing.lua#L999)\n", encoding="utf-8")
        report = checker.scan(self.wiki)
        self.assertEqual(report["counts"]["pages"], 1)
        self.assertEqual(report["issues"], [])

    def test_selected_pages_are_relative_to_wiki_not_cwd(self):
        self.page.write_text(f"[valid]({self.link}#L1)\n", encoding="utf-8")
        result = self.cli("reference/components/example.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"]["references"], 1)
        self.assertEqual(self.cli(str(self.root / "outside.md")).returncode, 2)

    def test_cli_exit_codes_strict_and_no_input_mutation(self):
        self.page.write_text(f"[blank]({self.link}#L2)\n", encoding="utf-8")
        before = {p.relative_to(self.root): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob("*") if p.is_file()}
        for args, expected in (((), 0), (("--strict",), 1), (("--context", "6"), 2)):
            result = self.cli(*args)
            self.assertEqual(result.returncode, expected, result.stderr)
            if expected != 2:
                report = json.loads(result.stdout)
                self.assertEqual(report["passed"], expected == 0)
        after = {p.relative_to(self.root): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_missing_root_empty_scope_and_page_read_errors(self):
        with self.assertRaisesRegex(ValueError, "existing directory"):
            checker.scan(self.root / "missing")
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, "no Wiki Markdown"):
            checker.scan(empty)
        report = checker.scan(self.wiki, ["absent.md"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["issues"][0]["code"], "page-read")


if __name__ == "__main__":
    unittest.main()
