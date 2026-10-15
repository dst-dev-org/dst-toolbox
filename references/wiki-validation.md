# Wiki 校验工具

工具参数、输出与检查范围在本文件维护；按任务只读对应小节。K＝明确知识根，S＝所安装知识 Skill；命令从工具箱根执行，跨工作目录用脚本绝对路径。Python／依赖基线见[环境](environment.md)，不因校验任务自动安装环境。

## 页面与导航

`validate_page.py` 需要 Python／PyYAML，只读检查页面元数据、标签、大小、本地链接与 Markdown 标题锚点。格式／标签／大小契约唯一来源是 `S/references/maintain/write-format.md`，通过 `--format` 指定，不在工具箱复制。

```powershell
python scripts/tools/verify/validate_page.py --wiki-root "<K>/wiki" --source-root "<本页所用scripts根>" --format "<S>/references/maintain/write-format.md" "<页面绝对路径>"
```

位置参数可传多个页面，均为绝对路径。指定页时追加 `--check-indexes` 才检查全库导航登记／父入口／Top 30；省略页面参数时检查根索引、reference 根索引及支持类型目录下的知识页／索引，同时检查导航。排除日志和旧分类（sessions／decisions／templates／patterns／pitfalls），不扫描工程目录。

`--source-root` 核对 frontmatter sources 的文件存在性；使用页面所用快照，不同快照分批，不一律绑定 current。普通链接按实际目标检查；远程可访问性、Lua 行号、章节职责、技术语义与游戏效果不在本工具范围，不替代重组前入链搜索。

reference 知识页的可选 `size_class` 按格式文件中的分档表选择预算；省略为 `standard`，非法值或在索引／cookbook 中使用报 `metadata` 问题。`pages[].size` 给实际行数／UTF-8 字节及上限，源码知识页另含 `size_class`。只有旧式基础表的格式文件仍支持标准档，显式非默认档报未定义，不能静默回退；分档表存在但缺类／重复／预算不一致时配置报错。索引构建复用相同检查，分类是否符合页面实际复杂度仍由内容审阅判断；阈值只在 Skill 格式文件维护。

输出 `pages[].issues`／`pages[].passed`、可选 `navigation` 与总 `passed`。`link/link-anchor` 对应缺失目标／标题锚点，其他问题按各自代码定位。退出 0＝所选检查通过，1＝有页面或导航问题，2＝参数／运行失败；指定页且未要求导航时，不能把结果称为全库导航通过。本工具用于共享 Wiki，不用于 Skill 包文档或任意模组 Wiki。

## 覆盖自查

`verify_page_coverage.py` 只读检查覆盖与管理噪声；页面范围、frontmatter、导航登记与格式预算复用 `validate_page.py`，不复制解析，也不另立预算。

```powershell
python scripts/tools/verify/verify_page_coverage.py --wiki-root "<K>/wiki" --format "<S>/references/maintain/write-format.md" [--registrations <清单.json>] [--fail-on error|warning|info] [--severity error|warning|info ...] [--code <code> ...] [--page <前缀> ...] [--changed <变更清单.txt>] [--scope prefab|all] [--missing-scope prefab|all] [--strict] [--json] [--limit 500]
```

默认 `--scope prefab` 只报 Prefab 页问题：索引提醒、非 Prefab 返回链／解析失败、共享短语别名都不打印；`--scope all` 才恢复全库检查。别名归属（A）：有清单时，confirmed 注册名被多个正常维护（非 archived）Prefab 页 aliases 占用报 error；confirmed 名称按精确 aliases 匹配，大小写变体只出 info、不作为归属；无清单只报疑似冲突，`^[a-z][a-z0-9_]{2,}$` 形态 warning；大写／短语／函数名只作 info，且仅在 `--scope all` 输出。candidate／unresolved 不参与冲突判定。返回链（B）：正文行首 `返回 [[...]]`（可带 `-/*/+/>`）至少一个指向 `check_indexes` 的唯一登记叶索引才通过；全部指向他处 warning；HTML 注释按空白屏蔽、不提供返回链；无返回链（`backlink-missing`）、有返回行但解析不出 `[[...]]`（`backlink-unrecognized`）、叶索引无法唯一确定（`backlink-unresolved`）均为 info，不算通过；`unresolved` 只计后两类与页面解析失败。默认只检查 Prefab 页；`--scope all` 才看其他知识页，其中无返回链仍由 `--missing-scope`（默认 Prefab）限制。索引预算（C）：仅 `--scope all` 运行；`--rows-warn`（表格数据行，默认 60）、`--bytes-warn`（UTF-8 字节，默认 12288）只是提醒，硬上限仍取格式表（物理行／KiB），消息同时标出两种口径。覆盖缺口（D）：只统计非 archived 的 Prefab 页的精确页面名／别名；清单 confirmed 在页面文件名或 aliases 均无命中 warning（组件页／归档页不算覆盖，大小写变体不算覆盖并在消息提示），`--strict` 升 error。

清单 JSON 可选：顶层数组，或对象下 `entries`／`registrations`／`prefabs`／`items`；条目为字符串（视为 unresolved）或带 `name|id|prefab|registration` 与 `status`（confirmed／candidate／unresolved，缺省 unresolved）的对象；`snapshot` 优先于 `raw/current/BUILD.txt`。未传清单时 `checks.alias_ownership=suspected-only`、`coverage_gaps=skipped`，此时 `error 0` 不能证明 confirmed 注册名没有归属冲突；D 也不运行。

输出 `snapshot`／`scope`／`checks`／`counts`／`unresolved`／`hits_total`／`shown`／`truncated`／`omitted`／`findings`／`groups`／`passed`／`exit_reason`；`--json` 输出整份报告，默认文本摘要。默认只把 error／warning 逐条列入 `findings`，info 只进 `groups`；`--severity info` 展开 info 详情，`--code`／`--page` 过滤详情（`--code` 未配 `--severity` 时自动含全部严重度），`--changed` 把详情限定在本轮变更页（`findings[].pages` 列出全部涉及页，冲突含所有归属页，任一页命中即保留）。`--limit` 只截断详情；`counts`／`groups`／`hits_total` 始终基于全量扫描。`checks.page_scope` 标明当前口径，默认 `indexes=skipped`。`groups` 按登记叶索引（返回链不一致）、目录（缺失／未识别）或别名／注册名汇总，warning 组附完整页面，info 组附前 20 页。

退出 0＝没有达到 `--fail-on`（默认 error）的发现，1＝有阻塞发现，2＝输入／执行失败；`passed` 只表示“无阻塞发现”，不表示全部内容已核验（看 `checks`／`unresolved`／`omitted`）。`--strict` 只把 D 缺口升为 error。页面范围与 `validate_page.py` 相同（不含 updates、日志与旧分类）；不解析 `.po`、不判断页面结论或源码覆盖、不比对历史快照。

2026-11-04 全库基线（无清单，默认 `--scope prefab --fail-on error`）：修复 54 个变更页、8 个新页补链、105 个历史页后，1096 页默认 **0 发现**（返回链不一致 0、Prefab 缺失 0；索引提醒与短语别名被 scope 跳过），`passed true`、退出 0、`exit_reason clean`。`--scope all` 时为 0 error／4 warning／21 info（25 条、25 组，索引提醒均未超 240 物理行／24 KiB）。带 FX 清单（270 confirmed）时默认 96 条 `coverage-gap` warning（174 已覆盖），`--scope all` 才加 4 条索引提醒；`--missing-scope all` 另列 823 条非 Prefab 历史页（component 812、cookbook 5、api 3、mechanism 3），不计入 `unresolved`。105 页是一次性例外，后续仍按“触碰时再改”，先用 `--changed <清单>` 看变更页。回归：`python -B -m unittest discover -s scripts/tests/python -p test_page_coverage.py -v`（24 项）。

## Prefab 译名定位

`inspect_prefab_names.py` 可从指定快照的 `languages/chinese_s.po`、Wiki 的两列名称 CSV 或调用方提供的实显名称定位候选。复用页面 frontmatter 解析，需 Python／PyYAML。

```powershell
python scripts/tools/verify/inspect_prefab_names.py --source-root "<本页所用scripts根>" "<页面绝对路径>"
python scripts/tools/verify/inspect_prefab_names.py --source-root "<本页所用scripts根>" --key STRINGS.NAMES.MOON_ALTAR_ROCK_GLASS
python scripts/tools/verify/inspect_prefab_names.py --name-catalog "<K>/wiki/assets/prefab-names.csv" --key STRINGS.NAMES.BEEFALOWOOL
python scripts/tools/verify/inspect_prefab_names.py --display-name "<已核实的简中显示名>" "<页面绝对路径>"
python scripts/tools/verify/inspect_prefab_names.py --source-root "<scripts根>" --page-key "<页面A>" STRINGS.NAMES.MOON_ALTAR_ROCK_GLASS --page-name "<页面B>" "坎普斯" --output "<K>/output/prefab-names.json"
python scripts/tools/verify/inspect_prefab_names.py --reuse "<K>/output/prefab-names.json"
```

页名与形似注册名的英文 aliases 只生成 `STRINGS.NAMES.*` 候选。已从源码确认显示键时，用可重复的 `--key` 查精确上下文（也支持 `STRINGS.SKIN_NAMES.*`）；带 `--key` 时最多传一篇页面。工具列出英文、简中译文与 PO 物理行范围；标题、摘要按子串查，aliases 按整项查。候选译文未出现在标题和摘要时标记 `review_visible_name`，即使别名已收录也提醒核对玩家能否读懂主名称。

`--display-name` 可重复，需指定一篇页面，可省略 `--source-root` 直接比对。结果标 `provided-name`，名称证据由调用方提供。

`--name-catalog` 可单用或和 `--source-root` 合用，匹配同名 `STRINGS.NAMES.*` 键。CSV 候选标 `runtime-name-catalog`，同键同值时保留带行号的 PO 结果。CSV 版本看资产说明，动态显示名查实际路径。`--reuse` 可恢复路径并重新读取当前 CSV。

多页可直接列路径；需要指定证据时可重复传 `--page-key PAGE KEY` 或 `--page-name PAGE NAME`，同一批只读取一次 .po。可用 `--output` 将 JSON 报告保存到已存在的生成物目录，目标须是新文件。复审用 `--reuse` 恢复原批页面、绑定参数和已查键，再从现有 Markdown 重新比对。可追加页面路径只复审子集。复用会核对 .po 路径、大小、修改时间及快照 build（可读时），只接受此前已查过的键。快照变动或新增键时重新查询；手工提供名称的适用版本仍由调用方核对。

JSON 的 `missing_explicit_keys` 列出本次所选来源均未提供名称的显式键，`ambiguous_keys` 列出 PO 中同键的多条译文。推测键未命中时省略。PO 解析适用带单行 `msgctxt` 的单数条目，支持多行值，跳过空译文和 fuzzy 条目。退出 0 表示定位完成，2 表示输入或运行错误。实际显示名、正文首次介绍与索引措辞由复审者核对。

## 源码引用

```powershell
python scripts/tools/verify/validate_source_links.py --wiki-root "<K>/wiki" "<页面绝对路径>"
```

`validate_source_links.py` 只读检查根导航、`cookbook/` 和 `reference/` 中行内 Markdown 的本地 `.lua`／`.po` 链接，排除围栏代码、行内代码和 HTML 注释，保留原 Wiki 物理行号；不读日志、日志归档或工程目录；所选目录内的 archived 状态页仍检查。按链接实际路径读取 `raw/current` 或历史快照，不重定向源码版本；链接离开知识根报错，在知识根内但不在 `raw/` 下报 `source-outside-raw` 警告并继续检查。其他后缀不读取，计入 `counts.skipped_unsupported`；此数只含已识别的本地行内链接，不是所有被忽略的 Markdown 总数。

无行号时仅检查文件可读，`#L12`／`#L12-L20` 检查正向、非零、未越界；文件不可读、无效片段和区间报错。起始行为空报复查警告，Lua 起始行仅 `end`／`else` 等另报结构行警告；区间终点为空新增 `source-end-blank`，用 `anchor: start/end` 标明端点，单行不重复报，终点 `end`／`}` 不新增警告。脚本不自动移行，也不判断正文结论是否被源码支撑。

源码按字节读，优先 UTF-8（接受 BOM），失败回退 latin-1；`source_encodings` 按成功读取的文件列 `encoding`（utf-8／utf-8-sig／latin-1）、`fallback` 与引用出现次数 `references`。这些是 info，不计 warning 或 strict 失败，不能据回退编码认定文件损坏；明确二进制头或大量 NUL 则每文件报一次 `source-binary` warning。页面仍须 UTF-8。页面校验、链接检查、缓存切章及 read 共用 `wiki_text.physical_lines`，只按 CR／LF 分行，U+0085／U+2028 等保留在原行；read 保留原始换行字节。

输出 JSON 包含计数、问题详情、问题页汇总与检查背景（`current_snapshot_version`／`not_checked`／`parser_limits`）。`by_page` 按错误数、警告数排序，含该页全部 references／errors／warnings；默认 `--max-issues 50`（1～1000）同时限制详情和问题页数量，总计仍完整，省略分别用 `truncated`／`omitted`、`problem_pages`／`by_page_omitted` 表明。`--context 2`（0～5）控制端点上下文，长行标记裁剪。`current_snapshot_version` 记录 `raw/current/BUILD.txt` 路径、值与读取状态，只作复现背景；缺失／不可读不影响校验，不代表历史引用版本或匹配验证。位置参数为相对 `--wiki-root` 或绝对页面路径，例如 `reference/components/equippable.md`。退出码 0＝无错误（可有警告），1＝有错误或 `--strict` 下有警告，2＝参数／运行失败。

解析采用逐行 Markdown 子集：不覆盖远程／引用式链接、HTML 链接／autolink、多行／嵌套链接或 Windows 盘符绝对目标；缩进代码暂不区分，内部链接可能被检查，以免漏掉列表缩进的正常链接。报告 `not_checked`／`parser_limits` 明示范围，不提供无法准确统计的 ignored 总数。脚本不检查版本／哈希匹配、裸 `文件:行号` 或 frontmatter `sources`；后者仍由页面校验器检查，不替代语义审阅或游戏验证。

## Lua 示例

使用已存在的 Full Moon 探针读取完整 Lua 5.1 文件，不执行示例：

```powershell
& "<T>/scripts/fullmoon-dst/target/debug/examples/parser_probe.exe" --syntax-only "<临时完整示例.lua>"
```

采用实际已有 debug／release 路径，非 Windows 二进制无 .exe；不要为单例检查运行全快照 verify_parser.py 或构建工具链。按示例标注的文件边界分别另存临时文件，不拼补省略片段、不把多文件合成一个 Lua；结束后清理本次临时文件。

该调用只证明 Lua 5.1 语法是否可解析，不核验名称绑定、API、主客端边界或游戏效果；缺二进制时按调用方规则人工审阅并注明语法未测。提取器／方言兼容等工程复现另见[环境](environment.md#复现检查)。
