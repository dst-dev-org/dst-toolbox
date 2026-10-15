"""Targeted regressions for the read-only Prefab name locator."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/verify"))
from inspect_prefab_names import candidate_keys, collect_evidence, find_entries, inspect_page, main, read_name_catalog


class PrefabNameTests(unittest.TestCase):
    def test_descriptive_title_flags_missing_game_name(self):
        page = Path("moon-altar-pieces.md")
        meta = {"title": "天体祭坛部件与岩石包裹", "summary": "敲开岩石包裹",
                "aliases": ["moon_altar_rock_glass", "月坛岩石", "Inviting Formation"]}
        key = "STRINGS.NAMES.MOON_ALTAR_ROCK_GLASS"
        po = f'msgctxt "{key}"\nmsgid "Inviting Formation"\nmsgstr "吸引人的结构"\n'
        keys = candidate_keys(page, meta)
        self.assertEqual(keys, {key})
        entries = find_entries(po, keys)
        candidate = inspect_page(page, meta, keys, set(), entries)["candidates"][0]
        self.assertEqual(candidate["zh_cn"], "吸引人的结构")
        self.assertEqual(candidate["present_in"], [])
        self.assertTrue(candidate["review_visible_name"])

        meta["aliases"].append("吸引人的结构")
        candidate = inspect_page(page, meta, keys, set(), entries)["candidates"][0]
        self.assertEqual(candidate["present_in"], ["aliases"])
        self.assertTrue(candidate["review_visible_name"])

        meta["summary"] = "敲开吸引人的结构（岩石包裹）"
        candidate = inspect_page(page, meta, keys, set(), entries)["candidates"][0]
        self.assertEqual(candidate["present_in"], ["summary", "aliases"])
        self.assertFalse(candidate["review_visible_name"])

    def test_explicit_skin_key_and_physical_multiline_anchor(self):
        key = "STRINGS.SKIN_NAMES.example"
        po = (f'#. unicode\u2028separator\r\nmsgctxt "{key}"\r\nmsgid "Skin"\r\n'
              'msgstr ""\r\n"魔法"\r\n"帽"\r\n')
        entries = find_entries(po, {key})
        page = Path("example_fx.md")
        meta = {"title": "魔法帽光效", "summary": "", "aliases": ["example_fx"]}
        candidates = inspect_page(page, meta, candidate_keys(page, meta), {key}, entries)["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["match"], "explicit-key")
        self.assertEqual(candidates[0]["zh_cn"], "魔法帽")
        self.assertEqual((candidates[0]["start_line"], candidates[0]["end_line"]), (2, 6))

    def test_untranslated_and_fuzzy_entries_are_not_evidence(self):
        missing, fuzzy, good = [f"STRINGS.NAMES.{name}" for name in ("MISSING", "FUZZY", "GOOD")]
        po = (f'msgctxt "{missing}"\nmsgid "Missing"\nmsgstr ""\n\n'
              f'#, fuzzy\n#. Note\nmsgctxt "{fuzzy}"\nmsgid "Fuzzy"\nmsgstr "暂译"\n\n'
              f'msgctxt "{good}"\nmsgid "Good"\nmsgstr "官方名"\n')
        self.assertEqual(set(find_entries(po, {missing, fuzzy, good})), {good})

    def test_game_display_name_can_be_compared_without_a_po_entry(self):
        page = Path("blueprint.md")
        meta = {"title": "蓝图", "summary": "动态拼接配方名", "aliases": ["木头短剑蓝图"]}
        candidate = inspect_page(page, meta, set(), set(), {}, ("木头短剑蓝图",))["candidates"][0]
        self.assertEqual(candidate, {
            "zh_cn": "木头短剑蓝图", "match": "provided-name",
            "present_in": ["aliases"], "review_visible_name": True,
        })

    def test_catalog_only_lookup_handles_multiline_and_blank_values(self):
        path = Path("prefab-names.csv").resolve()
        data = 'prefab,zh_name\r\nworld,世界\r\nforest,\r\nplaybill,"舞台\n演出"\r\n'
        with patch.object(Path, "open", return_value=io.StringIO(data, newline="")):
            catalog = read_name_catalog(path)
        self.assertNotIn("STRINGS.NAMES.FOREST", catalog)
        self.assertEqual(catalog["STRINGS.NAMES.PLAYBILL"], "舞台\n演出")

        stream = io.StringIO()
        with (patch("inspect_prefab_names.read_name_catalog", return_value=catalog),
              patch.object(sys, "stdout", stream), patch.object(stream, "reconfigure", create=True)):
            self.assertEqual(main(["--name-catalog", str(path), "--key", "STRINGS.NAMES.WORLD",
                                   "--key", "STRINGS.NAMES.FOREST"]), 0)
        report = json.loads(stream.getvalue())
        self.assertEqual(report["lookups"], [
            {"key": "STRINGS.NAMES.WORLD", "zh_cn": "世界", "match": "runtime-name-catalog"},
        ])
        self.assertEqual(report["missing_explicit_keys"], ["STRINGS.NAMES.FOREST"])
        self.assertIsNone(report["po_evidence"])

    def test_catalog_and_po_prefer_matching_po_with_line_evidence(self):
        page = Path("world.md")
        meta = {"title": "世界", "summary": "", "aliases": ["world"]}
        key = "STRINGS.NAMES.WORLD"
        keys = {key}
        po = find_entries(f'msgctxt "{key}"\nmsgid "World"\nmsgstr "世界"\n', keys)
        same = inspect_page(page, meta, keys, set(), po, catalog={key: "世界"})["candidates"]
        different = inspect_page(page, meta, keys, set(), po, catalog={key: "旧名"})["candidates"]
        self.assertEqual([(row["zh_cn"], row["start_line"]) for row in same], [("世界", 1)])
        self.assertEqual([row["zh_cn"] for row in different], ["世界", "旧名"])

    def test_batch_keeps_names_with_their_pages_and_replays_without_po_read(self):
        a, b = (Path(name).resolve() for name in ("a.md", "b.md"))
        root = Path("scripts").resolve()
        source = root / "languages/chinese_s.po"
        key = "STRINGS.NAMES.OVERRIDE"
        contents = {
            a: '---\ntype: prefab\ntitle: A\nsummary: 描述\naliases: []\n---\n',
            b: '---\ntype: prefab\ntitle: B\nsummary: 描述\naliases: []\n---\n',
            source: f'msgctxt "{key}"\nmsgid "Override"\nmsgstr "覆盖名"\n',
        }

        def run(args, prior=""):
            stream = io.StringIO()
            input_stream = io.TextIOWrapper(io.BytesIO(prior.encode("utf-8")), encoding="utf-8")
            with (input_stream, patch.object(sys, "stdin", input_stream), patch.object(sys, "stdout", stream),
                  patch.object(stream, "reconfigure", create=True)):
                self.assertEqual(main(args), 0)
            return stream.getvalue()

        with (patch("inspect_prefab_names.source_identity", return_value={"path": str(source)}),
              patch.object(Path, "read_text", autospec=True, side_effect=lambda path, **_: contents[path]) as reads):
            initial = run(["--source-root", str(root), "--page-key", str(a), key,
                           "--page-name", str(b), "实显名"])
            self.assertEqual(sum(call.args[0] == source for call in reads.call_args_list), 1)
            del contents[source]
            contents[b] = contents[b].replace("summary: 描述", "summary: 实显名")
            replay = run(["--reuse", "-"], initial)
        before, after = (json.loads(report)["pages"] for report in (initial, replay))
        self.assertEqual([[name["zh_cn"] for name in p["candidates"]] for p in after], [["覆盖名"], ["实显名"]])
        self.assertTrue(before[1]["candidates"][0]["review_visible_name"])
        self.assertFalse(after[1]["candidates"][0]["review_visible_name"])

    def test_reuse_rejects_different_source_or_unchecked_keys(self):
        evidence = {"source": {"build": "1"}, "checked_keys": ["STRINGS.NAMES.A"], "entries": {}}
        with patch("inspect_prefab_names.source_identity", return_value={"build": "2"}):
            with self.assertRaisesRegex(ValueError, "same unchanged PO"):
                collect_evidence(Path("names.po"), {"STRINGS.NAMES.A"}, evidence)
        with patch("inspect_prefab_names.source_identity", return_value=evidence["source"]):
            with self.assertRaisesRegex(ValueError, "did not check 1 key"):
                collect_evidence(Path("names.po"), {"STRINGS.NAMES.B"}, evidence)


if __name__ == "__main__":
    unittest.main()
