# DST 接口核验规范

仅维护机器 facts、正式 reviews／类型补充、LuaCATS 注解或 lsp-dst fork 数据时读取；技术结论执行 所用知识库 Skill 的 `references/query/query.md`（查询规则，按实际安装位置读取），写知识同时执行 所用知识库 Skill 的 `references/maintain/maintain-wiki.md`（知识维护，按实际安装位置读取）。普通 Wiki 案例、教程与场景问题增修不触发本文件及工程契约加载。

技术格式见 [输出契约](output-format.md) 和 [JSON Schema](../scripts/schemas/contract.schema.json)，fork 操作见 [维护说明](lsp-dst.md)。仅在数据或工具维护时加载这些文件。

- 机器事实记录声明、表达式、条件与位置；默认赋值不等于终生类型，语法引用不等于运行调用图或硬依赖。完整 AST 不作默认 AI 输入，精简事实按需求读取。
- 外部候选固定实际 commit。真实继承依据源码，编辑器公共基类不证明组件拥有可选钩子；未知类型、未解析目标、截断、部分覆盖及冲突显式保留。
- 核验补充独立于产物，逐项记范围、核验者、日期、快照及全部必要证据哈希。只有外部注解不足以核验；属性和生命周期需必要机制／宿主证据，不能静默重绑同名符号。
- 条目 `pending / verified / stale` 与合并结果 `unknown / verified / conflict / review-needed` 分开。只用当前有效的已采纳结论生成具体类型、Wiki 技术说明或可运行代码；运行验证另记。
- lsp-dst 注解、正式 reviews 和覆盖清单统一在独立 fork 维护，本项目固定 commit 读取；修改先从核验输入开始，注解与 Wiki 共用结论，不分别手改造成分歧。
- 契约样例是工具参考数据，不进入 Wiki 默认索引；格式与哈希检查不能证明语义正确。证据变化后的自动影响分析和失效迁移按实际工具能力执行。
