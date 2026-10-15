"""Reference-page budgets, legacy defaults and the public validator entrypoint."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_page as fixture


class SizeClassTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wiki = self.root / "wiki"
        self.target = self.wiki / "reference/components/test.md"
        self.target.parent.mkdir(parents=True)

    def text(self, profile=None):
        return fixture.TEXT if profile is None else fixture.TEXT.replace(
            "type: component", f"type: component\nsize_class: {profile}")

    def check(self, text, policy=fixture.FORMAT):
        self.target.write_bytes(text.encode("utf-8"))
        return fixture.page.check_page(self.target, self.wiki, format_path=policy)

    def policy(self, text):
        path = self.root / "policy.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_unmarked_legacy_page_keeps_standard_budget(self):
        legacy = self.check(self.text())
        explicit = self.check(self.text("standard"))
        self.assertTrue(legacy["passed"] and explicit["passed"])
        for key in ("size_class", "max_lines", "max_bytes"):
            self.assertEqual(legacy["size"][key], explicit["size"][key])
        self.assertEqual((legacy["size"]["max_lines"], legacy["size"]["max_bytes"]),
                         (200, 16 * 1024))

    def test_utf8_byte_boundaries_for_all_classes(self):
        for profile, kib in (("simple", 8), ("standard", 16), ("complex", 32)):
            with self.subTest(profile=profile):
                base = self.text(profile) + "\n中文\n"
                exact = base + "x" * (kib * 1024 - len(base.encode("utf-8")))
                self.assertTrue(self.check(exact)["passed"])
                report = self.check(exact + "x")
                self.assertFalse(report["passed"])
                issue = next(i for i in report["issues"] if i["code"] == "size-bytes")
                self.assertEqual(issue["byte"], kib * 1024)

    def test_line_boundaries_for_all_classes(self):
        for profile, lines in (("simple", 120), ("standard", 200), ("complex", 400)):
            with self.subTest(profile=profile):
                base = self.text(profile)
                exact = base + "\n" * (lines - base.count("\n"))
                self.assertTrue(self.check(exact)["passed"])
                report = self.check(exact + "\n")
                issue = next(i for i in report["issues"] if i["code"] == "size-lines")
                self.assertEqual(issue["line"], lines + 1)

    def test_invalid_class_values_are_metadata_errors(self):
        for value in ("tiny", "null", "[]", "{name: complex}", "12", "true"):
            with self.subTest(value=value):
                report = self.check(self.text(value))
                self.assertFalse(report["passed"])
                self.assertIn("invalid size_class", str(report["issues"]))

    def test_indexes_and_cookbook_cannot_override_their_budget(self):
        for name, kind, category in (("index.md", "index", "root"),
                                     ("reference/components/index.md", "index", "index"),
                                     ("cookbook/test.md", "cookbook", "cookbook")):
            with self.subTest(name=name):
                target = self.wiki / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(self.text("complex").replace("type: component", f"type: {kind}"),
                                  encoding="utf-8")
                report = fixture.page.check_page(target, self.wiki, format_path=fixture.FORMAT)
                self.assertFalse(report["passed"])
                self.assertIn("only to reference knowledge pages", str(report["issues"]))
                self.assertEqual(report["size"]["category"], category)
                self.assertEqual(report["size"]["max_bytes"], fixture.page.load_limits(fixture.FORMAT)[category][1])

    def test_class_limits_come_from_selected_policy(self):
        policy = fixture.FORMAT.read_text(encoding="utf-8").replace(
            "| 400 | 32 KiB |", "| 360 | 28 KiB |")
        report = self.check(self.text("complex"), self.policy(policy))
        self.assertTrue(report["passed"])
        self.assertEqual((report["size"]["max_lines"], report["size"]["max_bytes"]),
                         (360, 28 * 1024))

    def test_legacy_policy_supports_standard_and_rejects_undefined_class(self):
        policy = fixture.FORMAT.read_text(encoding="utf-8")
        policy = policy.split("### 源码知识页分档\n")[0] + "## 标签\n" + policy.split("## 标签\n")[1]
        path = self.policy(policy)
        self.assertTrue(self.check(self.text(), path)["passed"])
        self.assertTrue(self.check(self.text("standard"), path)["passed"])
        self.assertIn("not defined by the selected format", str(self.check(self.text("complex"), path)["issues"]))

    def test_malformed_class_policies_fail_instead_of_guessing(self):
        policy = fixture.FORMAT.read_text(encoding="utf-8")
        complex_row = "| `complex` | Coupled mechanisms | 400 | 32 KiB |"
        variants = (
            policy.replace(complex_row, complex_row + "\n" + complex_row),
            policy.replace(complex_row, ""),
            policy.replace("| `complex`", "| `unknown`"),
            policy.replace("| `standard` | Typical reference | 200 | 16 KiB |",
                           "| `standard` | Typical reference | 200 | 17 KiB |"),
            policy.replace("| `simple` | Single concern | 120 | 8 KiB |",
                           "| `simple` | Single concern | 0 | 8 KiB |"),
            policy.replace(complex_row, "| `complex` | Coupled mechanisms | 190 | 32 KiB |"),
        )
        for variant in variants:
            with self.subTest(variant=variants.index(variant)):
                with self.assertRaises(ValueError):
                    fixture.page.load_size_classes(self.policy(variant))

    def test_cli_accepts_complex_page_but_preserves_unmarked_limit(self):
        text = self.text("complex") + "x" * (18 * 1024)
        self.target.write_text(text, encoding="utf-8")
        command = [sys.executable, "-B", "-X", "utf8", str(fixture.SCRIPTS / "tools/verify/validate_page.py"),
                   "--wiki-root", str(self.wiki), "--format", str(fixture.FORMAT), str(self.target)]
        run = subprocess.run(command, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["pages"][0]["size"]["size_class"], "complex")
        self.target.write_text(text.replace("size_class: complex\n", ""), encoding="utf-8")
        run = subprocess.run(command, capture_output=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("size-bytes", run.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
