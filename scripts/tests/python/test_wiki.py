"""Independent navigation, retrieval, stale-cache and chapter-output invariants."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2]
FORMAT = SCRIPTS / 'tests/fixtures/page-policy.md'
sys.path.insert(0, str(SCRIPTS / "tools/wiki"))
import query_wiki as query
import wiki_data as wiki


def index_text(title, table="", extra=""):
    return f'''---
title: {title}
created: 2026-10-11
updated: 2026-10-11
type: index
tags: [overview]
---
# {title}
| 入口 | 需求 | 状态 |
|---|---|---|
{table}
{extra}
'''


def page_text(name="uses", summary="工具按次数消耗", aliases="工具耐久", kind="component", state="active"):
    return f'''---
title: {name}
created: 2026-10-11
updated: 2026-10-11
type: {kind}
summary: {summary}
aliases: [{aliases}]
tags: [{kind}]
dst_build: "fixture:one"
sources: [components/{name}.lua]
reliability: verified
validation: source-reviewed
status: {state}
---
# {name}
## 快速判断
- 职责与适用：服务端工具消耗。
## 关键接口
`SetUses(amount)` 设置次数。
## 典型接入
### 修改已有斧头耐久
- 前提：目标模组已经加载。
```lua
SetUses(200)
-- ## This is not a heading
-- [[reference/components/missing]] is not navigation
```
## 常见陷阱与限制
不要把修改上限当作修改当前次数。
## 验证记录
只审阅了源码，未运行游戏。
'''


class WikiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wiki = self.root / "wiki"
        self.write("index.md", index_text("导航", "| [[reference/index]] | 机制 | |"))
        self.write("reference/index.md", index_text("机制", "| [[reference/components/index]] | 组件 | |"))
        self.write("reference/components/index.md", index_text("组件", "| [[reference/components/uses]] | 工具 | active |"))
        self.write("reference/components/uses.md", page_text())

    def write(self, path, text):
        target = self.wiki / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
        return target

    def build(self):
        return wiki.build(self.wiki, format_path=FORMAT)

    def cache(self):
        cache = self.root / "index.json"
        cache.write_text(wiki.encode(self.build()), encoding="utf-8")
        return cache

    def cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "tools/wiki/query_wiki.py"),
                               "--wiki-root", str(self.wiki), *args], capture_output=True)

    def test_exact_name_and_method_skip_navigation_and_target_relevant_section(self):
        data = self.build()
        self.assertEqual(query.search(data, ["uses"])["results"][0]["chapter"], "快速判断")
        self.assertEqual(query.search(data, ["SetUses"])["results"][0]["chapter"], "关键接口")

    def test_alias_and_scene_demand(self):
        data = self.build()
        self.assertEqual(query.search(data, ["工具耐久"])["results"][0]["path"], "reference/components/uses.md")
        self.assertEqual(query.search(data, ["修改已有斧头耐久"])["results"][0]["chapter"], "修改已有斧头耐久")

    def test_nested_api_topic_and_cookbook_keep_direct_lookup(self):
        self.write("index.md", index_text("导航", "| [[reference/index]] | | |\n| [[cookbook/index]] | | |"))
        self.write("reference/index.md", index_text("机制", "| [[reference/components/index]] | | |\n| [[reference/api/index]] | | |"))
        self.write("reference/api/index.md", index_text("API", "| [[reference/api/modinfo/index]] | | |"))
        self.write("reference/api/modinfo/index.md", index_text("modinfo", "| [[reference/api/modinfo/fields]] | | active |"))
        api = page_text("fields", "模组加载优先级", "priority", "api").replace("tags: [api]", "tags: [modding]")
        self.write("reference/api/modinfo/fields.md", api)
        self.write("cookbook/index.md", index_text("任务", "| [[cookbook/starter]] | | active |"))
        self.write("cookbook/starter.md", page_text("starter", "模组起步", "模组框架", "cookbook"))
        data = self.build()
        self.assertEqual(data["coverage"]["knowledge_pages"], 3)
        result = query.search(data, ["priority"], path="reference/api/modinfo/")
        self.assertEqual(result["results"][0]["path"], "reference/api/modinfo/fields.md")
        self.assertEqual(query.read_chapter(self.wiki, "reference/api/modinfo/fields#关键接口")["path"],
                         "reference/api/modinfo/fields.md")
        self.assertEqual(data["navigation"]["registrations"]["reference/api/modinfo/fields.md"],
                         ["reference/api/modinfo/index.md"])

    def test_reference_container_cannot_register_pages_or_mix_categories(self):
        self.write("reference/index.md", index_text("机制", "| [[reference/components/index]] | | |\n| [[reference/components/uses]] | | |"))
        self.assertIn("registration-category", {i["code"] for i in wiki.page.check_indexes(self.wiki)["issues"]})
        self.write("reference/index.md", index_text("机制", "| [[reference/components/index]] | | |\n| [[reference/api/index]] | | |"))
        self.write("reference/components/index.md", index_text("组件"))
        self.write("reference/api/index.md", index_text("API", "| [[reference/components/uses]] | | |"))
        issues = wiki.page.check_indexes(self.wiki)["issues"]
        self.assertIn("registration-category", {i["code"] for i in issues})
        self.assertIn("registration", {i["code"] for i in issues})

    def test_cookbook_local_pages_and_topic_index_keep_one_registration(self):
        self.write("index.md", index_text("导航", "| [[reference/index]] | | |\n| [[cookbook/index]] | | |"))
        self.write("cookbook/index.md", index_text("任务",
                   "| [[cookbook/starter]] | 起步 | active |\n| [[cookbook/equipment/index]] | 装备 | |"))
        self.write("cookbook/starter.md", page_text("starter", "模组起步", "模组框架", "cookbook"))
        self.write("cookbook/equipment/index.md", index_text("装备", "| [[cookbook/equipment/hand]] | 手持 | active |"))
        self.write("cookbook/equipment/hand.md", page_text("hand", "手部装备", "手持物", "cookbook"))
        data = self.build()
        self.assertEqual(data["navigation"]["registrations"]["cookbook/starter.md"], ["cookbook/index.md"])
        self.assertEqual(data["navigation"]["registrations"]["cookbook/equipment/hand.md"],
                         ["cookbook/equipment/index.md"])
        self.assertEqual(query.search(data, ["手持物"], path="cookbook/equipment/")["results"][0]["path"],
                         "cookbook/equipment/hand.md")

        # A parent index cannot take over a topic's leaf registration.
        self.write("cookbook/equipment/index.md", index_text("装备"))
        self.write("cookbook/index.md", index_text("任务",
                   "| [[cookbook/starter]] | | |\n| [[cookbook/equipment/index]] | | |\n| [[cookbook/equipment/hand]] | | |"))
        self.assertIn("registration-nonleaf", {i["code"] for i in wiki.page.check_indexes(self.wiki)["issues"]})

        # Registering it in both indexes remains a duplicate, not a shortcut.
        self.write("cookbook/equipment/index.md", index_text("装备", "| [[cookbook/equipment/hand]] | | |"))
        self.assertIn("registration", {i["code"] for i in wiki.page.check_indexes(self.wiki)["issues"]})

    def test_reference_inventory_excludes_unrelated_and_old_layout_paths(self):
        for name in ("reference/log.md", "reference/notes.md", "reference/decisions/x.md",
                     "reference/api/templates/x.md", "components/old-layout.md"):
            self.write(name, "uses\n")
        self.assertEqual(set(wiki.inventory(self.wiki)), {
            "index.md", "reference/index.md", "reference/components/index.md", "reference/components/uses.md"})

    def test_mechanism_subtopics_are_registered_queryable_and_make_cache_stale(self):
        self.write("reference/index.md", index_text("机制",
                   "| [[reference/components/index]] | 组件 | |\n| [[reference/mechanisms/index]] | 系统机制 | |"))
        self.write("reference/mechanisms/index.md", index_text("系统机制",
                   "| [[reference/mechanisms/ui/index]] | 界面 | |"))
        self.write("reference/mechanisms/ui/index.md", index_text("界面",
                   "| [[reference/mechanisms/ui/status]] | 玩家界面 | active |"))
        text = page_text("status", "玩家界面", "状态面板", "mechanism").replace(
            "tags: [mechanism]", "tags: [modding]")
        self.write("reference/mechanisms/ui/status.md", text)
        cache = self.cache()
        run = self.cli("search", "status", "--type", "mechanism", "--index", str(cache))
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)["results"]
        self.assertEqual([r["path"] for r in result], ["reference/mechanisms/ui/status.md"])
        self.assertEqual(result[0]["validation"], "source-reviewed")
        chapter = query.read_chapter(self.wiki, "reference/mechanisms/ui/status#关键接口")
        self.assertIn("未运行游戏", "".join(part["text"] for part in chapter["ranges"]))
        self.write("reference/mechanisms/ui/status.md", text + "changed\n")
        _, changes = wiki.load(cache, self.wiki)
        self.assertEqual(changes["changed"], ["reference/mechanisms/ui/status.md"])
        self.assertEqual(self.cli("search", "status", "--type", "mechanism", "--index", str(cache)).returncode, 1)

        self.write("reference/mechanisms/ui/status.md", text.replace("type: mechanism", "type: api"))
        with self.assertRaisesRegex(ValueError, "type differs"):
            self.build()

    def test_prefab_relations_are_crosslinks_and_chapter_read_does_not_follow_them(self):
        self.write("reference/index.md", index_text("机制",
                   "| [[reference/components/index]] | 组件 | |\n| [[reference/prefabs/index]] | 原版对象 | |"))
        self.write("reference/prefabs/index.md", index_text("原版对象",
                   "| [[reference/prefabs/object]] | 组合入口 | active |"))
        text = page_text("object", "组合入口", "原版参照", "prefab").replace(
            "tags: [prefab]", "tags: [modding]")
        start, end = text.index("## 关键接口"), text.index("## 常见陷阱与限制")
        text = text[:start] + ("## 关联机制导航\n| 对象 | Wiki 入口 |\n|---|---|\n"
                              "| 组件 | [[reference/components/uses#关键接口]] |\n") + text[end:]
        self.write("reference/prefabs/object.md", text)
        data = self.build()
        self.assertEqual(data["navigation"]["registrations"]["reference/components/uses.md"],
                         ["reference/components/index.md"])
        selected = query.read_chapter(self.wiki, "reference/prefabs/object#关联机制导航")
        emitted = "".join(part["text"] for part in selected["ranges"])
        self.assertIn("[[reference/components/uses#关键接口]]", emitted)
        self.assertIn("未运行游戏", emitted)
        self.assertNotIn("SetUses(200)", emitted)

    def test_category_move_invalidates_old_cache_with_added_removed_and_navigation(self):
        cache = self.cache()
        self.write("reference/components/tools/uses.md", page_text())
        (self.wiki / "reference/components/uses.md").unlink()
        self.write("reference/components/index.md", index_text("组件", "| [[reference/components/tools/uses]] | | active |"))
        _, changes = wiki.load(cache, self.wiki)
        self.assertEqual(changes["added"], ["reference/components/tools/uses.md"])
        self.assertEqual(changes["removed"], ["reference/components/uses.md"])
        self.assertEqual(changes["changed"], ["reference/components/index.md"])
        response = self.cli("search", "uses", "--index", str(cache))
        self.assertEqual(response.returncode, 1)
        self.assertEqual(json.loads(response.stdout)["results"], [])

    def test_cookbook_and_mechanism_share_five_candidates_across_goals(self):
        self.write("index.md", index_text("导航", "| [[reference/index]] | | |\n| [[cookbook/index]] | | |"))
        rows = []
        for i in range(6):
            name = f"demo{i}"
            # Keep assembly and mechanism goals independent; shared symbols would
            # make this a path-order tie test instead of a shared-budget test.
            text = page_text(name, "新道具骨架", "新物品", "cookbook")
            text = text.replace("`SetUses(amount)` 设置次数。", "`CreateEntity()` 创建实体。")
            text = text.replace("SetUses(200)", "local inst = CreateEntity()")
            self.write(f"cookbook/{name}.md", text)
            rows.append(f"| [[cookbook/{name}]] | | active |")
        self.write("cookbook/index.md", index_text("骨架", "\n".join(rows)))
        result = query.search(self.build(), ["新物品", "SetUses"])
        self.assertEqual(len(result["results"]), 5)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["ambiguous_goals"])
        self.assertEqual({r["type"] for r in result["results"]}, {"cookbook", "component"})

    def test_unrelated_and_history_pages_are_not_default_candidates(self):
        self.write("log.md", "uses\n")
        self.write("decisions/index.md", "uses\n")
        self.write("reference/components/templates/x.md", "uses\n")
        self.write("reference/components/history.md", page_text("history", state="archived"))
        self.write("reference/components/index.md", index_text("组件", "| [[reference/components/uses]] | | active |\n| [[reference/components/history]] | | archived |"))
        data = self.build()
        self.assertEqual(len(data["pages"]), 2)
        self.assertEqual(query.search(data, ["history"])["results"], [])
        self.assertEqual(len(query.search(data, ["history"], history=True)["results"]), 1)

    def test_unknown_conditions_are_explicit_and_not_inferred_from_tags(self):
        target = self.wiki / "reference/components/uses.md"
        target.write_text(page_text().replace("- 职责与适用：服务端工具消耗。", "无明确条件。").replace("- 前提：目标模组已经加载。", ""), encoding="utf-8")
        result = query.search(self.build(), ["uses"])["results"][0]
        self.assertTrue(result["conditions"][0].startswith("unknown"))

    def test_cookbook_condition_section_is_read_without_inference(self):
        text = "## 适用条件\n- 已有服务端模组。\n- 使用原版资源。\n## 最小 demo\n其他内容。\n"
        self.assertEqual(wiki.conditions(text), ["- 已有服务端模组。", "- 使用原版资源。"])

    def test_build_match_mismatch_and_unknown_do_not_imply_runtime_validation(self):
        data = self.build()
        for build, state in [(None, "unknown"), ("fixture:one", "match"), ("fixture:two", "mismatch")]:
            result = query.search(data, ["uses"], build=build)["results"][0]
            self.assertEqual(result["source_version"], state)
            self.assertEqual(result["validation"], "source-reviewed")

    def test_stale_cache_added_removed_changed_including_navigation(self):
        for action, key in [("add", "added"), ("remove", "removed"), ("edit", "changed"), ("nav", "changed")]:
            with self.subTest(action=action):
                cache = self.cache()
                if action == "add":
                    self.write("reference/components/extra.md", page_text("extra"))
                elif action == "remove":
                    (self.wiki / "reference/components/uses.md").unlink()
                elif action == "edit":
                    self.write("reference/components/uses.md", page_text() + "changed\n")
                else:
                    self.write("reference/components/index.md", index_text("组件", "changed"))
                _, changes = wiki.load(cache, self.wiki)
                self.assertTrue(changes[key])
                response = self.cli("search", "uses", "--index", str(cache))
                self.assertEqual(response.returncode, 1)
                self.assertEqual(json.loads(response.stdout)["results"], [])
                (self.wiki / "reference/components/extra.md").unlink(missing_ok=True)
                self.write("reference/components/uses.md", page_text())
                self.write("reference/components/index.md", index_text("组件", "| [[reference/components/uses]] | 工具 | active |"))

    def test_tampered_cache_is_rejected(self):
        cache = self.cache()
        data = json.loads(cache.read_text(encoding="utf-8"))
        data["pages"][0]["meta"]["status"] = "archived"
        cache.write_text(wiki.encode(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            wiki.load(cache, self.wiki)

    def test_read_actual_ranges_preserves_full_code_and_validation(self):
        for newline in ["\n", "\r\n"]:
            text = page_text().replace("\n", newline)
            self.write("reference/components/uses.md", text)
            result = query.read_chapter(self.wiki, "reference/components/uses#修改已有斧头耐久")
            emitted = "".join(r["text"] for r in result["ranges"])
            self.assertIn("SetUses(200)", emitted)
            self.assertIn("未运行游戏", emitted)
            self.assertIn("职责与适用", emitted)
            self.assertNotIn("不要把修改上限", emitted)
            lines = text.splitlines(keepends=True)
            for part in result["ranges"]:
                start, end = part["lines"]
                self.assertEqual(part["text"], "".join(lines[start - 1:end]))
            self.assertLess(result["read_characters"], len(text))

    def test_nested_and_duplicate_headings_ignore_long_fence_contents(self):
        text = "# P\n## A\n### B\ntext\n## A\n## A-1\n````lua\n```\n## Fake\n````\n## End\n"
        chapters = wiki.page.sections(text)
        self.assertEqual([s["anchor"] for s in chapters], ["p", "a", "b", "a-1", "a-1-1", "end"])
        self.assertEqual(chapters[1]["end"], 4)

    def test_nested_case_keeps_parent_preamble_but_omits_sibling(self):
        text = page_text().replace("## 典型接入\n", "## 典型接入\n共同前提：只能服务端。\n")
        text = text.replace("## 常见陷阱与限制", "### 另一个案例\n不要返回此段。\n## 常见陷阱与限制")
        self.write("reference/components/uses.md", text)
        result = query.read_chapter(self.wiki, "reference/components/uses#修改已有斧头耐久")
        emitted = "".join(r["text"] for r in result["ranges"])
        self.assertIn("共同前提", emitted)
        self.assertNotIn("不要返回此段", emitted)

    def test_same_page_subgoals_do_not_repeat_metadata_boundaries_or_code(self):
        result = query.read_targets(self.wiki, ["reference/components/uses#典型接入", "reference/components/uses#关键接口",
                                               "reference/components/uses#典型接入"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["chapters"], ["典型接入", "关键接口"])
        emitted = "".join(part["text"] for part in result[0]["ranges"])
        self.assertEqual(emitted.count("## 验证记录"), 1)
        self.assertEqual(emitted.count("SetUses(200)"), 1)
        self.assertNotIn("不要把修改上限", emitted)

    def test_budget_entire_json_never_slices_code_and_recomputes_goal_gaps(self):
        report = {"mode": "search", "goals": ["a", "b"], "results": [
            {"matched_goals": [0], "text": "小"}, {"matched_goals": [1], "text": "字" * 3000}],
            "truncated": False, "omitted": 0}
        encoded = wiki.bounded(report, 2048)
        self.assertLessEqual(len(encoded.encode()), 2048)
        self.assertEqual(report["output_bytes"], len(encoded.encode()))
        self.assertEqual(report["uncovered_goals"], [1])
        self.assertTrue(report["truncated"])
        self.assertEqual(report["results"][0]["text"], "小")

    def test_oversized_chapter_is_omitted_whole(self):
        self.write("reference/components/uses.md", page_text().replace("SetUses(200)", "-- " + "字" * 2000))
        response = self.cli("--max-bytes", "2048", "read", "reference/components/uses#典型接入")
        self.assertEqual(response.returncode, 0, response.stderr)
        report = json.loads(response.stdout)
        self.assertTrue(report["truncated"])
        self.assertEqual(report["results"], [])
        self.assertLessEqual(len(response.stdout), 2048)
        self.assertEqual(report["output_bytes"], len(response.stdout))

    def test_no_match_is_not_absence_and_path_type_filters_work(self):
        cache = self.cache()
        response = self.cli("search", "QuantumNeverFound", "--index", str(cache))
        report = json.loads(response.stdout)
        self.assertEqual(report["results"], [])
        self.assertEqual(report["uncovered_goals"], [0])
        self.assertIn("targeted", report["next"])
        self.assertEqual(query.search(self.build(), ["uses"], kind="cookbook")["results"], [])
        self.assertEqual(query.search(self.build(), ["uses"], path="reference/prefabs/")["results"], [])
        self.assertEqual(query.search(self.build(), ["修改已有手杖"])["results"], [])
        self.assertEqual(query.search(self.build(), ["物品栏发光"])["results"], [])

    def test_external_paths_logs_and_absent_validation_boundary_rejected(self):
        for target in ["../outside#x", "log#x", "reference/components/uses"]:
            with self.assertRaises(ValueError):
                query.read_chapter(self.wiki, target)
        self.write("reference/components/uses.md", page_text().replace("## 验证记录", "## Other"))
        with self.assertRaisesRegex(ValueError, "validation boundary"):
            query.read_chapter(self.wiki, "reference/components/uses#典型接入")

    def test_missing_or_duplicate_registration_blocks_build(self):
        self.write("reference/components/index.md", index_text("组件"))
        with self.assertRaisesRegex(ValueError, "registration"):
            self.build()
        self.write("reference/components/index.md", index_text("组件", "| [[reference/components/uses]] | | |\n| [[reference/components/uses]] | | |"))
        with self.assertRaisesRegex(ValueError, "registration"):
            self.build()

    def test_crosslink_is_not_registration_and_navigation_parent_required(self):
        self.write("reference/components/index.md", index_text("组件", extra="相关 [[reference/components/uses]]。"))
        self.assertFalse(wiki.page.check_indexes(self.wiki)["passed"])
        self.write("reference/components/index.md", index_text("组件", "| [[reference/components/uses]] | | |"))
        self.write("reference/components/unused/index.md", index_text("Orphan"))
        issues = wiki.page.check_indexes(self.wiki)["issues"]
        self.assertIn("index-unreachable", {i["code"] for i in issues})

    def test_root_cannot_become_full_leaf_list_and_navigation_cycle_rejected(self):
        self.write("index.md", index_text("导航", "| [[reference/components/index]] | | |\n| [[reference/components/uses]] | | |"))
        self.assertIn("root-leaf", {i["code"] for i in wiki.page.check_indexes(self.wiki)["issues"]})
        self.write("index.md", index_text("导航", "| [[reference/components/index]] | | |"))
        self.write("reference/components/index.md", index_text("组件", "| [[index]] | | |\n| [[reference/components/uses]] | | |"))
        self.assertIn("index-cycle", {i["code"] for i in wiki.page.check_indexes(self.wiki)["issues"]})

    def test_top30_inactive_duplicate_and_maximum(self):
        self.write("index.md", index_text("导航", "| [[reference/index]] | | |", "## Top 30 高频入口\n" +
                   "\n".join("- [[reference/components/uses]]" for _ in range(31))))
        codes = {i["code"] for i in wiki.page.check_indexes(self.wiki)["issues"]}
        self.assertEqual(codes, {"top30-target", "top30-count"})
        self.write("index.md", index_text("导航", "| [[reference/index]] | | |", "## Top 30 高频入口\n- [[reference/components/uses]]"))
        self.write("reference/components/uses.md", page_text(state="review-needed"))
        self.assertIn("top30-target", {i["code"] for i in wiki.page.check_indexes(self.wiki)["issues"]})

    def test_archived_page_may_leave_normal_navigation_but_history_can_find_it(self):
        self.write("reference/components/old.md", page_text("old", state="archived"))
        data = self.build()
        self.assertEqual(query.search(data, ["old"])["results"], [])
        self.assertEqual(len(query.search(data, ["old"], history=True)["results"]), 1)

    def test_tag_taxonomy_and_oversized_pages_block_publication(self):
        self.write("reference/components/uses.md", page_text().replace("tags: [component]", "tags: [made-up]"))
        with self.assertRaisesRegex(ValueError, "unknown tag"):
            self.build()
        self.write("reference/components/uses.md", page_text() + "字" * 6000)
        with self.assertRaisesRegex(ValueError, "size-bytes"):
            self.build()

    def test_complex_page_builds_and_selected_chapter_stays_bounded(self):
        text = page_text().replace("type: component", "type: component\nsize_class: complex")
        text += "\n## Unrelated background\n" + ("background " * 8 + "\n") * 250
        target = self.write("reference/components/uses.md", text)
        cache = self.cache()
        data, changes = wiki.load(cache, self.wiki)
        self.assertFalse(any(changes.values()))
        self.assertEqual(data["pages"][0]["meta"]["size_class"], "complex")
        run = self.cli("read", "reference/components/uses#关键接口")
        self.assertEqual(run.returncode, 0, run.stderr)
        response = json.loads(run.stdout)
        emitted = "".join(r["text"] for r in response["results"][0]["ranges"])
        self.assertIn("SetUses(amount)", emitted)
        self.assertIn("未运行游戏", emitted)
        self.assertNotIn("Unrelated background", emitted)
        self.assertFalse(response["truncated"])
        self.assertLessEqual(len(run.stdout), 16000)
        target.write_text(text.replace("size_class: complex\n", ""), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "size-(lines|bytes)"):
            self.build()

    def test_large_category_routes_only_relevant_leaf_and_search_does_not_emit_all(self):
        self.write("reference/components/index.md", index_text("组件", "| [[reference/components/tools/index]] | 工具 | |\n| [[reference/components/gear/index]] | 装备 | |"))
        self.write("reference/components/tools/index.md", index_text("工具", "| [[reference/components/uses]] | | active |"))
        rows = []
        for i in range(80):
            name = f"gear{i}"
            self.write(f"reference/components/gear/{name}.md", page_text(name, "装备回调", "装备速度"))
            rows.append(f"| [[reference/components/gear/{name}]] | 装备 | active |")
        self.write("reference/components/gear/index.md", index_text("装备", "\n".join(rows)))
        data = self.build()
        result = query.search(data, ["uses"])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(data["navigation"]["registrations"]["reference/components/uses.md"], ["reference/components/tools/index.md"])
        self.assertLess(len(wiki.encode(result)), 2048)

    def test_updater_is_reproducible_and_failure_preserves_existing_cache(self):
        cache = self.root / "cache/index.json"
        command = [sys.executable, "-X", "utf8", str(SCRIPTS / "tools/wiki/update_index.py"),
                   "--wiki-root", str(self.wiki), "--format", str(FORMAT), "--output", str(cache)]
        before = wiki.inventory(self.wiki)
        for _ in range(2):
            run = subprocess.run(command, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            raw = cache.read_bytes()
            if _ == 0:
                baseline = raw
            self.assertEqual(raw, baseline)
        self.assertEqual(wiki.inventory(self.wiki), before)
        self.write("reference/components/index.md", index_text("Missing registration"))
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(cache.read_bytes(), baseline)


if __name__ == "__main__":
    unittest.main()
