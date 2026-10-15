# 统一接口数据契约 v1.0.0

本文件定义 W01 的机器交换格式，结构由 [contract.schema.json](../scripts/schemas/contract.schema.json) 校验；知识采纳以 [接口核验规则](verify-interfaces.md) 为准，页面与写入流程见 所用知识库 Skill 的 `references/maintain/maintain-wiki.md`（维护规范，按实际安装位置读取）。样例是人工标注参考；Full Moon 已完成最小语法提取与有限解析，范围见 [提取与索引验收](../docs/reports/w03/acceptance.md)。W04 已交付单组件 [LuaCATS 导出器](../scripts/tools/maintenance/export_luacats.py) 及 finiteuses／equippable 两份同源注解与 AI 编写知识页，范围见 [试点验收](../docs/reports/w04/acceptance.md)；没有自动覆盖既有 Wiki 的生成器。源码查询见 所用知识库 Skill 的 `references/query/query-source.md`（源码查询，按实际安装位置读取），首个 facts 检视见 [首层报告](../docs/reports/w03/stage1.md)。

本格式是本仓库的工程参考，供开发提取器、核验数据和消费工具时按需读取，解释机器字段的含义与不可表达的边界。日常查询使用短索引、选中的知识页与必要源码区间，无需读取本契约、全部 JSON 或完整 AST。

源码输入默认选择 `.lua`；`.po` 翻译资源属于主动排除范围，不进入 AST、符号索引或默认知识候选。报告覆盖时明确所选范围与排除策略，不把这些资源列为解析失败；`.lua` 中的非 UTF-8、字节码和语法错误仍须报告。`parse_scripts.py` 并列输出 `coverage-report.json`（运维报告 `report_version:1`，不属于契约 kind），记录全部选择、输入类别、哈希、错误及排除策略；manifest 的 files 仅列 UTF-8 源文件，包含语法失败输入。消费时同时检查报告，不以 manifest 清单宣称全部输入成功；不新增 v1.0.0 字段或伪造 UTF-8 编码。

## 文件层与存储

| kind | 内容 | 正式位置 |
|---|---|---|
| `manifest` | 快照、生产者、来源版本及文件哈希 | `<K>/output/<snapshot-id>/manifest.json` |
| `facts` | 一份源码文件的符号、语法观察、条件和定位 | `<K>/output/<snapshot-id>/facts/<source-path>.json` |
| `candidates` | 一个外部来源对一份源码文件的候选类型或说明 | `<K>/output/<snapshot-id>/candidates/<source-id>/<source-path>.json` |
| `reviews` | 独立维护的逐项核验补充及其证据锚点 | 独立 lsp-dst fork 的 `reviews/<source-path>.json`，纳入 fork 版本控制 |
| `resolved` | 从上述输入合并出的可重建缓存 | `<K>/output/<snapshot-id>/resolved/<source-path>.json` |
| `example-bundle` | 将五层嵌入同一文件的契约参考样例 | `scripts/tests/fixtures/bundles/*.json`，纳入版本控制 |

`<source-path>` 相对于来源根，例如 `components/finiteuses.lua`；因此后缀为 `.lua.json`。`snapshot-id` 包含版本命名空间，例如 `dst-steam-25643519`。生成目录保持 Git 忽略；核验输入位于独立维护 fork 的 reviews，主项目固定 fork commit。源码提取不能覆盖这些输入，也不复制整份游戏源码。

lsp-dst 维护库使用 [YingSP/lsp-dst](https://github.com/YingSP/lsp-dst)，主项目引用方式见 [fork 维护](lsp-dst.md)。候选 source.revision 记录实际 fork commit，files 记录实际字节哈希；上游基线通过 fork 覆盖清单保留。W01 历史样例继续引用原始上游 commit 与字节，不改成维护工作树。

一个快照共享 manifest，每份 facts 对应一个 candidates 文件和一个 reviews 文件。v1 每次合并使用一个指定外部库；未使用外部库时 source_id=null，anchors / claims 均为空。多外部库同时合并留待有真实需求时扩展格式，不能私自把对象改成数组。重新提取只改生成层，不能覆盖 fork 的 reviews。修改语义从 reviews 开始；不要手改 resolved、导出的注解或 Wiki 代替输入核验。

所有对象声明 `format_version: "1.0.0"`。不认识的主版本拒绝读取；新增字段或枚举必须升级格式并迁移，不能无声忽略。生产者另记自己的版本，`mode` 区分 `extracted`、`manual-reference` 和 `synthetic`；提取模式必须记录真实 parser 名称与版本。参考样例的 parser 为 null，不表示运行过 Full Moon。

## 来源、位置与身份

- `manifest.snapshot.version` 明确版本编号体系。W01 参考快照的 `BUILD.txt` 为 Steam buildid `25643519`，与其他 DST build 编号不能互换。外部 lsp-dst 用固定 Git commit，不用浮动分支名。
- 每个 source 有唯一 ID、kind、revision 和文件清单。文件路径使用 `/`，相对于来源根，禁止绝对路径、盘符和 `..`。`root_hint` 只是提示；读取工具通过显式来源根映射定位，不能直接执行或信任该值。
- 文件及 anchor 的 SHA-256 对原始 UTF-8 字节计算；不统一换行、不去 BOM、不重新格式化。anchor 为半开区间 `[start.byte, end.byte)`，byte 从 0 开始，line / column 从 1 开始。行以 LF 分隔，column 按该行 UTF-8 字节数计数，CR 若存在仍占一个字节；end 可位于下一行的列 1。
- symbol ID 约定为 `<source-path>#<scope>/<kind>:<name>`。例如 `components/finiteuses.lua#FiniteUses/method:Use`；顶层 scope 为 `module`，字段 scope 为所属类，构造器 name 为 `new`。局部函数用所在词法作用域；匿名函数用父作用域加 `anon:1` 等出现序号。同一作用域重定义追加 `@2` 等序号，并保留诊断。ID 不含行号，不能仅按同名方法跨文件关联。
- 文件顶层语句归属于 Lua chunk 的内部符号 `<source-path>#module/function:<chunk>`，其 scope 为 module、calling 为 plain、参数为空、owner_id 为 null、anchor 覆盖整个文件。它不是源码声明的 API，不导出成 Wiki 方法或类型；语法失败时不造有效 chunk。嵌套局部函数 scope 用 `module/<外层函数名>` 逐层表示；匿名函数使用该父 scope 下的 `anon:1` 等 name，例 `module/second/holder/function:anon:1`。这是 W02 的身份约定补充，不新增 JSON 字段或枚举。
- 非函数体的子块在父 scope 下按源码顺序记 `block:1` 等，例如 `module/outer/block:1`，避免不同块中的同名局部定义合并。重复定义的子作用域保留 `@N`；实例／未知表上的直接函数赋值保留写入目标名、所在词法 scope 与外层函数 owner，不因 `self.callback` 的形状猜成类方法。符号 scope 和 owner 仅描述声明，不证明运行绑定或控制流。
- `owner_id` 表示声明所属符号，不表示运行时继承。`base_expression` 只保留源码 Class 基类表达式；外部编辑器公共基类不能改写它。
- 行号移动不改变符号身份，但 anchor 的 byte 位置必须重新定位。区间哈希不变且身份唯一时可提出迁移；目标有歧义、代码区间或任一支撑证据变化时须复查，不能自动换绑同名符号。跨快照复用需要重新确认并更新核验记录，W01 不实现增量迁移。

reviews 自带证据 anchors，包括其他文件的调用点和宿主机制，不能依赖某次提取恰好输出相同区间。facts、candidates、reviews 的 anchor ID 在同一合并单元中唯一；重复区间可复用同一个 ID，重复定义 ID 则报错。

## 精简源码事实

`symbols` 保存类、构造器、函数、方法、字段与定义区间。`parameters` 按声明顺序记录参数，vararg 保留为 `...`；冒号方法使用 `calling: colon`，不额外造出显式 self，普通函数为 plain，类和字段为 none。

`records` 只存必要表达式和定位，不存整棵 AST。每条都有 subject、anchor 和 guards：

| kind | 最小观察 |
|---|---|
| `assignment` | 写入目标、右值原文、字面量类别；默认赋值不是字段终生类型 |
| `return` | 按分支保留表达式列表；implicit=true 表示无显式 return 的路径，仅能在提取器确认时填写 |
| `call` | 接收表达式、被调用表达式、参数原文及目标解析状态 |
| `property_callback` | Class 属性字段与回调表达式；运行副作用仍需核验 class 机制 |
| `method_alias` | 方法赋值／别名与解析状态，不能只搜索 function 声明 |
| `event_emit` / `event_listen` | 接收对象、事件名称表达式、可确定的字面名称、payload / callback |
| `component_access` | 接收对象、组件名表达式、可确定的字面名及 read / add / remove |
| `prefab_registration` | 注册名表达式、可确定的字面名、工厂表达式及解析状态 |
| `comment` | 选定的注释文本及样式；注释中的伪代码不计 assignment |

comment.text 保留 token 原字节，包括 CRLF 单行注释可能包含的 CR；style 的 line / block 仅分类语法形式。WARNING 等从文本筛选为待核验候选，不是新 record kind，也不直接等于常见坑。函数前的注释默认归 chunk，后续语义关联需另行核验。

guard 保存原条件、所在分支和区间；嵌套条件按外到内排列。else 仍保存对应 if 条件，不能把它误当正条件；after-return 表示前置早退的续行条件。这是词法条件记录，不声称完整控制流证明。

elseif / else 同时保留之前分支的 else 条件线索和当前分支条件；函数体只采用自身执行上下文的 guards，闭包定义时条件留在外层 assignment，不能传播成闭包运行前提。loop 记录 while／until 条件、generic for iterator 表达式或 numeric for 头部；repeat 的 until 不是首次执行的正条件。after-return 覆盖可证明的 return 分支续行，elseif 各返回分支与单一 else 续行分别保留条件；and／or 右值使用 then／else 词法条件。任意 CFG、异常与动态值不做证明，未覆盖形状保留限制。条件声明通过 associated assignment 的目标／区间回查，symbols 不能单独证明必达；未实现路径不私增字段。

字段首次观察锚定声明，写入逐条保留；没有独立源码 RHS 的隐式值／多返回扩展提供诊断，不伪造原表达式。property_callback 只承诺属性表语法映射；method_alias 的唯一已知目标保留显式 parameters／calling，候选歧义不拼接签名，未知成员 RHS 仅留 assignment 与诊断，不猜测成员必为方法。

`resolution.state` 为 resolved / unresolved / ambiguous。resolved 必须指向本单元已声明的唯一符号；unresolved 保留表达式和原因；ambiguous 保留候选 ID，禁止选择第一个。跨文件目标在未加载定义时保持 unresolved。v1 的事件、组件、调用和注册是语法观察，不是已证明的运行调用图或硬依赖；可选组件关系不能自动写成 dependencies。

事件专用观察不替代普通 call：`event_listen` 的 `payload_expression` 为 null，callback_expression 记录回调；可选的第三个来源实体参数保留在同位置 call.arguments，不能冒充事件 payload。去重显示可在消费视图处理，提取不能因此丢参数。

`coverage.selection` 明确本次覆盖的符号和 record_kinds。complete 只承诺这个选择范围的结构提取；不代表全文件、类型或行为全部正确。partial / failed、truncated 和 diagnostics 必须显式保留。动态目标未解析可以出现在结构完整的结果中；解析产生虚构 token 的区间不能作为有效证据。生产者不能凭解析器返回对象就宣称 complete。

## 候选与核验补充

每个条目用 `target = {symbol_id, facet}` 定位。facet 与 value 对应：

| facet | value.kind | 含义 |
|---|---|---|
| `field:type` / `param:<name>:type` | type | LuaCATS 类型表达式，未知 expression=null |
| `param:<name>:optional` | optional | accepts_omitted 与 accepts_nil 分开，未知为 null |
| `returns` | returns | 按位置列类型 slots、variadic 与 can_fall_through |
| `summary` / `behavior:<slug>` / `relation:<slug>` | text | 一条有边界的职责、行为或关系说明 |
| `aliases` | aliases | 需求措辞与检索别名，不作为源码方法别名 |

slots=[] 表示没有返回值；variadic=null 表示没有已声明的可变返回尾部，未确定时该 returns 条目保持 pending。can_fall_through 是返回路径信息，不自动等价于某个返回槽的 nil。类型词法合法性由后续 LuaLS 验证，契约校验不声称类型系统完备。未知不能为了出注解升级成已核验的 any。外部 idk / any 等占位即使在编辑器库有定义，也不证明实际类型；未确定的具体类型先保留为 null，并记录原候选来源。

vararg 可用 `param:...:type` 定位；其类型表达式描述每个可变参数的值类型，不用 vararg 个数伪造多个命名参数。

每条 review 记录 state、verdict、来源候选 ID、核验快照、核验者、日期、适用 scope、证据和运行记录。pending 是未完成核验，verified 是已审阅其支撑源码，stale 是证据变更后待复查；与页面状态分别处理。

- verified 必须有当前快照、日期和至少一份游戏源码证据；只有 external-annotation 不够。每个 evidence 保存 anchor_id、当时的 expected_sha256 和角色。
- accept 采纳当前 value；reject 仅拒绝关联候选，不删除源码事实。关联候选必须与 review 的 target 和 value 相同；修正值另建 accept 条目，不能把旧候选偷偷改成新值。
- 核验者可以是 AI；必须真实读取实现及必要调用点，scope 说明证明范围。机器只能校验结构、位置和状态一致性，不能证明文字语义正确。
- 属性副作用要包括 property-mechanism 证据，生命周期触发要包括 host-dispatch 证据，参数约定按需要包括 caller。一个定义区间哈希不是完整的影响分析；漏掉支撑文件仍可能漏报失效。
- 未知值不能成为有效 verified accept。state=stale、快照不符、证据缺失或 expected hash 不符均不能采纳。重新定位、补证据和确认新版本是后续核验工作。
- runtime=[] 表示没有游戏运行验证。非空记录必须有实际 build、环境、场景、预期、观察及结果文件；source-reviewed 不能自动升级为 runtime-tested。

## 确定性合并

源码事实负责声明与定位，review 负责采纳语义；外部候选永不自行升级。按 `(symbol_id, facet)` 汇集全部候选及 reviews，输出顺序及 ID 列表按字符串排序：

1. 筛选当前有效的 verified reviews；无效的已核验输入按 stale 对待并报告，严格校验拒绝声称其仍有效。
2. 多个 accept 的 value 相同则合并证据；不同则 conflict，value=null。若同一候选同时被有效 accept 和 reject，也为 conflict，禁止静默优先一方。
3. 有一致 accept 则 verified；reject 可以拒绝错误候选而不阻断独立核验的替代值。
4. 无 accept 且存在 stale 输入则 review-needed；其余为 unknown，包括只有外部候选、只有 pending 或只有 reject 的情况。unknown / review-needed 不提供可采纳 value。
5. 保留所有 candidate_ids、有效 rejected_candidate_ids、selected_review_ids 和 conflict_ids，形成逐项 provenance。没有候选或 review 的声明仍可进入结构索引，但不造出语义条目。

resolved 的 `input_sha256` 分别绑定 manifest、facts、candidates、reviews。哈希输入为 canonical JSON：对象键按 Unicode 顺序排序、无多余空白、UTF-8、非 ASCII 不转义，等价于 Python `json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)`。不得用原文件排版计算缓存身份。v1 数据不使用浮点 JSON 值，Lua 数值保留表达式字符串，避免跨语言序列化差异。

## 三种消费视图

- **短索引**：从 symbols + anchors 得到定义入口；summary / aliases 只采用 verified 项。未知、截断和歧义作为状态返回；读选定代码区间解决缺口。
- **LuaCATS**：从声明形状和 verified 类型／可选性／返回条目生成，未核验字段不输出臆造的具体类型；不把外部 editor base 当运行继承。W04 单组件导出已实现；无显式返回值不造返回槽，单个显式返回槽有可证明 fall-through 时导出可空，不将一般多返回 fall-through 任意补 nil。
- **Wiki**：采纳 verified summary / behavior / relation 和必要事实；典型案例仍需完整接入上下文与源码证据，不能从 AST 自动补齐“常见坑”。按 所用知识库 Skill 的 `references/maintain/write-format.md`（页面格式，按实际安装位置读取） 写元数据，按 所用知识库 Skill 的 `references/maintain/maintain-wiki.md`（知识维护，按实际安装位置读取） 记录核验版本、范围和运行程度。

样例中的 projection_checks 只是这三种视图可使用／排除的 ID 清单，不是已实现生成器。样例选择覆盖关键特征，不承诺组件全量类型覆盖。

## 校验参考样例

校验工具依赖 `requirements.txt` 中固定版本的 jsonschema；安装到自行选择的虚拟环境或临时目录，不要求 Rust 或 LuaLS。

```powershell
python -m pip install -r scripts/requirements.txt
```

```powershell
python scripts/tools/verify/validate_examples.py --source-root "dst=<K>/raw/current/scripts"
python -m unittest discover -s scripts/tests/python -p test_contract.py
```

默认读取 `scripts/tests/fixtures/bundles/`；游戏来源须通过 `--source-root dst=<K>/raw/current/scripts` 或知识库配置明确定位，核对文件、字节区间及 BUILD.txt。固定版本外部库可用 `--source-root lsp-dst=<本地根>` 显式核对；未提供时明确报告未核对的外部来源，不影响已经独立核验的游戏证据。`--structure-only` 仅做格式、引用、哈希关联和确定性合并检查，不能声称已核对本地源码。对历史样例应指定对应的游戏来源根，而不是改写样例哈希匹配新版本。W01 使用原上游 commit 的注解字节，带本地修订的 fork 工作树不能充当该历史来源；历史文件恢复方式见 fork 维护说明。

校验失败退出非零。当前工具面向 W01 bundle，不是 /lint-dst、批量合并器、LuaCATS 验证器或增量维护实现。
