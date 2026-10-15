# 首个 facts 输出与契约检视

日期：2026-10-10；生产者 `fullmoon-dst 0.2.0`，Full Moon `3.0.0 / lua51`，契约 `1.0.0`，源码 Steam buildid `25643519`。本页记录本轮交付与检视，不进入默认知识查询。规则见 [输出契约](../../../.claude/references/output-format.md)，后续验收见 [PLAN](../../../PLAN.md)。

这是 0.2.0 的历史阶段结果；当前 0.3.0 已扩展字段／属性／别名／guards，并补全当时延后的注释，见 [第二层检视](stage2.md)。复核旧产物时 `verify_extraction.py` 加 `--stage 1`，当前命令默认比较第二层；以下历史数字和限制不重写成新结果。

## 已跑通的范围

Rust 提取器读取原字节，拒绝恢复 AST，输出声明、显式参数、词法作用域、定义区间及部分 trivia 注释；识别已知内联构造器的 `Class` 调用。直接函数赋值保留定义，实例回调不冒充类方法；字段、属性回调、方法别名、调用、条件及引用解析尚未实现，成功结果统一为 `partial`。

`health.lua` 输出 58 个符号、108 个原字节锚点、28 条注释；另外 20 条条件／循环区域内注释逐条提供诊断锚点，暂不填入缺少 guards 的 comment 记录。抽查 `Health`、构造器、`onpercent`、`SetVal`、`DoDelta` 及实例回调，与源码声明和区间一致。`DoDelta` 的显式参数为 `amount, overtime, cause, ignore_invincible, afflicter, ignore_absorb`，不补造隐式 `self`。[raw/current/scripts/components/health.lua:3] [raw/current/scripts/components/health.lua:62] [raw/current/scripts/components/health.lua:269] [raw/current/scripts/components/health.lua:565] [raw/current/scripts/components/health.lua:613]

产物在 Git 忽略的 `scripts/output/w03-stage1-final-dst/`，其中 health facts 位于 `facts/components/health.lua.json`。5 个独立样本选择比较 19/51 项，8 个真实试点选择比较 28/65 项，保留全部禁止误报检查；合计 47/116 项。原人工基准及其 `parser_executed:false` 来源记录未修改，不能把本次结果写成全套基准通过。

## 五项检视

| 检视 | 结果与处理 |
|---|---|
| 字段定义是否够用 | 当前声明、参数、位置和注释可以用 v1.0.0 表示。三个后续边界见下节；未增加未经版本迁移的字段 |
| 字节区间 | 所有成功输出锚点的原切片哈希、半开区间、行／字节列通过独立 Python 校验。LF 的 `component.lua`、`health.lua` 与 CRLF 的 `utf8-crlf.lua` 均检查；另用同一份含中文及尾注释的独立代码分别生成 LF／CRLF 验证 |
| trivia 与 WARNING | 文件头、行尾、长注释和 EOF 注释被保留，代码形状字符串不生成伪符号。CRLF 单行 comment token 包含结尾 CR，原文／哈希保留它。`WARNING` 保持 `kind:comment`、`style:line/block`，从原文筛选为警告候选，不增设类型或自动生成 pitfall |
| resolution 三态 | 格式可以表达单一目标、无法确定目标和多个候选；三种对象通过 Schema。实际 resolver 尚未实现，本轮 facts 不产生 resolution，不能声称三态已通过真实自动解析 |
| 失败与截断诊断 | 语法失败包含文件、行／字节列、byte 区间、错误信息及最多 160 字符的行上下文，anchors／symbols／records 为空。编码、字节码与访问错误单独分类。当前没有结果数量截断，`truncated:false`；解析后的主动遗漏用 `partial` 和定位诊断，不能伪称截断已验证 |

`health.lua` 没有 WARNING 文本；补用 `container.lua:1007` 验证真实警告。原文 `--V2C: ***WARNING*** checkallcontainers not implemented here` 提取为行注释，区间 `[30997,31057)`，归属 chunk。它位于函数前而非函数体内，当前不自动关联下一方法；结合后续源码才能说明适用范围。[raw/current/scripts/components/container.lua:1007] [raw/current/scripts/components/container.lua:1009]

三态的真实源码设计核对：`onpercent(self)` 在单元内有唯一可见局部定义，可成为 resolved 候选；`self.redirect(...)` 的值依赖运行赋值，适合 unresolved；条件下存在多个可能的定义且不能证明唯一到达目标时才用 ambiguous。不同作用域的同名函数不是自动歧义，重定义也不自动意味着运行目标不唯一。[raw/current/scripts/components/health.lua:3] [raw/current/scripts/components/health.lua:15] [raw/current/scripts/components/health.lua:623] [scripts/tests/fixtures/extraction/scopes.lua]

## 契约边界与下一层要求

1. **输入覆盖与 manifest**：v1.0.0 的文件 encoding 固定 UTF-8，不能把非 UTF-8／字节码硬填进清单。现用并列的 `coverage-report.json`（`report_version:1`，运维报告，不是新增契约 kind）记录全部选定路径、原字节哈希、输入类别及诊断；manifest 仅列 UTF-8 源文件，包括 UTF-8 语法失败文件。消费前同时读覆盖报告，不以 manifest.files 推断全部输入成功。这解决当前需求；未来需要单文件交换完整输入覆盖时再做契约版本迁移。
2. **符号声明条件**：records 有 guards，symbols 没有。实际回调可在 if 内定义，仅用定义锚点和 scope 不足以支持完整自动关系分析。目前诊断 `declaration-guards-deferred` 锚定包围条件／循环，成功状态仍 partial；扩展赋值／条件事实时验证能否用关联 assignment 及其 guards 完整表达。若独立声明仍无法表达且消费者确实需要结构化条件，再升级契约，不把 guards 塞进未定义字段。
3. **注释邻接与警告标签**：style 是语法样式，不是重要性。原文已足以筛 WARNING／DEPRECATED 候选；前置注释与方法的关联尚未证明，不能只凭临近绑定。先按锚点回读，不为标签扩字段；实际生成页需要可靠关联时再设计。无包围 if／loop 的 comment 记录也不等于运行必达，早退续行条件尚未提取。

health 的排版 JSON 为约 91 KiB，属于内部缓存；定义 anchors 和全部 comments 的总量不适合默认送给 LLM。后续源码查询在工具内部筛符号，只返回所选参数和定位，再读必要原代码；本轮没有测量 token 收益。

下一层实现字段、属性回调、赋值／别名和 guards，优先补全条件内注释。随后实现调用及 resolution，并用唯一局部、动态成员、条件多候选、词法遮蔽和跨文件缺口验证三态。不需要增加 codegraph。未来实现候选预算时，截断诊断需说明选择／限制、已返回数量、遗漏范围及继续读取入口；本轮不能验收不存在的截断分支。

## 复现

构建环境见 [ENVIRONMENT](../../../.claude/references/environment.md)。从仓库根执行，输出目录必须为空；重复复现选择新目录，保留旧产物及其覆盖报告。

以下命令路径已同步工具箱布局，历史版本、验收数字与结论保留。

```powershell
cargo build --locked --manifest-path scripts/fullmoon-dst/Cargo.toml
& .\.venv\Scripts\python.exe scripts/tools/source/parse_scripts.py components/health.lua --output scripts/output/health-review-new
& .\.venv\Scripts\python.exe scripts/tools/source/parse_scripts.py --catalog scripts/tests/fixtures/baselines/fixtures.json --output scripts/output/fixtures-review-new
& .\.venv\Scripts\python.exe scripts/tools/verify/verify_extraction.py scripts/tests/fixtures/baselines/fixtures.json --facts-root scripts/output/fixtures-review-new/facts
& .\.venv\Scripts\python.exe scripts/tools/source/parse_scripts.py --catalog scripts/tests/fixtures/baselines/pilots.json --output scripts/output/pilots-review-new
& .\.venv\Scripts\python.exe scripts/tools/verify/verify_extraction.py scripts/tests/fixtures/baselines/pilots.json --facts-root scripts/output/pilots-review-new/facts
& .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests/python -p test_extraction.py
```

故意语法错误样本使包装退出 1，这是该输入的明确失败；投影比较另行检查失败诊断和空输出并通过。包装访问／进程／配置错误退出 2。程序未执行游戏 Lua、LuaLS、语义推断、类型合并或 Wiki 生成；没有全快照 facts 提取结果。
