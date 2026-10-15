# DST Toolbox

独立的 DST Lua 5.1 提取、索引、校验和 LuaCATS／fork 维护工具。普通模组开发、Markdown 查询与案例／陷阱增修不要求本仓。原 scripts 布局保留，所有知识输入从显式参数或用户 `~/.dst-wiki/config.json` 定位，四仓无需相邻。

当前功能满足下一阶段，暂时冻结一般功能演进；按明确任务补充必要检查与只读迁移预览。维护基线、正式类型覆盖和暂缓项见 [PLAN](PLAN.md)，实现职责见 [工程设计](docs/design.md)。lsp-dst 仅 finiteuses／equippable 有正式逐项核验，其余声明仍作候选。

## 目录与依赖

`scripts/fullmoon-dst/` 是 Rust 0.4.0／Full Moon 3.0.0；`scripts/schemas/` 是契约；`scripts/tests/` 是原字节 fixtures 与 Python 测试；`scripts/tools/` 按 source／wiki／verify／maintenance 分类；`references/` 保存工程约定。固定 fork pin 在 `scripts/vendor/lsp-dst.json`，完整克隆被忽略。

Python 包装要求 3.11+，依赖固定在 [requirements.txt](scripts/requirements.txt)。提取须构建 Rust 核心；Wiki 检索／页面校验需要 Python 和 PyYAML，独立源码链接校验只用 Python 标准库；LuaLS 仅注解检查时使用。版本依据见 [环境](references/environment.md)，正式字段见 [输出契约](references/output-format.md)。

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r scripts/requirements.txt
cargo build --locked --release --manifest-path scripts/fullmoon-dst/Cargo.toml
```

下文 K＝知识仓、S＝知识库维护 Skill 的实际绝对路径；占位符须替换，python 选择已有环境。命令从工具仓执行，跨工作目录使用脚本绝对路径即可。源码准备已经随两个 Skill 安装，用所用 Skill 的 scripts/setup_raw.ps1 -KnowledgeRoot <K>，不要求本工具仓。

## facts 与源码索引

```powershell
python scripts/tools/source/parse_scripts.py --knowledge-root "<K>" components/health.lua --output "<K>/output/health-new" --binary scripts/fullmoon-dst/target/release/fullmoon-dst.exe
python scripts/tools/source/source_index.py build --snapshot-root "<K>/output/health-new" --source-root "<K>/raw/current/scripts"
python scripts/tools/source/source_index.py query definition DoDelta --snapshot-root "<K>/output/health-new" --source-root "<K>/raw/current/scripts" --path components/health.lua
```

`--all` 才选择全量 Lua，`.po` 主动排除；自定义源码根须提供真实 --version／编号体系和 --output。catalog 的 root_hint 保留历史来源：fixture 自动定位工具箱测试输入，真实源码通过 --source-root 或配置定位。输出非空拒绝覆盖；解析缺口输出 failed／partial 与 diagnostics。默认完整 AST 不落盘，仅输出精简 facts、manifest 与覆盖报告，默认 output 在 K；构建／查询检查版本与哈希，有限 resolution 不证明运行调用图。详见 [索引维护](references/source-index.md)。

## Wiki 校验、缓存与章节

页面格式唯一来源是维护 Skill 的 write-format.md，用 --format 显式传入，不复制格式／标签到工具仓。

```powershell
python scripts/tools/verify/validate_page.py --wiki-root "<K>/wiki" --source-root "<K>/raw/current/scripts" --format "<S>/references/maintain/write-format.md"
python scripts/tools/verify/validate_source_links.py --wiki-root "<K>/wiki"
python scripts/tools/wiki/update_index.py --wiki-root "<K>/wiki" --source-root "<K>/raw/current/scripts" --format "<S>/references/maintain/write-format.md"
python scripts/tools/wiki/query_wiki.py --wiki-root "<K>/wiki" search "工具耐久"
python scripts/tools/wiki/query_wiki.py --wiki-root "<K>/wiki" read "reference/components/finiteuses#典型接入"
```

默认知识缓存 K/output/wiki/index.json，可用 --output／--index 改路径。人工 Markdown 控制摘要／分类／Top 30，构建只校验并原子写缓存；search 检查页面哈希与增删改，stale 拒用。read 不依赖缓存，按真实章节输出前提、代码与验证边界；默认 5 候选／16,000 UTF-8 总输出字节，超预算整项省略并报告，不切代码。词汇命中不是功能证明；结构校验不核验源码行号／哈希或游戏表现，缺缓存直接搜索 Markdown。

页面／导航、源码引用与 Lua 示例的详细参数、扫描范围、输出、截断与退出码只在 [Wiki 校验工具](references/wiki-validation.md) 对应小节维护；这里保留命令入口，按需读取，不整读所有工具说明。

### 源码哈希基线

`validate_source_hashes.py` 提供显式 check／record；缓存、局部写入、损坏清单与输出边界见 [源码哈希基线工具](references/source-baseline.md)。是否刷新由调用方核验结果决定，普通查询不自动执行。

### 源码锚点迁移预览

版本修补可用 `scripts/tools/maintenance/plan_source_link_updates.py` 对显式旧新快照和所选 Wiki 页生成只读计划；完整相同且区间外上下文充分／唯一才给迁移建议。`--include-patch` 对支持格式输出相对知识根的补丁，CRLF 等格式受限页只给建议与 review；不自动写文件、升版或刷新基线。调用、退出码及边界见 [迁移预览](references/source-link-migration.md)；语义是否可沿用由知识 Skill 和已核验更新条目判断。

## 基准、接口与 fork

```powershell
python scripts/tools/verify/validate_examples.py --source-root "dst=<K>/raw/current/scripts"
python scripts/tools/verify/check_baselines.py --knowledge-root "<K>"
python scripts/tools/maintenance/maintain_lsp_dst.py check --knowledge-root "<K>"
```

check_baselines 可加 --facts-root 比较人工预期；参考 bundle 的 --structure-only 不需要游戏输入，不等于语义验证。runtime 证据须显式 --record-root；export_luacats 参数均明确指定事实／manifest／reviews／source／output，源记录有运行条目时使用同一记录根。注解及正式 reviews 在独立 lsp-dst fork维护；pin 仍只固定已发布 commit，不自动提交或推送。详见 [接口核验](references/verify-interfaces.md)／[fork](references/lsp-dst.md)。

## 验证与 Skill 辅助脚本同步

完整提取测试须 debug binary，原 fixtures 的 -text 属性保留。格式测试明确指向一个固定测试规范；实际知识校验使用上述生产 --format。源码准备测试仅在显式指定已安装 Skill 时运行。

```powershell
cargo build --locked --manifest-path scripts/fullmoon-dst/Cargo.toml
$env:DST_WIKI_FORMAT = "<S>/references/maintain/write-format.md"
$env:DST_SETUP_SCRIPT = "<S>/scripts/setup_raw.ps1"
python -m unittest discover -s scripts/tests/python
python scripts/tools/maintenance/sync_skill_helpers.py --source-skill "<S>" --development-skill "<开发 Skill 根>"
```

helper 权威实现随 dst-wiki-skill维护，开发 Skill 通过显式工具取得哈希一致副本，安装后独立使用。两 Skill 的最小查询与路径约定改动需交叉检查，不形成运行依赖。

只验证源码准备时，用 `python -m unittest discover -s scripts/tests/python -p test_setup_raw.py -v`。可选 `DST_TEST_POWERSHELL` 指定要测的 PowerShell 可执行文件；Windows 设置 `DST_TEST_OTHER_DRIVE_TEMP` 为另一盘上已存在、可写的绝对目录后，额外执行跨盘用例。测试只在该目录内新建临时子目录并清理，不访问真实游戏安装；未设置时跳过跨盘用例。

只验证 Wiki 源码引用检查时，用 `python -B -m unittest discover -s scripts/tests/python -p test_source_links.py -v`；合成输入位于自动清理的临时目录，不需要游戏安装、PyYAML、AST 或 Skill。

只验证源码哈希基线时，用 `python -B -m unittest discover -s scripts/tests/python -p test_source_hashes.py -v`；同样使用自动清理的临时输入，不访问真实知识库。

只验证锚点迁移预览时，用 `python -B -m unittest discover -s scripts/tests/python -p test_source_link_updates.py -v`；只用标准库和自动清理的合成输入。

历史 [W03](docs/reports/w03/acceptance.md)／[W04](docs/reports/w04/acceptance.md)／[检索](docs/reports/w05/retrieval.md) 报告保留当时命令与路径；迁移映射见 [报告说明](docs/reports/README.md)。本地生成缓存、游戏源码、个人配置、Cargo target 和完整 fork 克隆不提交。原创代码采用 [AGPL-3.0-or-later](LICENSE)；工具输出、游戏源码与第三方组件不适用本仓授权，边界见 [NOTICE](NOTICE)，外部贡献按 [贡献约定](CONTRIBUTING.md) 接收。
