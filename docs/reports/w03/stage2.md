# 字段、属性回调、别名与条件提取

日期：2026-10-10。生产者 `fullmoon-dst 0.3.0`，契约继续为 `1.0.0`；Full Moon `3.0.0 / lua51` 与其他依赖不变。本页接续 [首层检视](stage1.md)，仅维护／回归时读取，实际进度见 [PLAN](../../../PLAN.md)。

这是 0.3.0 的历史结果；当前 0.4.0 已完成 W03 最小提取与索引，见 [验收记录](acceptance.md)。以下历史数字与 partial 说明保留，不替换为新结果。

## 已交付与验收

新增 positional assignment、实例字段写入、内联 Class 属性表、已知方法别名、显式 return、词法 guards 与完整 trivia 注释。成功结果仍为 `partial`：普通调用、事件、组件、Prefab 与跨文件引用尚未实现，也没有完整控制流或运行值推断。

原 W02 清单未修改。本轮投影比较覆盖全部 symbols 和 assignment / property_callback / method_alias / return / comment，独立样本 31/51 项、真实试点 41/65 项，合计 **72/116 项**通过；全部禁止误报要求保留。首层的 47 项包含在其中，不相加。`verify_extraction.py --stage 2` 为默认选择；`--stage 1` 可复核历史产物。

25 项真实 binary／包装测试通过（原 10 项适配扩展记录，加 15 项独立用例），覆盖三态、覆写、遮蔽、两个 Class 同时初始化、方法交换、条件／循环／早退、闭包边界、CRLF／中文以及主动遗漏诊断。原 5 项探针、12 项契约、8 项比较工具测试通过；这些检查不证明游戏运行语义。

## 表示与保守边界

| 信息 | 当前处理 |
|---|---|
| 赋值 | 每个有独立 RHS 的目标保留原表达式及 literal_kind；无独立 RHS、最后 call／vararg 的额外目标提供区间诊断，不造原文 `nil` 或臆造返回值 |
| 字段 | 只对已知 Class 构造器实例或冒号方法的实例绑定建立直接字段；遮蔽的 self、动态下标、深层目标不据形状猜成类字段。首次观察锚定字段，所有写入仍单独保留；不推断终生类型 |
| 属性回调 | 内联 Class 的 NameKey 属性表链接 field 和 callback；唯一可见函数 resolved，外部／动态／覆写值 unresolved，多个已知可选定义 ambiguous。动态属性表／键和无法判定的 Class 重载提供诊断 |
| 方法别名 | 已知函数／多个已知候选才建别名符号与记录；唯一目标复用显式参数及 calling，歧义目标不拼接参数。未知成员 RHS 保留 assignment 和诊断，不自动升级成方法 |
| 条件 | 保留 then / elseif / else；elseif 与 else 包含之前分支条件的否定线索。loop 为原条件或 for 头部，repeat.until 只描述循环区域，不表示首次执行的前置条件 |
| 早退 | 仅在同一块的单一无 else／elseif 条件体能确认 return 时记录 after-return；break 路径不成立。复杂分支续行、短路 RHS 与异常退出尚未建模 |
| 函数边界 | 闭包的定义／赋值条件属于外层执行上下文，闭包体从自己的条件开始，不继承定义时 if。条件声明以 assignment＋源码区间关联，symbols 本身没有 guards，consumer 不能只读符号判断必达 |

三态用于有限的词法／赋值形状解析，仍不是已证明的运行调用链。条件／闭包中写入外层值保留已知候选并诊断限制，遇到未知值就保持 unresolved；不同作用域同名不自动合并。多分支全部覆盖、跨文件、动态返回及副作用不做证明，不能以当前解析能力支持全局唯一目标结论。

本轮保持契约 v1.0.0，不新增 symbol.guards 或 comment WARNING 字段。`conditional-symbol` 仍给包围条件／循环的锚点；其 assignment、属性记录或原区间提供条件依据。WARNING 是 comment 原文候选，不自动生成 pitfall；函数前注释的语义关联仍需源码核验。动态属性／重载、隐式返回和短路等留在 partial 缺口，而非声称 complete。

## 真实源码复核

`health.lua` 提取出 96 个符号、325 个锚点，127 条 assignment、9 条 property_callback、20 条显式 return、48 条 comment。上轮 20 条条件内注释已经补齐，没有 `comment-guard-not-extracted`；死亡分支中的注释保留 `old_health > 0 and self.currenthealth <= 0 / then`。9 条属性映射均定位到同文件函数；实例回调继续保持词法所属函数而非类方法。[raw/current/scripts/components/health.lua:62] [raw/current/scripts/components/health.lua:105] [raw/current/scripts/components/health.lua:269] [raw/current/scripts/components/health.lua:583] [raw/current/scripts/components/health.lua:597]

finiteuses 的 total／current 写入和属性表关联、OnSave 条件 return，以及 container 的两个生命周期别名符合原基准；别名记录保留到 Close 定义的解析，不合并两种生命周期触发语义。[raw/current/scripts/components/finiteuses.lua:12] [raw/current/scripts/components/finiteuses.lua:19] [raw/current/scripts/components/finiteuses.lua:48] [raw/current/scripts/components/container.lua:1086] [raw/current/scripts/components/container.lua:1087]

已对 16 个选定 facts 和 2 份 manifest 检查 Schema、原字节半开区间／行字节列／哈希、owner／record／guard／resolution 引用及覆盖输入哈希；两项实际编码／字节码失败保持空事实。LF／CRLF 加中文条件和注释用独立输入验证；游戏文件未修改。输出在 `scripts/output/w03-stage2-verified-fixtures/` 与 `scripts/output/w03-stage2-verified-dst/`，均 Git 忽略。

health 排版 facts 约 296 KiB，比首层更大，是工具内部可重建缓存。后续查询必须内部筛选符号／记录，仅返回少量参数、条件及定位；不整份传给 LLM，不以产物大小宣称 token 收益已测量。

## 复现与下一步

先按 [ENVIRONMENT](../../../.claude/references/environment.md) 构建 binary；输出目录须为空。

以下命令路径已同步工具箱布局，历史版本、验收数字与结论保留。

```powershell
cargo build --locked --manifest-path scripts/fullmoon-dst/Cargo.toml
& .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests/python -p "test_extraction*.py"
& .\.venv\Scripts\python.exe scripts/tools/source/parse_scripts.py --catalog scripts/tests/fixtures/baselines/fixtures.json --output scripts/output/stage2-fixtures-new
& .\.venv\Scripts\python.exe scripts/tools/verify/verify_extraction.py scripts/tests/fixtures/baselines/fixtures.json --stage 2 --facts-root scripts/output/stage2-fixtures-new/facts
& .\.venv\Scripts\python.exe scripts/tools/source/parse_scripts.py --catalog scripts/tests/fixtures/baselines/pilots.json --output scripts/output/stage2-pilots-new
& .\.venv\Scripts\python.exe scripts/tools/verify/verify_extraction.py scripts/tests/fixtures/baselines/pilots.json --stage 2 --facts-root scripts/output/stage2-pilots-new/facts
```

独立错误样本导致包装退出 1，随后比较核验错误诊断和空事实；当前实际编码／字节码输入也退出 1。下一步实现 call、event、component、Prefab 等语法观察，复用现有 guards 和保守 resolution；之后构建有限结果的定义／反向引用查询索引。全 W02、全快照 facts、LuaLS 和游戏运行未验收。
