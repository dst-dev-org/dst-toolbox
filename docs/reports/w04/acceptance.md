# 类型与知识页试点验收

日期：2026-10-11；W04 的两份试点及发布／固定引用完成。前一轮状态保留在 [finiteuses 首轮检视](finiteuses.md)，环境与版本以 [环境说明](../../../.claude/references/environment.md) 为准。游戏运行未执行，W05 检索与真实任务验收尚未开始。

## 交付范围

| 组件 | 正式 reviews | 导出范围 | 投影采用条目 | Wiki |
|---|---:|---|---:|---|
| finiteuses | 83 | 8 个字段、19 个实际方法 | 76 | [组件页](../../../wiki/reference/components/finiteuses.md)；原版斧头总次数接入 |
| equippable | 93 | 17 个声明／属性字段、18 个实际方法 | 80 | [组件页](../../../wiki/reference/components/equippable.md)；原版手杖装备速度／精神贡献接入 |

两份导出均无缺失 facets、冲突或失效证据；投影仅采用字段、参数、可空／省略、返回和摘要条目，其他行为依据继续保留在 reviews／resolved，不因不进入声明而丢弃。两个源码 Class 均无真实基类，声明没有继承 component_base，也没有补造公共编辑器可选钩子。

这是所列组件的原版接口约定和必要行为核验；不是全库／引擎准确性或任意模组写入证明。外部 ent／Action 模型只作兼容编辑器类型，其他依赖未因此升级。equippable 的外部动态字段 flipdapperonmerms／is_magic_dapperness／refuse_on_restrict 等没有完整字段投影；相关被选行为仅核验所列消费者与调用点，不补造未抽取的声明。

## equippable 的关键核验结果

- 原版 Inventory 三处 ToPocket() 不传 owner，onpocketfn 必须接受 nil；方法仅调用回调，不修改装备标志，不覆盖全部持有者变化。Equip／Unequip 的非空 owner 约定来自原版 Inventory 和实体回调域，不能据赋值语法扩大为所有 Lua 值。
- Inventory:Equip 先 OnPutInInventory，再调用组件 Equip，随后登记人物槽位、发人物 equip。物品 equipped／unequipped 与人物 equip／unequip 是不同事件和接收对象；物品 equipped 回调中槽位可能尚未登记。
- equipslot 存槽名字符串，网络 ID 由 equipslotutil 转换；walkspeedmult 属性经 Class 写回调和 inventoryitem replica 序列化。范围和精度以实际断言为准，equippable 与 saddler 不能同时占用共享字段。
- 正确拼写 restrictedtag 在 Class 属性映射中存在，默认 nil；注释 retrictedtag 不执行。IsRestricted 返回 boolean，true 为受限；首项 restrictedtag ~= nil 使无标签路径返回 false。加载判定只放宽匹配人物的技能树标签。
- dapperness 是装备基础精神速率贡献，sanity 仅遍历装备槽，经角色／湿度／总速率修正后按 dt 使用；不统一除以 54，也不保证净增某数／分钟。动态回调覆盖基础／鱼人翻转值，湿物品惩罚仍随后应用。
- OnRemoveFromEntity 重置锁及 replica 属性，不自动调用卸装回调或清人物槽。宿主 RemoveComponent 和实体 Remove 的分派不同，自建效果须核对各清理路径；引擎网络内部没有可见 Lua 实现，实际传播与预测仍需游戏验证。

上述结论及全部必要证据保存在 fork reviews，来源为 Steam buildid 25643519，原始 UTF-8 字节／区间／行列／SHA-256 核对通过。声明与知识页使用相同核验结论，未修改游戏源码、正式 Schema、历史 bundles 或人工基准。

## 实际验证

- 完整 Python 回归 **98 项通过**：新增 7 项 LuaLS 报告检查，要求每处故意错误准确命中，同时拒绝正例／声明错误、额外错误、错误行位或未知诊断来源；原 91 项保留通过。
- LuaLS **3.19.1／Lua 5.1**：两份声明和各自正例无诊断。finiteuses 三处、equippable 六处故意错误全部按行号和代码匹配；依赖库加载但不诊断全库，库级 luals_checked 仍为 false。记录二进制、声明、用例及配置哈希。
- 入袋回调的 `fun(..., owner: ent?)` 在该 LuaLS 版本没有命中故意未保护访问；改为 `owner: ent|nil` 后命中 need-check-nil。批量检查显式启用该诊断，不依赖编辑器打开文件状态；保留函数顶层参数的省略与可空约定。这是实测的注解消费者差异，不表示游戏类型变化。
- fork 的 **2 份注解／176 条记录**通过来源／区间字节检查。重新导出两份声明与维护声明原字节一致；契约输入、确定性合并、零缺口／零冲突检查通过。
- 7 份当前 Wiki 技术页／索引通过最低元数据、链接／标题和行数／UTF-8 字节检查；叶级登记与两个根精选入口人工核对。完整标签／索引语义自动检查仍留 W05，结构通过不代替 DST 语义核验。
- W01 历史 bundles 和 W02 基准来源字节检查通过；历史外部注解另按原 commit 导出检查，不以新 fork 代替原字节。没有因为此轮改注解而重写旧参考数据。
- **游戏未运行**：两个案例保持 source-reviewed。客户端预测／多人显示／骑乘、角色精神差异、旧存档／删除／重载和模组冲突未做实际运行验收；实际 token 收益尚未测量。

本地最终生成和诊断报告在 `scripts/output/w04-equippable-20261011/`，备份在 `scripts/output/backups/w04-equippable-20261011/`；均忽略，不作为查询／发布依赖。工具命令以 [工具箱说明](../../../scripts/README.md#类型导出与最小页面校验) 为准；初次未命中的诊断报告保留为本次排查记录，不当成功结果。

## 发布与复现

独立 fork 已提交并推送 [1db05561ea6ea271093ea780b60d49e7499baf40](https://github.com/YingSP/lsp-dst/commit/1db05561ea6ea271093ea780b60d49e7499baf40)，包含两份声明、正式 reviews／manifest／coverage、维护说明及局部 [LuaLS 记录](https://github.com/YingSP/lsp-dst/blob/1db05561ea6ea271093ea780b60d49e7499baf40/reviews/luals-validation.json)。

主项目 [lsp-dst.json](../../../scripts/vendor/lsp-dst.json) 已固定该已发布 commit；maintain_lsp_dst.py pin／check 通过。独立工作树干净，上游 push URL 仍为 DISABLED；主项目暂存区不变，主仓未提交或推送。新克隆按 pin setup 后可复现已登记输入，不再依赖未发布工作树。证据重查需要同版本游戏快照，单独复用注解不需要 Wiki／Python／源码。

W04 的验收是两份类型与知识页一致、证据和未知边界可追溯、结构／LuaLS 检查及固定版本可复现；没有将游戏运行或全库审校冒充已完成。下一步按 PLAN 进入 W05 的索引、章节读取、cookbook 与真实需求闭环。
