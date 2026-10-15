# 提取与核验基准

本页是提取器开发与回归的工程参考，说明 W02 基准的样本范围、证据和比较方法，仅开发提取器或核对验收时读取。这里不是 Wiki 页面，不进入默认知识查询；技术结论按 所用知识库 Skill 的 `references/query/query.md`（查询证据规则，按实际安装位置读取），正式类型／核验输入维护另按 [接口核验](verify-interfaces.md)。所有预期为人工审阅，`parser_executed: false` 描述基准建立时的来源，不是解析器输出。当前完整提取比较 51/51 项独立样本及 65/65 项真实试点预期通过，见 [验收记录](../docs/reports/w03/acceptance.md)；JSON 按文件／check 读取，不整份发送给查询模型。

## 输入与覆盖

| 基准 | 范围 | 核验内容 |
|---|---|---|
| [fixtures.json](../scripts/tests/fixtures/baselines/fixtures.json) | 5 个独立 Lua 文件，51 项结构事实、8 项禁止误报项 | 不依赖 DST 安装；包含故意失败输入 |
| [pilots.json](../scripts/tests/fixtures/baselines/pilots.json) | Steam buildid 25643519，8 个源码文件、65 项结构事实、7 项人工行为记录 | 保留路径、字节／行列位置与 SHA-256，不复制整份游戏源码 |
| 所用知识库 Skill 的 `assets/templates/component.md`（component 模板，按实际安装位置读取） | W04 页面消费目标 | 摘要与修改入口优先，未知和验证范围显式保留 |

两份基准是验收选择清单，不是完整 facts 或 resolved 数据，也不替代 fork 正式 reviews。所有字段与方法类型仍由 W04 逐项审校；W01 examples 是历史契约样例，不能当完整提取金标准。

| 独立样本 | 主要特征 | W03 必须避免 |
|---|---|---|
| [component.lua](../scripts/tests/fixtures/extraction/component.lua) | Class 构造、属性回调、默认赋值、nil、冒号／vararg、then／else／早退、动态回调、事件与方法别名 | 丢掉条件／接收对象；将注释 fake／phantom／Imaginary 当符号 |
| [factories.lua](../scripts/tests/fixtures/extraction/factories.lua) | 两个字面 Prefab 注册、参数化 Prefab、包装工厂调用、服务端早退 | 将工厂参数 name 猜成 demo_c；把一个文件等同一个 Prefab |
| [scopes.lua](../scripts/tests/fixtures/extraction/scopes.lua) | 不同作用域的同名函数、匿名函数、动态组件／事件名、代码形状字符串 | 错绑同名 update；将字符串里的 fake 当真实调用 |
| [utf8-crlf.lua](../scripts/tests/fixtures/extraction/utf8-crlf.lua) | 中文 UTF-8 字节列、CRLF、模块顶层语句 | 按字符数计算 byte／column 或改写换行 |
| [invalid.lua](../scripts/tests/fixtures/extraction/invalid.lua) | 未闭合参数列表 | 声称 complete 或给修复 token 有效证据；应 failed＋error，facts／anchors 空 |

`.gitattributes` 为这些 Lua 输入禁用换行转换，使不同机器检出的哈希一致。样本中的 Class、Prefab 和实体 API 不在此实现；这些是解析输入，不是可运行模组。

## 本地源码特征

路径相对于 `raw/current/scripts/`；关键区间及支撑文件的原始字节已人工读取并登记在 pilots.json。

| 输入 | 结构事实 | 语义审阅边界 |
|---|---|---|
| `components/finiteuses.lua` | Class / total、current 默认值与属性映射；Use 原表达式；OnSave 条件返回；动态修改耗损回调 | 支撑属性机制、条件协作与保存路径；不从默认值推出终生类型 [raw/current/scripts/components/finiteuses.lua:10] [raw/current/scripts/class.lua:36] |
| `components/equippable.lua` | replica 调用、onequipfn 实参、equipped／unequipped 事件接收物品、监听、注释伪字段 | 分清物品与 owner、属性恢复；网络编码与完整回调类型留 W04 [raw/current/scripts/components/equippable.lua:92] |
| `components/container.lua` | Close 定义与两个生命周期方法别名 | 组件移除与实体移除不同宿主入口，不能合并触发 [raw/current/scripts/components/container.lua:1086] [raw/current/scripts/entityscript.lua:648] [raw/current/scripts/entityscript.lua:1723] |
| `class.lua` / `entityscript.lua` | 属性回调实参、可选钩子分派、OnSave 宿主调用 | 宿主机制是行为依据；编辑器公共模型不证明继承或钩子存在 [raw/current/scripts/class.lua:43] [raw/current/scripts/entityscript.lua:1903] |
| `prefabs/axe.lua` | 内层 fn、参数化 Prefab、四次 MakeAxe 调用、条件 finiteuses 挂载 | 模式与配置条件不能丢；词法观察不自动跨函数传播四种配置 [raw/current/scripts/prefabs/axe.lua:110] [raw/current/scripts/prefabs/axe.lua:291] |
| `prefabs/torch.lua` | 服务端 equippable 挂载、回调绑定、直接注册 | 只作装备代表调用，不承诺 torch 全部行为 [raw/current/scripts/prefabs/torch.lua:451] |
| `prefabs/icebox.lua` | 服务端 container、WidgetSetup、Prefab 与 MakePlacer 调用分别记录 | 没读 MakePlacer 定义时不能自动升级为已解析注册 [raw/current/scripts/prefabs/icebox.lua:77] [raw/current/scripts/prefabs/icebox.lua:100] |

## 比较约定

- `baseline_version: 1` 是验收清单版本，与接口 JSON `contract_version: 1.0.0` 分开。root_hint 定位输入；`--source-root` 可显式覆盖单份基准根。
- `cases[].checks` 按路径、稳定 symbol ID 与所选 data 匹配 facts，不比较生成器任意 record ID 或数组顺序。对象按指定字段子集比较；列表按完整顺序比较，因此参数和 guard 不可静默缺省。`forbidden` 拒绝伪符号、伪调用与未经传播的名称。
- check anchor 是必须包含的最小证据区间；输出 anchor 可更大，但所有实际位置／哈希必须对应原始字节。整文件 anchor 不能代替准确方法归属；人工复核 W03 输出区间是否足够短。
- 文件顶层记录使用契约定义的内部 `<chunk>`；不是公开 API。方法别名声明参数跟随已解析目标；没有唯一目标时保留 unresolved，不猜签名。
- guards 按外到内排列；else 保留原 if 条件和 else 标记，早退续行用 after-return。循环保留条件或 iterator 表达式，例如 `pairs(self.components)`；这是词法条件，不是完整控制流证明。
- 确定的本地局部／方法引用可 resolved；对象、replica 和动态回调默认 unresolved 并给 reason。同文件名称解析不证明运行时不被重写。参数化 Prefab 的 `literal_name: null` 与解析成功的工厂引用可以同时存在。
- 事件专用观察与普通 call 可以共享同一证据区间；ListenForEvent 的可选来源实体参数由 call.arguments 保留，event_listen 的 payload_expression 为 null。不能将监听来源当 payload，也不能为了去重丢实参。
- fixtures 成功文件要求所选结构范围 complete，错误文件 failed；pilots 允许 partial / complete，以 coverage.selection 明确范围，不能用 65 项检查声称全文件提取正确。两者均不接受 truncated。
- `semantic_reviews` 是这次人工核对记录，有证据、范围缺口及 `runtime_tested: false`；不是正式 W01 reviews，自动比较不验证其中文结论。游戏运行、LuaLS 和全量组件审校待 W04。

## 已实现的检查

默认检查输入与证据字节，只用 Python 标准库：

```powershell
python scripts/tools/verify/check_baselines.py --knowledge-root "<K>"
python scripts/tools/verify/check_baselines.py scripts/tests/fixtures/baselines/fixtures.json
```

W03 产出 facts 后，加 `--facts-root`，按 `<source-path>.json` 查找每个输出；此时使用 `requirements.txt` 的 jsonschema：

```powershell
python scripts/tools/verify/check_baselines.py scripts/tests/fixtures/baselines/fixtures.json --facts-root "<fixtures facts 根目录>"
python scripts/tools/verify/check_baselines.py scripts/tests/fixtures/baselines/pilots.json --source-root "<K>/raw/current/scripts" --facts-root "<K>/output/dst-steam-25643519/facts"
python -m unittest discover -s scripts/tests/python -p test_baselines.py
```

比较工具检查 JSON Schema、位置、引用、所选正例与禁止误报项；8 项独立测试验证条件遗漏、事件接收对象、伪符号、失效坐标／文件、错误输出与解析失败。测试只验证比较工具，不声称已验证解析器。W03 还需记录真实 parser 版本、解析诊断与提取覆盖，逐项人工核对输出；自动化检查不替代语义审阅。

阶段比较使用 `verify_extraction.py`，默认 `--stage 2` 从原清单选择全部声明和 assignment／property_callback／method_alias／return／comment；`--stage 1` 可复核历史非字段／别名声明及 comment。均保留所有 forbidden 和错误输入要求，允许 partial，不改原基准或降低完整 `check_baselines.py` 的要求。当前验收使用完整 check_baselines.py，116/116 项通过；阶段工具仅保留历史复核，不代替全套检查。`test_extraction*.py` 共 38 项真实 binary／包装测试，另有 8 项源码索引测试，需先构建，不能与比较工具的 8 项混称。
