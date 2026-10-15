"""Relocation plans must preserve evidence and never mutate input files."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/maintenance/plan_source_link_updates.py"
SPEC = importlib.util.spec_from_file_location("dst_link_updates", SCRIPT)
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


class SourceLinkUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dst-link-updates-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "knowledge with spaces"
        self.wiki = self.root / "wiki"
        self.page = self.wiki / "reference/components/example.md"
        self.old = self.root / "raw/archive/build-old/scripts"
        self.new = self.root / "raw/current/scripts"
        self.page.parent.mkdir(parents=True)
        for root in (self.old, self.new):
            (root / "components").mkdir(parents=True)
        self.source = "components/test.lua"
        self.link = "../../../raw/current/scripts/components/test.lua"
        self.code = "function Example:Run()\n    local value = 1\n    return value\nend\n"
        self.inputs(self.code, "-- inserted\n" + self.code)

    def inputs(self, old, new, text=None):
        (self.old / self.source).write_text(old, encoding="utf-8", newline="\n")
        (self.new / self.source).write_text(new, encoding="utf-8", newline="\n")
        self.page.write_text(text or f"# Example\n\n[code]({self.link}#L2-L3)\n", encoding="utf-8", newline="\n")

    def scan(self, **kwargs):
        return planner.scan(self.wiki, self.old, self.new, [self.page], **kwargs)

    def test_unique_equal_block_maps_interior_range(self):
        report = self.scan(include_patch=True)
        self.assertTrue(report["mechanical_passed"])
        self.assertEqual(report["proposals"][0]["new_lines"], [3, 4])
        self.assertIn(f"+[code]({self.link}#L3-L4)", report["patch"])
        self.assertIn("*** Update File: wiki/reference/components/example.md", report["patch"])
        self.assertEqual(report["patch_root"], str(self.root.resolve()))
        self.assertNotIn("dst_build", report["patch"])

    def test_same_file_and_bom_crlf_changes_keep_positions(self):
        for value in (self.code.encode(), b"\xef\xbb\xbf" + self.code.replace("\n", "\r\n").encode()):
            (self.new / self.source).write_bytes(value)
            report = self.scan(include_patch=True)
            self.assertEqual(report["counts"]["unchanged"], 1)
            self.assertEqual(report["patch"], "")

    def test_changes_outside_reference_only_prove_location(self):
        self.inputs(self.code + "local unrelated = 1\n", self.code + "local unrelated = 2\n")
        report = self.scan()
        self.assertTrue(report["mechanical_passed"])
        self.assertEqual(report["counts"]["unchanged"], 1)
        self.assertIn("claim support / DST semantics", report["not_checked"])

    def test_changed_interior_cannot_be_approved_by_matching_endpoints(self):
        self.inputs(self.code, self.code.replace("value = 1", "value = 2"))
        report = self.scan(include_patch=True)
        self.assertFalse(report["mechanical_passed"])
        self.assertEqual(report["issues"][0]["code"], "changed-or-cross-hunk")
        self.assertEqual(report["patch"], "")

    def test_repeated_identical_blocks_are_ambiguous(self):
        self.inputs(self.code, self.code + self.code)
        report = self.scan()
        self.assertEqual(report["issues"][0]["code"], "ambiguous-or-insufficient-context")

    def test_whole_matching_block_has_no_external_context(self):
        self.page.write_text(f"[whole]({self.link}#L1-L4)\n", encoding="utf-8", newline="\n")
        report = self.scan(include_patch=True)
        self.assertEqual(report["issues"][0]["code"], "insufficient-context")
        self.assertEqual(report["patch"], "")

    def test_deleted_body_reintroduced_in_another_function_is_not_relocated(self):
        self.inputs("function A()\nlocal x = 1\nend\n",
                    "function A()\nend\nfunction B()\nlocal x = 1\nend\n",
                    f"[A body]({self.link}#L2)\n")
        report = self.scan(include_patch=True)
        self.assertFalse(report["mechanical_passed"])
        self.assertEqual(report["issues"][0]["code"], "insufficient-context")
        self.assertEqual(report["counts"]["proposed"], 0)
        self.assertEqual(report["patch"], "")

    def test_structural_or_comment_only_external_context_is_not_sufficient(self):
        self.inputs("-- comment\nlocal x = 1\nend\n",
                    "-- added\n-- comment\nlocal x = 1\nend\n",
                    f"[body]({self.link}#L2)\n")
        self.assertEqual(self.scan()["issues"][0]["code"], "ambiguous-or-insufficient-context")

    def test_long_comment_body_cannot_justify_movement_to_another_function(self):
        for equals in ("", "=", "=="):
            opening, closing = "--[" + equals + "[", "]" + equals + "]"
            body = f"{opening}\nnote\n{closing}\nlocal x = 1\nend\n"
            self.inputs("function A()\n" + body,
                        "function A()\nend\nfunction B()\n" + body,
                        f"[A body]({self.link}#L5)\n")
            report = self.scan(include_patch=True)
            self.assertEqual(report["counts"]["proposed"], 0)
            self.assertEqual(report["issues"][0]["code"], "ambiguous-or-insufficient-context")
            self.assertEqual(report["patch"], "")

    def test_comment_lexer_handles_strings_long_brackets_and_code_after_close(self):
        lines = ['local text = "--[[ not a comment"', '--[=[', 'note',
                 ']=] local value = 1', 'end -- ignored', 'local text = [==[',
                 '--[[ inside a string', ']==] return value']
        self.assertEqual(planner.context_code_flags(lines),
                         [True, False, False, True, False, True, False, True])

    def test_crlf_page_keeps_proposals_but_never_emits_normalizing_patch(self):
        self.page.write_bytes(f"# Example\r\n\r\n[code]({self.link}#L2-L3)\r\n".encode())
        before = self.page.read_bytes()
        report = self.scan(include_patch=True)
        self.assertEqual(report["counts"]["proposed"], 1)
        self.assertEqual(report["issues"][0]["code"], "patch-line-endings")
        self.assertFalse(report["mechanical_passed"])
        self.assertEqual(report["patch"], "")
        self.assertEqual(self.page.read_bytes(), before)
        self.assertTrue(self.scan()["mechanical_passed"])

    def test_page_bom_and_missing_final_newline_need_format_preserving_transport(self):
        text = f"[code]({self.link}#L2-L3)\n".encode()
        for value in (b"\xef\xbb\xbf" + text, text.rstrip(b"\n")):
            self.page.write_bytes(value)
            report = self.scan(include_patch=True)
            self.assertEqual(report["issues"][0]["code"], "patch-page-format")
            self.assertEqual(report["patch"], "")

    def test_blank_or_structural_old_start_requires_review(self):
        for old, anchor in ((self.code, 4), ("\n" + self.code, 1)):
            self.inputs(old, "-- insertion\n" + old, f"[weak]({self.link}#L{anchor})\n")
            report = self.scan()
            self.assertEqual(report["issues"][0]["code"], "weak-old-anchor")

    def test_invalid_old_ranges_never_guess(self):
        for anchor in ("L0", "L9", "L4-L1", "L1-L9"):
            self.page.write_text(f"[bad]({self.link}#{anchor})\n", encoding="utf-8", newline="\n")
            self.assertEqual(self.scan()["issues"][0]["code"], "old-range-invalid")

    def test_missing_old_or_new_source_are_distinct(self):
        (self.old / self.source).unlink()
        report = self.scan()
        self.assertEqual(report["counts"]["review"], 1)
        self.assertEqual(report["issues"][0]["code"], "old-source-missing-or-case")
        (self.old / self.source).write_text(self.code, encoding="utf-8")
        (self.new / self.source).unlink()
        self.assertEqual(self.scan()["counts"]["errors"], 1)

    def test_wrong_case_is_rejected_even_on_case_tolerant_filesystems(self):
        self.page.write_text(f"[wrong]({self.link.replace('test.lua', 'TEST.lua')}#L1)\n", encoding="utf-8")
        self.assertEqual(self.scan()["issues"][0]["code"], "new-source-missing-or-case")

    def test_same_line_duplicates_and_ignored_links_keep_their_spans(self):
        citation = f"[code]({self.link}#L2-L3)"
        self.page.write_text(f"`{citation}` {citation} {citation} <!-- {citation} -->\n"
                             f"```lua\n{citation}\n```\n", encoding="utf-8", newline="\n")
        report = self.scan(include_patch=True)
        self.assertEqual(report["counts"]["proposed"], 2)
        addition = next(line for line in report["patch"].splitlines() if line.startswith("+") and "[code]" in line)
        self.assertEqual(addition.count("#L3-L4"), 2)
        self.assertEqual(addition.count("#L2-L3"), 2)

    def test_angle_encoded_paths_preserve_destination_and_title(self):
        name = "components/with space (copy).lua"
        for root in (self.old, self.new):
            (root / self.source).rename(root / name)
        self.page.write_text('[code](<../../../raw/current/scripts/components/with%20space%20(copy).lua#L2-L3> "title")\n', encoding="utf-8", newline="\n")
        report = self.scan(include_patch=True)
        self.assertIn('with%20space%20(copy).lua#L3-L4> "title")', report["patch"])

    def test_historical_links_are_preserved_not_mapped_to_current(self):
        link = self.link.replace("current", "archive/build-old")
        self.page.write_text(f"[old]({link}#L1-L4)\n", encoding="utf-8")
        report = self.scan(include_patch=True)
        self.assertEqual(report["counts"]["skipped_other_snapshot"], 1)
        self.assertEqual(report["patch"], "")

    def test_boundaries_and_invalid_parameters_are_rejected(self):
        self.page.write_text("[outside](../../../output/test.lua#L1)\n", encoding="utf-8")
        self.assertEqual(self.scan()["issues"][0]["code"], "source-outside-raw")
        for kwargs in ({"max_items": 0}, {"max_items": 1001}):
            with self.assertRaises(ValueError):
                self.scan(**kwargs)
        with self.assertRaises(ValueError):
            planner.scan(self.wiki, self.old, self.new, [self.root / "outside.md"])
        with self.assertRaises(ValueError):
            planner.scan(self.wiki, self.old, self.old, [self.page])

    def test_invalid_utf8_and_fragment_are_visible(self):
        self.page.write_text(f"[bad]({self.link}#function)\n", encoding="utf-8")
        self.assertEqual(self.scan()["issues"][0]["code"], "source-fragment")
        (self.new / self.source).write_bytes(b"\xff")
        self.assertEqual(self.scan()["issues"][0]["code"], "source-read")

    def test_truncation_preserves_counts_and_complete_explicit_patch(self):
        self.page.write_text("\n".join(f"[code]({self.link}#L2-L3)" for _ in range(3)) + "\n", encoding="utf-8", newline="\n")
        report = self.scan(max_items=1, include_patch=True)
        self.assertEqual(report["counts"]["proposed"], 3)
        self.assertEqual(report["proposals_omitted"], 2)
        self.assertEqual(report["patch"].count("+[code]"), 3)

    def test_cli_is_read_only_and_exit_codes_distinguish_review(self):
        before = {p: sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}
        args = [sys.executable, "-B", "-I", str(SCRIPT), "--wiki-root", str(self.wiki),
                "--old-source-root", str(self.old), "--new-source-root", str(self.new),
                "--include-patch", str(self.page)]
        result = subprocess.run(args, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["patch"])
        after = {p: sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.inputs(self.code, self.code.replace("value = 1", "value = 2"))
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)
        args[args.index(str(self.old))] = str(self.root / "missing")
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)

    @unittest.skipUnless(os.environ.get("DST_TEST_CODEX_BINARY"), "optional local apply_patch binary not configured")
    def test_patch_actually_applies_at_knowledge_root_without_other_byte_changes(self):
        report = self.scan(include_patch=True)
        before = self.page.read_bytes()
        source_hashes = {p: sha256(p.read_bytes()).hexdigest()
                         for root in (self.old, self.new) for p in root.rglob("*.lua")}
        result = subprocess.run([os.environ["DST_TEST_CODEX_BINARY"], "--codex-run-as-apply-patch",
                                 report["patch"]], cwd=report["patch_root"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(self.page.read_bytes(), before.replace(b"#L2-L3", b"#L3-L4"))
        self.assertEqual(source_hashes, {p: sha256(p.read_bytes()).hexdigest() for p in source_hashes})


if __name__ == "__main__":
    unittest.main()
