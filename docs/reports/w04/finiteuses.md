# 类型与页面首轮检视

日期：2026-10-11；范围为 W04 的 finiteuses 首轮闭环，W04 整阶段尚未完成。版本唯一来源见 [环境说明](../../../.claude/references/environment.md)，详细进度见 [PLAN](../../../PLAN.md#w04核验类型并生成注解与-wiki)。

## 交付与边界

- Steam buildid 25643519 未变，源码准备跳过解压，复用 W03 已验收 facts；没有重建全库或修改游戏源码。
- finiteuses 原有 5 条核验保留，新增 78 条，共 83 条：8 个字段、19 个实际方法的参数类型／省略性／返回分支、摘要及 Class／耗尽／攻击路径说明。equippable 仍有前期 8 条，共 91 条本地 reviews；并不代表全部依赖类型、引擎内部或任意模组赋值已经准确。
- [LuaCATS 导出](../../../scripts/tools/maintenance/export_luacats.py) 直接消费正式 reviews 与匹配 facts／来源 manifest，共用契约检查和确定性合并。报告 76 条投影 reviews、零缺失 facets，完整 resolved 保留 83 条。实际 Class 基类为 nil，声明不再继承 component_base；补出源码真实 OnSave／OnLoad／OnUsedAsItem，不造公共模型钩子。
- [finiteuses 知识页](../../../wiki/reference/components/finiteuses.md) 使用同一核验结论，86 行、8,858 UTF-8 字节；例子只修改已有斧头，不需要额外资源。保留旧存档恢复绝对次数、耗尽事件在归零前发出、动作消费与武器攻击分开等边界。案例未在游戏运行。
- [最小页面检查](../../../scripts/tools/verify/validate_page.py) 检查元数据、链接和分类大小，阈值从 page-format 唯一表读。超限退出失败并报告位置，不改写或截断页面；发布登记仍由维护流程在检查后执行。标签分类、Top 30／叶级索引一致性和源码语义自动检查留 W05。

## 实际核验发现

finiteuses 的 SetMaxUses 只改 total，属性写入经 Class 更新可选修理组件；初始化满次数要同时设置 current。SetUses 先发 percentusedchange，再把非正值归零；onfinished 只在正到非正转换触发，实体删除由回调决定。动作消费先查 Action 对象映射，再应用使用者效率和修正回调；Weapon 攻击直接 Use，不进入此链。满次数默认不存，非满初始状态用 doesnotstartfull 控制保存。赋值型 setter 缺少运行时类型检查，LuaCATS 记录原版推荐域与 nil 行为，不证明任意 Lua 值皆有效。

原版 Class、宿主分派、动作入口和代表实例均纳入 reviews 的字节哈希。引擎网络内部没有可见 Lua 实现；本轮只审阅可见逻辑，未声称客户端显示或多人同步运行结果。此前公共 component_base 仅是编辑器模型，本轮不修改全库模型，以移除试点继承并显式声明实际接口解决误报。

## 验证结果

- 完整 Python 回归 91 项通过，其中新增 9 项投影、9 项页面测试；原契约、基准、提取／包装、源码准备与索引测试保持通过。
- fork 证据检查：2 份注解、91 条记录、来源文件／区间／行列／SHA-256 通过。正式 Schema 与原始 fixtures／baselines 未改，导出实际输入通过契约校验。
- LuaLS 3.19.1／Lua 5.1：[verify_luacats.py](../../../scripts/tools/verify/verify_luacats.py) 检查生成声明和正确用法无诊断；错误数值参数、nil 存档参数、不存在 OnUpdate 各命中预期诊断。依赖库仅加载，未诊断全库；实际二进制和声明哈希在本地报告。
- 页面最低检查通过，覆盖全部当前 Wiki 页／索引；LF／CRLF、长行和代码块超限、失效链接／章节、重复 metadata、错误状态、越界路径有独立用例。元数据／路径通过不证明中文行为说明正确。
- 游戏运行未执行；实际 token 收益未测量。最终文档链接、字节保护和 Git 索引检查留本轮追加日志记录。

本地生成／LuaLS 报告在 `scripts/output/w04-finiteuses-20261011/`，原文备份在 `scripts/output/backups/w04-finiteuses-20261011/`，均被 Git 忽略，不是发布依赖。工具用法与复现命令见 [工具箱](../../../scripts/README.md#类型导出与最小页面校验)。

## 尚未完成

equippable 的字段、回调、属性序列化和可空持有者需同等核验，再生成第二份组件页并执行 LuaLS。两份试点通过后才能完成 W04 整阶段验收。

本轮 fork 改动保留在独立工作树，未暂存、提交、推送或修改主项目 pin；旧 pin 仍只有已发布的前期修订，不能复现本轮输入。发布与更新引用作为后续步骤，不能用未发布 commit 冒充固定版本。常驻 AGENTS／CLAUDE／SKILL 路由未扩张；查询和案例维护继续无需 Python、LuaLS 或 fork 克隆。
