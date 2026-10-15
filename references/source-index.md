# 源码索引生成与维护

日期：2026-10-10。本页是源码索引的工程参考，仅生成、修复或开发索引时读取，介绍 [source_index.py](../scripts/tools/source/source_index.py) 的构建、存储和有效性检查；精选 Wiki／需求检索属于 W05。日常使用见 所用知识库 Skill 的 `references/query/query-source.md`（源码查询，按实际安装位置读取）。facts 遵循 [输出契约](output-format.md)，完整 AST 和缓存不作为 LLM 默认输入。

## 生成

先构建 Rust 提取器，再生成一个新的快照目录。现有目录不能覆盖；选择 `.lua`，`.po` 主动排除。所有输出保持 Git 忽略。

```powershell
cargo build --locked --release --manifest-path scripts/fullmoon-dst/Cargo.toml
python scripts/tools/source/parse_scripts.py --knowledge-root "<K>" --all --binary scripts/fullmoon-dst/target/release/fullmoon-dst.exe --output "<K>/output/source-new"
python scripts/tools/source/source_index.py build --snapshot-root "<K>/output/source-new" --source-root "<K>/raw/current/scripts"
```

`--all` 显式选择来源根下全部 `.lua`；不传时仍为显式路径或 catalog。自定义根须同时提供 `--source-root` 与提取的 `--version`；查询／建索引也传同一 `--source-root`。当前游戏快照的两项格式缺口使提取退出 1，但仍生成完整报告和 failed 空事实；工具错误退出 2。建索引不得把错误输入当作定义不存在。

查询类别、筛选与预算参数只在 所用知识库 Skill 的 `references/query/query-source.md`（查询说明，按实际安装位置读取） 维护；验证新缓存时将其中 `--snapshot-root` 替换为本次生成目录。替代旧缓存前先验证查询、覆盖报告与基准，再按 [清理规则](project-maintenance.md#生成物清理) 移除被替代的生成物。

## 轻量存储与有效性

`source-index/index.json` 保存版本、覆盖、输入哈希、计数及分片描述；`shards/<category>/<sha256(key)前两位>.json` 按类别和哈希前缀分片，内部以精确 key 存定义或引用；最多 6×256 个分片，避免每个符号一文件。工具内部读取索引和选中分片，LLM 只接收限量查询结果；无 SQLite、图服务、向量库或新依赖。

建索引逐文件核对来源／facts／报告、字节半开区间、行字节列、哈希、符号 owner、record／guard／resolution 引用和覆盖计数。索引只从当前生成层读取，不写 raw、fork reviews、注解或 Wiki 技术页。

查询重新检查 Steam BUILD.txt、来源字节哈希和 manifest／报告，完整扫描还检查文件集合；任何变化返回 stale 并停止返回候选。选中分片和关联 facts 也校验固定哈希，损坏时报错。该检查用于拒绝失效证据；自动增量迁移、影响分析与 review 状态更新仍属 W06。没有可靠并发快照锁，查询期间文件发生变化时应重新准备／提取；索引不替代实际源码复查。

语法关系不等于运行调用图：局部函数、已知 Class／实例方法有有限 resolved／ambiguous，外部、动态、覆写目标保持 unresolved；成员声明之后的 self 方法链接使用同类最终保守绑定。组件 API 名称按冒号调用形状识别，不声称对象类型已经验证；replica 不计为 components。直接 component slot 写入有诊断，不猜测 add／remove 操作。参数化 Prefab 不跨函数传播名字，也不把 MakePlacer 等普通调用自动猜成注册。

## 验证与范围

独立索引测试覆盖定义重名、筛选、精确 ID、目标反查、组件／事件、动态名称、无命中、结果预算、源码／文件集合／manifest／分片变更及生成边界。真实源码检视与全快照结果见 [提取与索引验收](../docs/reports/w03/acceptance.md)。输出字节预算不是 token 测量；实际重复查询收益在 W05 验证。
