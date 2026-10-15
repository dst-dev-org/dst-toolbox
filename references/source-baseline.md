# 源码哈希基线工具

本文件维护 `validate_source_hashes.py` 的参数、输出、缓存与写入行为。是否沿用／刷新证据由调用方知识 Skill 决定，普通查询不自动调用。K 为明确知识根；以下命令从工具箱根执行，跨工作目录用脚本绝对路径。

## 路径与范围

`validate_source_hashes.py` 仅用标准库，将页面 `sources` 的原始／规范化 sha256 保存在 `K/wiki/source-baseline.json`；范围为根索引、`cookbook/` 和 `reference/` 下的 Markdown，归档页不比较。默认源码根为 `K/raw/current/scripts`，可用 `--source-root` 指定历史快照；`--config` 可指定用户配置文件。页面参数相对 Wiki 根，或使用绝对路径。

## check

```powershell
python scripts/tools/verify/validate_source_hashes.py check --knowledge-root "<K>" --fresh-hours 0 "reference/components/health.md"
```

可传多页；省略页参数时才检查默认全库范围。所选页检查不读写全库检查缓存；全库调用才尝试缓存，且只有完整、干净结果才回写 output。`--fresh-hours 0` 跳过缓存；源码历史快照用 `--source-root`，不从页面版本自动定位旧输入。

`check` 对受管文件只读，缓存在 `K/output/source-baseline-cache.json`。24 小时内可复用干净结果，条件是源码根、BUILD、检查器规则版本、源码路径／大小／mtime 指纹、知识页集合／字节和清单内容一致；清单损坏禁止命中缓存，缓存损坏退回实检。版本维护用 `--fresh-hours 0`。源码指纹不是逐字节证明，同大小且保留 mtime 的替换需强制全检。引用路径按快照大小写精确匹配，宽容文件系统上的大小写漂移单列为 `case_mismatch`，不静默解析到另一文件。输出区分真变化、源码删除、行尾差异、大小写不符、页 sources 变更、未登记及陈旧条目，并附完整受影响页队列（每页各类计数，不受 `--max-items` 限制）；其余详情受 `--max-items` 限制，总计保留。

报告的 `counts` 完整，`changed`、`line_ending_only`、`case_mismatch`、`sources_changed`、`unrecorded_pages` 等详情各受 `--max-items` 限制（默认 50，1～1000）；所检范围的 `affected_pages` 完整，不受该上限影响。它只是文件级哈希漂移清单，不是全部版本维护候选。未登记页即使未使退出码失败，也仍是覆盖缺口；`line_ending_only` 不代表行为变化。

规范化仅移除 UTF-8 文件头 BOM、将 CRLF／CR 换为 LF 并忽略末尾换行数量，不忽略代码、缩进或注释变化；原始哈希与规范化哈希分别保留。

## record

```powershell
python scripts/tools/verify/validate_source_hashes.py record --knowledge-root "<K>" --write "reference/components/health.md"
```

`record` 默认 dry-run，传页只更新已复核页面；选中的归档页移除其基线，其他条目保持原样。缺源码或引用大小写与快照不符的页整页跳过并保留旧基线；成功记录时清除遗留 `source_hashes` 块。格式错误阻止全部写入；损坏清单禁止局部刷新，只能先修复或显式不传页面重建全量。全量重建会覆盖未复核页基线，不能用于单页收尾。游戏源码与页面结论不被工具修改。

记录以锁和原子写入保护共享清单；调用方仍须避免对同一页面并发改写。输出关注 `counts.recorded/refreshed/already_recorded`、`removed_archived`、跳过页及异常，不把未刷新页误称为已核验。实际是否刷新、批次时机与哪些结论已核验不由本工具裁决。

## 退出与边界

退出 0 表示未发现所检已登记依据漂移或格式问题；未登记页仍须单独报告覆盖缺口，不能算已核验。退出 1 表示漂移、删除、大小写不符、sources 变更、陈旧条目或格式／清单错误，退出 2 为参数／运行失败。文件哈希不证明结论、依赖完整性或游戏运行效果。

`passed`／退出码只对应本次所检范围；参数／运行失败不当作干净结果。工具不改变页面技术结论、dst_build 或游戏运行验证等级；未检查范围也在报告 `not_checked/parser_limits` 中说明。
