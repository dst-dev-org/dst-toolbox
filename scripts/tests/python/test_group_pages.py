"""Batch grouping candidates: thresholds, boilerplate, clusters and CLI."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2]
SCRIPT = SCRIPTS / "tools/wiki/group_pages.py"
SPEC = importlib.util.spec_from_file_location("dst_group_pages", SCRIPT)
grouping = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grouping)


def page(name, sources, links, kind="prefab", build="steam-buildid:26474873"):
    quoted = ", ".join(json.dumps(value) for value in sources)
    body = "\n".join(f"- 见 [[{target}]]" for target in links)
    return (
        "---\n"
        f"title: {name}\n"
        f"type: {kind}\n"
        f'dst_build: "{build}"\n'
        f"sources: [{quoted}]\n"
        "---\n\n"
        f"# {name}\n\n"
        f"{body}\n\n"
        "返回 [[reference/prefabs/index|Prefab 索引]]。\n"
    )


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dst-group-pages-",
                                                 ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skip_cleanup = False
        self.wiki = self.root / "wiki"
        (self.wiki / "reference/prefabs").mkdir(parents=True)
        (self.wiki / "reference/components").mkdir(parents=True)
        (self.wiki / "reference/index.md").write_text("---\ntitle: 参考\ntype: index\n---\n", encoding="utf-8")
        (self.wiki / "reference/prefabs/index.md").write_text("---\ntitle: Prefab\ntype: index\n---\n", encoding="utf-8")

    def write(self, name, text):
        path = self.wiki / "reference/prefabs" / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        return path

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--wiki-root", str(self.wiki), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def test_shared_links_and_sources_group(self):
        self.write("alpha", page("alpha", ["prefabs/a.lua", "components/mine.lua", "components/trap.lua"],
                                 ["reference/components/mine", "reference/components/trap", "reference/prefabs/beta"]))
        self.write("beta", page("beta", ["prefabs/b.lua", "components/mine.lua", "components/trap.lua"],
                                ["reference/components/mine", "reference/components/trap", "reference/prefabs/alpha"]))
        done = self.run_tool("--category", "prefab")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(report["groups"][0]["pages"], ["reference/prefabs/alpha", "reference/prefabs/beta"])
        self.assertEqual(report["groups"][0]["pairs"], 1)

    def test_boilerplate_excluded(self):
        # 6 页、ratio 0.5 => 门槛 3：5 页共引的算样板，2 页共引的不算。
        boiler = [f"common{i}.lua" for i in range(6)]
        for index, name in enumerate(("alpha", "beta", "gamma", "delta", "epsilon")):
            self.write(name, page(name, boiler, []))
        self.write("zeta", page("zeta", ["prefabs/z.lua"], []))
        self.write("alpha", page("alpha", boiler + ["prefabs/a.lua"], []))
        self.write("beta", page("beta", boiler + ["prefabs/a.lua"], []))
        done = self.run_tool("--category", "prefab", "--boilerplate-ratio", "0.5",
                              "--rare-limit", "0")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        names = [item["path"] for item in report["boilerplate"]["sources"]]
        self.assertIn("common0.lua", names)
        self.assertNotIn("prefabs/a.lua", names)
        self.assertEqual(report["groups"], [])

    def test_backlink_gap_states(self):
        self.write("alpha", page("alpha", ["prefabs/a.lua", "components/mine.lua", "components/trap.lua"],
                                 ["reference/components/mine", "reference/components/trap", "reference/prefabs/beta"]))
        self.write("beta", page("beta", ["prefabs/b.lua", "components/mine.lua", "components/trap.lua"],
                                ["reference/components/mine", "reference/components/trap"]))
        done = self.run_tool("--category", "prefab")
        report = json.loads(done.stdout)
        states = {(item["a"], item["b"]): item["state"] for item in report["backlink_gaps"]}
        self.assertEqual(states[("reference/prefabs/alpha", "reference/prefabs/beta")], "a-to-b")
        self.assertEqual(report["groups"][0]["pages"],
                         ["reference/prefabs/alpha", "reference/prefabs/beta"])

    def test_mutual_required_for_cluster_member(self):
        hub = ["prefabs/a.lua", "components/mine.lua", "components/trap.lua"]
        self.write("alpha", page("alpha", hub, ["reference/prefabs/hub"]))
        self.write("beta", page("beta", hub, ["reference/prefabs/gamma"]))
        self.write("gamma", page("gamma", hub, []))
        self.write("hub", page("hub", [], []))
        done = self.run_tool("--category", "prefab")
        report = json.loads(done.stdout)
        for group in report["groups"]:
            self.assertLessEqual(len(group["pages"]), 5)
            self.assertNotIn(["reference/prefabs/alpha", "reference/prefabs/beta"], [group["pages"]])

    def test_common_link_alone_is_not_family(self):
        # 6 页共引同一组件 => 该链接不稀有，单靠它不足以成为候选对。
        shared = ["components/stackable.lua", "prefabs/a.lua"]
        for name in ("alpha", "beta", "gamma", "delta", "epsilon"):
            self.write(name, page(name, shared, ["reference/components/stackable"]))
        done = self.run_tool("--category", "prefab", "--shared-links", "1", "--rare-limit", "2")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(report["pairs"], 0)

    def test_gap_only_inside_group(self):
        hub = ["prefabs/a.lua", "components/mine.lua", "components/trap.lua"]
        self.write("alpha", page("alpha", hub, ["reference/components/mine", "reference/components/trap"]))
        self.write("beta", page("beta", hub, ["reference/components/mine", "reference/components/trap"]))
        self.write("gamma", page("gamma", hub, ["reference/prefabs/delta"]))
        self.write("delta", page("delta", ["prefabs/d.lua", "components/mine.lua", "components/trap.lua"],
                                 ["reference/prefabs/gamma"]))
        done = self.run_tool("--category", "prefab", "--max-group", "2")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        grouped = {tuple(sorted(group["pages"])) for group in report["groups"]}
        for gap in report["backlink_gaps"]:
            self.assertIn(tuple(sorted([gap["a"], gap["b"]])), grouped)

    # --- family evidence: construction modules, pillar mechanics, naming ----------

    def test_construction_module_ignores_rarity(self):
        # staff_common.lua 被很多页引用；*_common / *_defs 是共享构造模块，仍算同厂证据。
        shared = ["prefabs/staff.lua", "prefabs/staff_common.lua"]
        for name in ("staffs", "yellowstaff", "opalstaff", "gamma", "delta", "epsilon"):
            self.write(name, page(name, shared, []))
        done = self.run_tool("--category", "prefab", "--rare-limit", "2")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        names = [item["path"] for item in report["boilerplate"]["sources"]]
        self.assertNotIn("prefabs/staff_common.lua", names)
        self.assertTrue(report["groups"], "construction module must keep the family grouped")
        biggest = max(report["groups"], key=lambda group: len(group["pages"]))
        self.assertIn("reference/prefabs/staffs", biggest["pages"])

    def test_pillar_mechanic_is_family_evidence(self):
        # armor 是页面的主机制；两页共引它即可成组，即使 source 完全不重叠。
        self.write("alpha", page("alpha", ["prefabs/a.lua"], ["reference/components/armor"]))
        self.write("beta", page("beta", ["prefabs/b.lua"], ["reference/components/armor"]))
        done = self.run_tool("--category", "prefab")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(report["groups"][0]["pages"],
                         ["reference/prefabs/alpha", "reference/prefabs/beta"])

    def test_generic_capability_is_not_family_evidence(self):
        # weapon / finiteuses 是"大类按钮"，两页共引不足以成组。
        for name in ("alpha", "beta"):
            self.write(name, page(name, [f"prefabs/{name}.lua"],
                                   ["reference/components/weapon"]))
        done = self.run_tool("--category", "prefab", "--shared-sources", "3", "--rare-limit", "0")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(report["groups"], [])

    def test_named_page_is_unidirectional_evidence(self):
        # 只有 alpha 正文点名 beta；点名是单向证据，足够入组。
        self.write("alpha", page("alpha", ["prefabs/a.lua"], ["reference/prefabs/beta"]))
        self.write("beta", page("beta", ["prefabs/b.lua"], []))
        done = self.run_tool("--category", "prefab")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(report["groups"][0]["pages"],
                         ["reference/prefabs/alpha", "reference/prefabs/beta"])

    def test_return_line_alone_is_not_evidence(self):
        # 两页只共引返回行里的索引入口，不构成邻接。
        body = page("alpha", ["prefabs/a.lua"], [])
        self.write("alpha", body)
        self.write("beta", page("beta", ["prefabs/b.lua"], []))
        done = self.run_tool("--category", "prefab")
        report = json.loads(done.stdout)
        self.assertEqual(report["pairs"], 0)

    def test_index_links_do_not_create_adjacency(self):
        # 共引 *-index 页本身不算稀有链接证据。
        for name in ("alpha", "beta"):
            self.write(name, page(name, [f"prefabs/{name}.lua"],
                                   ["reference/prefabs/tools-field-index",
                                    "reference/components/armor"]))
        done = self.run_tool("--category", "prefab")
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(report["groups"][0]["pages"],
                         ["reference/prefabs/alpha", "reference/prefabs/beta"])

    def test_unknown_page_is_input_error(self):
        done = self.run_tool(str(self.wiki / "reference/prefabs/missing.md"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("not a knowledge page", done.stderr)

    def test_page_outside_wiki_root_is_input_error(self):
        outside = self.root / "outside.md"
        outside.write_text(page("outside", [], []), encoding="utf-8")
        done = self.run_tool(str(outside))
        self.assertEqual(done.returncode, 2)
        self.assertIn("outside Wiki root", done.stderr)


if __name__ == "__main__":
    unittest.main()
