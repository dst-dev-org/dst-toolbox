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

## 源码引用

```powershell
python scripts/tools/verify/validate_source_links.py --wiki-root "<K>/wiki" "<页面绝对路径>"
```

`validate_source_links.py` 只读检查根导航、`cookbook/` 和 `reference/` 中行内 Markdown 的本地 `.lua` 链接，排除围栏代码、行内代码和 HTML 注释，保留原 Wiki 物理行号；不读日志、日志归档或工程目录；所选目录内的 archived 状态页仍检查。按链接实际路径读取 `raw/current` 或历史快照，不重定向源码版本；链接离开知识根报错，在知识根内但不在 `raw/` 下报 `source-outside-raw` 警告并继续检查。

无行号时仅检查文件可读，`#L12`／`#L12-L20` 检查正向、非零、未越界；文件不可读、无效片段和区间报错。起始行为空或仅 `end`／`else` 等报复查警告；区间终点为空新增 `source-end-blank`，用 `anchor: start/end` 标明端点，单行不重复报，终点 `end`／`}` 不新增警告。脚本不自动移行，也不判断正文结论是否被源码支撑。

输出 JSON 包含计数、问题详情、问题页汇总与检查背景（`current_snapshot_version`／`not_checked`／`parser_limits`）。`by_page` 按错误数、警告数排序，含该页全部 references／errors／warnings；默认 `--max-issues 50`（1～1000）同时限制详情和问题页数量，总计仍完整，省略分别用 `truncated`／`omitted`、`problem_pages`／`by_page_omitted` 表明。`--context 2`（0～5）控制端点上下文，长行标记裁剪。`current_snapshot_version` 记录 `raw/current/BUILD.txt` 路径、值与读取状态，只作复现背景；缺失／不可读不影响校验，不代表历史引用版本或匹配验证。位置参数为相对 `--wiki-root` 或绝对页面路径，例如 `reference/components/equippable.md`。退出码 0＝无错误（可有警告），1＝有错误或 `--strict` 下有警告，2＝参数／运行失败。

解析采用逐行 Markdown 子集：不覆盖远程／引用式链接、HTML 链接／autolink、多行／嵌套链接或 Windows 盘符绝对目标；缩进代码暂不区分，内部链接可能被检查，以免漏掉列表缩进的正常链接。报告 `not_checked`／`parser_limits` 明示范围，不提供无法准确统计的 ignored 总数。脚本不检查版本／哈希匹配、裸 `文件:行号` 或 frontmatter `sources`；后者仍由页面校验器检查，不替代语义审阅或游戏验证。

## Lua 示例

使用已存在的 Full Moon 探针读取完整 Lua 5.1 文件，不执行示例：

```powershell
& "<T>/scripts/fullmoon-dst/target/debug/examples/parser_probe.exe" --syntax-only "<临时完整示例.lua>"
```

采用实际已有 debug／release 路径，非 Windows 二进制无 .exe；不要为单例检查运行全快照 verify_parser.py 或构建工具链。按示例标注的文件边界分别另存临时文件，不拼补省略片段、不把多文件合成一个 Lua；结束后清理本次临时文件。

该调用只证明 Lua 5.1 语法是否可解析，不核验名称绑定、API、主客端边界或游戏效果；缺二进制时按调用方规则人工审阅并注明语法未测。提取器／方言兼容等工程复现另见[环境](environment.md#复现检查)。
