# 最小源码提取与关系索引验收

日期：2026-10-10；生产者 `fullmoon-dst 0.4.0`，契约 `1.0.0`，Full Moon `3.0.0 / lua51`，Rust `1.99.0 / x86_64-pc-windows-msvc`，源码 Steam buildid `25643519`。依赖、原 W02 清单、raw 与 fork pin 保留。本页接续 [第二层](stage2.md)，只在维护／回归时读取；用法见 [源码查询](../../../.claude/skills/dst-wiki/references/query-source.md)，进度见 [PLAN](../../../PLAN.md)。

## 交付范围

已提取声明、参数、作用域、字段／赋值、属性回调、方法别名、显式 return、trivia，以及普通 call、event emit／listen、component read／add／remove 与 Prefab 注册。函数链中的每次调用分别保留，包括嵌套调用、字符串／table 参数、括号函数和动态下标。调用参数不求值，监听来源保留在普通 call，不冒充 payload。

已知局部函数和 Class／实例成员提供有限三态解析；成员别名与字符串下标、字符串属性键可定位，唯一目标复用显式参数，未知不猜类型。Prefab 内联工厂可 resolved；外部名称、动态工厂或 shadowed Prefab 不猜测注册。常量字符串按 Lua 5.1 转义／长字符串规则识别，不能表示成非空 UTF-8 JSON 名称时保留原表达式与 null 字面名。

guards 覆盖 then／elseif／else、loops、可证明的早退续行以及 and／or 右值；闭包体不继承定义时条件。generic for 采用 iterator 表达式（符合原 W02），numeric for 保留头部。component 读取作为条件时锚点包括完整条件，实际 guards 按访问所在位置计算。Full Moon 方括号 index 的范围需显式补到关闭括号，真实 p[2] 调用已核对。

源码查询索引独立于 Wiki：精确名称／ID 查定义，按 callee／target／组件／事件／Prefab 查反向引用；简单 JSON 分片，无 codegraph 或服务。候选数、总字节、长表达式均有上限，覆盖、歧义、无命中、截断及失效明确返回。完整 facts 和 index 只在工具内部使用。

## 完成判据与保留边界

W03 的完成是最小语法提取与定位闭环通过验收，不要求每个输入 complete 或全库运行语义已证明。独立 fixtures 要求所选范围 complete；真实样本允许 partial。complete 仅表示所选显式语法范围；未解析外部调用本身不等于结构缺失。

没有独立 RHS 的赋值、动态 Class 重载／属性表／键、直接 components slot 写入保留 anchored partial 诊断；不造 nil 或多返回值。隐式 return、任意控制流、动态值、跨文件类型／调用唯一性与副作用不在最小分析范围。复杂续行无法证明时仅保留已有词法条件和范围说明。WARNING 保留为注释候选，不能直接生成常见坑。

数量截断未应用到提取层（truncated=false）；查询层限量截断有独立测试，分别报告。自动增量 review 迁移、类型核验／LuaCATS／Wiki 技术页、LuaLS 和游戏运行仍归后续阶段，不因 W03 完成就标为通过。

## 验证

原 W02 的 **116/116 项**完整比较通过（独立 51＋真实 65），保留全部禁止误报和错误输入要求，使用原 `check_baselines.py`，未用阶段投影代替全套验收。真实试点仍是有限特征清单，不能声称所有源文件是完整金标准。

38 项真实提取／包装测试、8 项真实索引测试、5 项 Rust 探针、12 项契约、8 项基准比较工具测试通过。独立输入覆盖三态、shadow／覆写、实例／别名、方括号、链式和嵌套调用、语法伪代码、短路／早退／闭包、中文 LF／CRLF、字节范围、错误与查询预算／失效。

真实复核：finiteuses:85 的 self:SetUses 链接到同类定义；equippable:100 的回调实参及 :102 的物品事件对象保持原文；entityscript:1908 的 v:OnSave 保留 pairs(self.components) 和 v.OnSave guards；axe 的四次 MakeAxe 调用分别保留，参数化 Prefab 不猜成字面注册；icebox 的 MakePlacer 保持普通 unresolved call。[raw/current/scripts/components/finiteuses.lua:85] [raw/current/scripts/components/equippable.lua:100] [raw/current/scripts/components/equippable.lua:102] [raw/current/scripts/entityscript.lua:1908] [raw/current/scripts/prefabs/axe.lua:291] [raw/current/scripts/prefabs/icebox.lua:101]

独立比较输出在 `scripts/output/w03-final-independent/`，真实试点最终使用全快照 `scripts/output/w03-full-final/facts/` 完整比较通过。全快照包含 4,030 份 facts（2,479 complete／1,549 partial／2 failed），91,215 个符号、391,446 条 call、67,290 条 component_access、3,129 条 event_emit、5,699 条 event_listen、2,459 条 Prefab 注册。有限 resolution 为 34,920 resolved／109 ambiguous／359,300 unresolved；不是运行关系正确率。全部 4,030 文件的原哈希、facts／manifest／报告及每个锚点和引用通过 source_index.build 校验；2 个 failed 的事实／锚点为空。

全量 facts 995,463,213 字节，索引 525,166,082 字节；均为内部可重建缓存，不进入默认上下文。最终索引为 1,517 个类别／哈希前缀分片，避免逐 key 文件过多。9 项真实查询检查来源有效性、结果预算及覆盖：Use 返回 3 个歧义候选，文件筛选后为 1；SetUses 目标反查 4 项；finiteuses 有 590 条语法引用只返回 5；equipped 有 24 项、动态 Prefab 有 345 项并报告截断；torch 注册 1 项、MakeAxe 调用 4 项、无命中保留格式缺口。输出 723～5,324 字节，均不超过默认 16,000；本机约 2.2～4.3 秒／查询，包含全来源哈希检查，不是跨平台性能保证或 token 测量。

health 最终为 96 symbols／490 anchors、374 records（139 call／127 assignment／48 comment／20 return／18 emit／4 listen／9 component／9 properties）；9 条属性映射和原 48 条注释保留。大型 maxwellhome.lua table 的原 return 和 trivia 字节检查通过；新增 10,000 项 table 独立测试避免退回缓慢 token 遍历。

## 复现

先按 [环境说明](../../../.claude/references/environment.md) 准备工具链；输出目录须不存在或为空。显式失败输入使 parse_scripts 返回 1，仍须继续检查其 failed facts，不能忽略或删除。

以下命令路径已同步工具箱布局，原验收版本、数字与保留边界不变。

```powershell
cargo build --locked --manifest-path scripts/fullmoon-dst/Cargo.toml
& .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests/python -p "test_extraction*.py"
& .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests/python -p test_source_index.py
& .\.venv\Scripts\python.exe scripts/tools/source/parse_scripts.py --catalog scripts/tests/fixtures/baselines/fixtures.json --output scripts/output/w03-fixtures-new
& .\.venv\Scripts\python.exe scripts/tools/verify/check_baselines.py scripts/tests/fixtures/baselines/fixtures.json --facts-root scripts/output/w03-fixtures-new/facts
& .\.venv\Scripts\python.exe scripts/tools/source/parse_scripts.py --catalog scripts/tests/fixtures/baselines/pilots.json --output scripts/output/w03-pilots-new
& .\.venv\Scripts\python.exe scripts/tools/verify/check_baselines.py scripts/tests/fixtures/baselines/pilots.json --facts-root scripts/output/w03-pilots-new/facts
```

两套基准成功后再按 [索引维护](../../../.claude/references/source-index.md) 的 --all／build 命令扩展全量，按 [源码查询](../../../.claude/skills/dst-wiki/references/query-source.md) 验证结果。大型静态 table 输入使用 AST visitor 直接访问 token，避免 Full Moon 扁平 Node::tokens 的 Vec 移位开销；原字节／trivia 仍核对。行字节列通过换行位置索引换算，未改变 CRLF 或 UTF-8 证据契约。
