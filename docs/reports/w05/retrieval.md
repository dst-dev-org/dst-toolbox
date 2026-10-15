# 知识检索与章节读取首轮检视

日期：2026-10-11。W05 进行中，本报告记录检索基础能力；cookbook、暖石组合实现和真实任务的三路成本比较尚未完成。没有游戏运行或精确 token 测量。

## 交付与取舍

- 清理已有内容目录 `components / prefabs / stategraphs` 的三个 `.gitkeep`，保留空 `api/engine` 占位。
- [update_index.py](../../../scripts/tools/wiki/update_index.py) 先检查知识页、标签／大小、人工导航及 Top 30，再原子生成独立 version 1 缓存，失败保留旧输出，有效输入重复生成原字节一致。人工 Markdown 保留分类、主题摘要和 Top 30 维护权；早期“生成导航”调整为“检查人工导航＋生成机器缓存”，避免程序重排覆盖人工需求组织。
- [query_wiki.py](../../../scripts/tools/wiki/query_wiki.py) 在工具内过滤路径／名称、明确标识符、摘要／别名、场景标题／条件；多个子目标与 cookbook／机制候选共享默认 5 项／16,000 UTF-8 输出字节。词汇命中不证明适用，返回章节入口后仍读证据。缓存不输出全文代码／AST；JSON 完整性与页面／导航增删改检查，stale 拒用旧候选。
- read 不依赖缓存，实际返回当前文件的章节行区间、元数据、父章节前提、快速判断／适用条件和验证记录／边界。同页目标合并去重，超预算整项省略并报告截断，不切代码；按需另取陷阱和接口，已有页修改继续先读全文。
- [validate_page.py](../../../scripts/tools/verify/validate_page.py) 保留单页草稿模式，默认全库检查标签、大小／链接／锚点、叶级表格登记、父入口／循环与 Top 30 数量／去重／active。跨主题正文链接不代替登记，归档页可移出正常导航。

工具归 `scripts/tools/wiki/`，复用原页面校验与既有 PyYAML，没有新依赖、codegraph、数据库或服务。可显式指定知识／源码根和缓存路径；其余工具的独立仓分发仍是后续计划。基础 Markdown 查询、案例／陷阱维护继续不要求 Python。使用说明按需读 [Wiki 查询](../../../.claude/skills/dst-wiki/references/search-wiki.md)，AGENTS／CLAUDE／SKILL 入口未增负担。

## 验证

新增 25 项独立测试，完整 Python 回归共 123 项通过。覆盖名称／完整标识符／需求／类型与路径过滤、cookbook 和机制的共享预算、同名、归档／无命中、已知版本／未知／不匹配、缓存新增／删除／内容与导航变化、缓存改坏、登记遗漏／重复／父入口／循环、Top 30 数量／状态、未知标签／超限页、81 页合成大分类、更新失败保留缓存，以及 LF／CRLF、嵌套／重复标题、长围栏代码、父前提、同页去重和完整输出预算。

当前真实库包含 2 份组件页、5 份导航，7 份页面的结构／标签／链接／大小、登记与 Top 30 检查通过。`finiteuses` 直查快速判断，`SetMaxUses` 定位关键接口，“修改已有手杖”定位接入案例；“物品栏发光”本轮返回检索缺口。测试发现并修复 ASCII 部分匹配导致 `uses` 命中 `SetUses` 和一般“修改已有”措辞误召回其他对象的问题。词汇排序仍非语义检索，实际措辞不足时补别名或定向查 Markdown／源码。

可复现命令（从知识库根）：

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s scripts/tests/python -p test_wiki.py
& .\.venv\Scripts\python.exe -X utf8 scripts/tools/verify/validate_page.py --source-root raw/current/scripts
& .\.venv\Scripts\python.exe -X utf8 scripts/tools/wiki/update_index.py --source-root raw/current/scripts
& .\.venv\Scripts\python.exe -X utf8 scripts/tools/wiki/query_wiki.py --build steam-buildid:25643519 search SetMaxUses "修改已有手杖" "物品栏发光"
& .\.venv\Scripts\python.exe -X utf8 scripts/tools/wiki/query_wiki.py read "components/finiteuses#典型接入"
```

## 局部读取量

仅量取固定库的工具输出及所选原文，不是完整任务成本比较。整份 JSON 含元数据、状态、转义及结尾换行；所选正文包含案例、快速判断和验证边界，原文件字节保留 CRLF。下表是 UTF-8 字节代理，不能换算成固定 token 数。

| 查询／读取 | 原页字节 | 所选正文 | 整份工具输出 |
|---|---:|---:|---:|
| finiteuses 名称查询 | — | — | 1,613 |
| SetMaxUses 标识符查询 | — | — | 1,778 |
| 工具耐久＋装备加速 | — | — | 3,238 |
| 手杖修改＋物品栏发光缺口 | — | — | 2,258 |
| finiteuses 典型接入 | 8,856 | 3,099 | 4,428 |
| equippable 典型接入 | 10,566 | 4,386 | 5,941 |
| 根“按需求进入”章节 | 967 | 341 | 1,033 |

局部章节工具确实减少这两份长页的返回量，但短根导航的 JSON 输出比原 Markdown 更大；仍按任务选直接读取、rg 或可选工具，不强制所有读取经过封装。查询加章节读取有两次输出，上表不能把章节单项差额当作整个任务收益；必要陷阱／接口追加读取也要计入。

实际输出与测量在本地忽略的 `scripts/output/w05-retrieval-20261011/`，复现脚本在本轮 `scripts/output/backups/w05-retrieval-20261011/measure_retrieval.py`。这些产物不作为普通查询前提，不随克隆分发；可用上述命令重新量取。

## 边界与下一步

缓存检查证明当前 Wiki 与构建输入一致；`--build` 仅比较用户已核对的版本标识与页版本，相同不证明源码证据未变。源码区间失效／影响分析留 W06。标签／索引通过、关键词命中或 LuaLS 通过均不证明行为或游戏运行；没有自动整页生成／更新。

第一份 `new-item` 骨架随后核验并交付，再与斧头／手杖已有机制修改任务验证组装上下文和源码／仅机制／骨架＋机制路径。暖石恒温、持有者灯光／精神、范围和共用清理仍需具体内容建设与运行缺口记录；真实任务扩展、Top 30 导航成本、准确 token 或明确代理测量继续按 [PLAN](../../../PLAN.md#w05真实方案与检索闭环) 推进。
