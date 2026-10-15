# 源码锚点迁移预览

`scripts/tools/maintenance/plan_source_link_updates.py` 是版本修补的只读定位工具，只需 Python 标准库。它不判断 DST 行为、不批准页面升版，也不写页面、源码、基线或缓存；版本维护的采用条件由知识 Skill 维护。

## 调用

```powershell
python scripts/tools/maintenance/plan_source_link_updates.py --wiki-root "<K>/wiki" --old-source-root "<旧快照scripts绝对路径>" --new-source-root "<新快照scripts绝对路径>" "reference/components/example.md"
```

三个根必须是明确的绝对目录，新源码根必须在知识根 raw/ 内；不从工作目录、工具箱邻仓或 BUILD 猜路径。页面必须显式选择，可传多页、Wiki 根相对路径或绝对路径；不默认扫描全库。调用方确认旧快照对应页面原核验依据，工具不读取／改写源码基线来替代该判断。

默认输出 JSON，不写文件。按需加 `--include-patch`，将输出的 `patch` 交给宿主允许的文本补丁工具；不要把 JSON 本身当补丁执行。补丁文件名相对报告的 `patch_root`（知识根，即 wiki-root 的父目录），应用时以该目录为工作目录；要求绝对路径的宿主可据此显式解析，不能按工具箱目录猜基准。补丁只改行号片段，应用后仍执行页面／源码引用检查；输入或规划工具更新后重新生成预览。

文本补丁目前仅支持无 BOM、LF 行尾且文件末尾有换行的页面。CRLF／CR 页仍提供行号建议，显式请求补丁时返回 `patch-line-endings` review；BOM 或缺末尾换行返回 `patch-page-format` review，不输出该页补丁。此时采用能保持原字节格式的宿主编辑，不自动归一化整页；这是补丁传输限制，不要求重新审阅源码逻辑。

## 机械证据与停止条件

- 同一文件对在单次调用内只读取／匹配一次；UTF-8 BOM、LF／CRLF 等按物理文本行比较，保留真实行号，不忽略缩进、注释或代码差异。
- 引用旧区间须合法且完整位于一个相同代码块中，区间外前后均须留有相同行，并至少有一行非空、非结构的代码上下文；行注释、Lua 长块注释及字符串正文不作有效代码，字符串内的注释标记不启动注释状态。扩展上下文在旧新两侧均唯一才提议迁移。匹配块恰好覆盖引用区间、上下文不足或只剩 end 等结构行时转 review；代码匹配仍不证明函数身份、代码移动语义或外部依赖未变。
- 区间内有改动、跨差异块、重复上下文，或变化文件中的旧锚点为空／结构行时转 review，不按行数偏移猜测。区间终点保留正常 end，不人为裁掉代码。来源缺失／大小写不符及非法路径明确报告；旧依据缺失不能自动迁移。
- 只处理链接实际落在所选新源码根的引用；其他 raw 快照的链接保留，计入 skipped_other_snapshot，不重定向到 current，也不检查其有效性。根外／raw 外来源拒绝规划。
- 解析复用 `validate_source_links.py` 的行内 Markdown 子集与掩码，保留页面物理行和匹配位置；不覆盖引用式／多行／嵌套链接、裸 file:line 或 frontmatter sources。仅有文件链接没有行号，不产生迁移补丁。

## 输出与使用边界

`counts` 和逐页计数完整，`proposals`／`issues` 默认各最多 50 项；`--max-items` 可设 1～1000，省略数见 `proposals_omitted`／`issues_omitted`。只取命中项，不必把全部预览加载进 AI 上下文；显式请求的 patch 包含所有支持格式页面的确定迁移，不受详情限额影响，格式受限页的建议仍保留在 proposals。

`input_fingerprint` 绑定本次读取的页面与旧新来源字节；逐页 sha256 辅助识别并发变更，不是语义验收。`mechanical_passed` 只表示没有待判断的机械问题；同一页可以同时有可迁移引用和 review，补丁仅含前者。退出码：0＝无机械待判断项，1＝有 review／error，2＝参数／运行失败。

未覆盖来源、未声明依赖、更新条目的语义充分性和游戏运行均不在本工具范围。它不能自动修改 dst_build／validation、执行 record 或把知识页标为已核验；不引入 AST、LuaLS 或 Markdown 全解析依赖。

## 回归

```powershell
python -B -m unittest discover -s scripts/tests/python -p test_source_link_updates.py -v
```

测试使用自动清理的临时输入，覆盖相同区间、内部变化、重复上下文、编码换行、边界／大小写、代码与注释排除、有限输出、可审阅补丁及 CLI 只读性；不需要游戏安装、Skill 或 PyYAML。

可选 `DST_TEST_CODEX_BINARY` 指定已有本机 Codex 原生可执行文件，额外调用其本地文本补丁器，在临时知识根实际应用 LF 补丁并逐字节核对；未设置则明确跳过该项。它不是迁移工具的运行依赖，不启动模型任务或访问真实知识页。CRLF 页测试采用“拒绝补丁、字节不变”路径。

验收记录分别列通过／跳过／失败；unittest 的 Ran 包含 skipped，不能把总数直接写为通过数。实际补丁应用的结论须附已设置上述变量的运行环境，默认命令不执行该可选项。若宿主 sandbox 的默认临时目录 ACL 拒绝创建测试输入，先准备宿主允许的可写绝对目录，并在启动 Python 前设置 `TMPDIR` 指向它；不放宽目录 ACL 或把建输入失败算作断言通过。

```powershell
$env:TMPDIR = "<已存在且宿主允许写入的临时基目录>" # 仅默认临时目录受限时设置
$env:DST_TEST_CODEX_BINARY = "<已有Codex原生可执行文件绝对路径>" # 仅实际补丁集成测试设置
python -B -m unittest discover -s scripts/tests/python -p "test_source_link*.py" -v
```
