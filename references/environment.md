# 环境、版本与 Lua 方言

记录日期：2026-10-11。本仓库工程参考，仅准备提取器环境、复现检查、升级依赖或评估兼容性时读取；本页归档版本选择与当前验证范围，不是游戏运行测试结果。提取数据遵守 [输出契约](output-format.md)，工作进度见 [PLAN](../PLAN.md)。

## 固定版本与选择

| 项目 | 当前版本／配置 | 依据与用途 |
|---|---|---|
| 游戏源码快照 | Steam buildid `25643519` | `raw/current/BUILD.txt`；不与其他 DST build 编号互换 |
| 游戏 Lua 版本标识 | `Lua 5.1.4`，解析目标为 Lua 5.1 | 本机游戏客户端／服务器二进制标识及源码用法，详见下节；未在游戏中执行 `_VERSION` |
| Full Moon | `3.0.0`，精确依赖 `=3.0.0` | [Cargo.toml](../scripts/fullmoon-dst/Cargo.toml) + [Cargo.lock](../scripts/fullmoon-dst/Cargo.lock)；本快照可读源码兼容性已检查 |
| 提取器／新增依赖 | `fullmoon-dst 0.4.0`；`serde_json =1.0.145`、`sha2 =0.10.9` | facts JSON 和原字节 SHA-256；传递依赖固定在 Cargo.lock，无图分析依赖 |
| 解析配置 | `default-features = false`；`LuaVersion::lua51()` | 不开启 `lua52 / lua53 / lua54 / luajit / luau / cfxlua`；不序列化整份 AST |
| Rust | `1.99.0`，`minimal` profile | [rust-toolchain.toml](../scripts/fullmoon-dst/rust-toolchain.toml)；已编译 Full Moon 与探针 |
| rustfmt | 随 `1.99.0` 工具链的 rustfmt 组件 | 首层开发时追加用户级格式化工具，未永久改 PATH |
| 编译目标 | `x86_64-pc-windows-msvc` | 64 位 Windows 目标；`x86_64` 不是 32 位 x86 |
| MSVC | 本机工具目录 `14.50.35717` | 已有 x64 编译器和链接器；C 探针及 Cargo 编译运行通过 |
| Windows SDK | 本机 `10.0.26100.0` | 已有 x64 库，可用于链接；不要求安装整套 Visual Studio IDE |
| Python | 本机 `3.14.3`；校验包装使用 `tomllib`，要求 Python 3.11+ | 项目 `.venv`，不向全局 Python 安装项目依赖 |
| jsonschema | `4.25.1` | [requirements.txt](../scripts/requirements.txt) 固定；W01／W02 检查使用 |
| PyYAML | `6.0.3` | 项目 `.venv`；最小页面元数据检查，依赖在 requirements.txt 固定；基础读写 Markdown 不要求安装 |
| LuaLS | `3.19.1`，Windows x64；检查目标 `Lua 5.1` | 复用本机 VS Code `sumneko.lua-3.19.1-win32-x64/server/bin/lua-language-server.exe`；finiteuses／equippable 两份声明与正反例通过，不代表全库或游戏运行 |

Rust 和 Full Moon 的版本号分别属于编译工具链和解析器，不需要与游戏 Lua 的 `5.1.4` 数字相同。Full Moon `3.0.0` 的 Lua 5.1 配置已通过当前验证，先保留此组合；不因“最新”就开启其他方言，也不凭未做过的比较声称它在所有版本中最优。依赖升级须重新执行兼容性和基准检查。

## 游戏版本与特性依据

- `class.lua` 文件头说明兼容 Lua 5.1；这是该文件的兼容注释，不能单独证明整个运行库版本。[raw/current/scripts/class.lua:2]
- 模组加载对函数设置环境，保留 `setfenv` 用法；工具代码注明 Lua 5.1 环境并调用 `loadstring`。这些支持 Lua 5.1 API 目标，不把运行库函数名当成新语法。[raw/current/scripts/mods.lua:351] [raw/current/scripts/mods.lua:397] [raw/current/scripts/util.lua:796] [raw/current/scripts/util.lua:799]
- 位运算通过 `bit.bor / bit.band / bit.bnot` 调用；调用本身不证明 LuaJIT，也不需要开启 Lua 5.3 的原生位运算符。[raw/current/scripts/physics.lua:34] [raw/current/scripts/physics.lua:45]
- Class、属性回调、Prefab 工厂、实体 API 和宿主钩子按 DST 实现核验；它们不是要启用的新 Lua 方言。[raw/current/scripts/class.lua:36] [raw/current/scripts/class.lua:83]

同一安装的两个 64 位程序中均发现原始 ASCII 标识 `$Lua: Lua 5.1.4 Copyright (C) 1994-2008 Lua.org, PUC-Rio $`。相对于游戏安装根的文件、原始字节位置及 SHA-256 为：

| 文件 | 标识起始 byte（从 0 起） | 文件 SHA-256 |
|---|---|---|
| `bin64/dontstarve_steam_x64.exe` | `6004080` | `e40de9b85df87a0ccd099be5bdeef84be62e3fb663163e83a4952a652db8c5c5` |
| `bin64/dontstarve_dedicated_server_nullrenderer_x64.exe` | `5484128` | `95d361bf6e60d498951e00449eedd2f9ac24a21ab5d8ae83e8bb39efce478545` |

这是本机二进制标识检查，不证明 Klei 对运行库没有修改，也不声称其他 build 或平台完全一致。W03 不需要下载或替换游戏的 Lua 解释器；需要实际行为验证时使用对应游戏环境。参考语法见 [Lua 5.1 手册](https://www.lua.org/manual/5.1/manual.html)，解析器接口见 [Full Moon 3.0.0](https://docs.rs/full_moon/3.0.0/full_moon/)。

## 已验证范围与输入边界

默认仅选择 `.lua` 进入语法扫描与后续 AST 提取；`.po` 翻译资源不解析、不进入符号／知识检索索引，也不计为解析失败或覆盖缺口。本快照有 12 个 `.po` 文件，共 215,043,214 字节（约 205 MiB），仍保留在原始快照中，不改变解压流程。根目录 知识仓 `.rgignore` 排除默认 `rg` 搜索中的 `.po`；从其他工作目录直接查本库时用 `-g '!*.po'` 保持该范围。明确处理翻译任务时再定向读取。语言加载、字符串组织等 `.lua` 代码仍属于源码，不因功能与翻译有关就排除。

- 5 项 Rust 探针测试通过：Lua 5.1 环境调用／vararg／长字符串、中文／CRLF 与半开 token 范围、语法错误拒绝、较新方言语法拒绝、非 UTF-8／字节码区分。
- 4 个合法独立样本和 8 个真实源码文件共 12 个输入解析通过，AST 原样还原且 token 区间对应原字节；故意错误样本退出 1，恢复 AST 被丢弃。
- 全快照 4,030 个 `.lua` 文件中 4,028 个 UTF-8 源文件通过 Lua 5.1 **语法检查**；另外两项是下表的输入格式缺口，不是已确认的方言冲突。该扫描不执行全量往返／位置检查、事实提取或游戏代码。
- W03 时 Python 12 项契约、8 项基准比较工具、38 项真实提取／包装与 8 项索引测试通过；原 W02 完整 116/116 项通过。全快照 facts／字节／引用与查询验收见 [提取与索引验收](../docs/reports/w03/acceptance.md)；首层／第二层报告保留历史状态。当时 LuaLS 与游戏运行未执行，W04 新增检查范围见下节。

| 输入 | 发现 | W03 处理边界 |
|---|---|---|
| `easing.lua` | 原字节 `295` 为 `0xA9`，第 14 行版权注释不符合 UTF-8；文件 SHA-256 `c2688aa196b250aa0b73ebdc41395cf0e167dfbeb61c481de92e2b63f70ca446` | 保留原字节并报告编码缺口；不得用替换字符解码或静默转码来伪造有效锚点。编码支持与字节映射有真实需求时另行实现 |
| `nis/xbnyn.lua` | 文件头 `1B 4C 75 61 51`，为 Lua 5.1 编译 chunk；文件 SHA-256 `75a5912351c8e7536b51299e10e0d91c4f3df3e74d68062e326f75667a9c4d27` | 明确为字节码，源码 AST 提取不支持，不执行或反编译；记入覆盖缺口，不能当作实现不存在 |

位置必须从原始 byte 计算 line／column。Full Moon 原生位置在 trivia 的换行末端与契约约定有差异，探针使用原 byte 切片核对 token，按 LF 分行并按 UTF-8 字节计算列，保留 CR；不直接把 `Position.character()` 填入证据锚点。

当前选用 `parse_fallible(..., LuaVersion::lua51()).into_result()`：错误结果不暴露恢复 AST，不接受补造 token 作为证据。较新方言的 goto／标签、整数除法、位运算符、`<const>`、Luau 类型标注和 continue 有拒绝用例；这些用例说明解析配置边界，不替代游戏执行验证。

## 复现检查

Windows 上从工具箱根执行；K 表示独立知识仓路径。Rust 已安装到当前用户 `.cargo/bin`；本次没有永久改 PATH，可用以下方式加入当前 PowerShell 会话：

```powershell
$env:Path = (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.cargo/bin') + ';' + $env:Path
rustc +1.99.0 --version --verbose
cargo +1.99.0 --version
```

首次复现需要 Rustup 和可用的 x64 MSVC／SDK；项目版本文件不负责安装系统编译组件。Python 环境重建：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r scripts/requirements.txt
```

构建、探针及基准工具检查：

```powershell
cargo test --locked --manifest-path scripts/fullmoon-dst/Cargo.toml --example parser_probe
cargo build --locked --manifest-path scripts/fullmoon-dst/Cargo.toml --example parser_probe
& .\.venv\Scripts\python.exe scripts/tools/verify/verify_parser.py --knowledge-root "<K>"
& .\.venv\Scripts\python.exe scripts/tools/verify/verify_parser.py --knowledge-root "<K>" --syntax-scan
& .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests/python -p test_contract.py
& .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests/python -p test_baselines.py
```

[verify_parser.py](../scripts/tools/verify/verify_parser.py) 默认核对 13 个试点的预期退出状态；`--syntax-scan` 遇到任何覆盖缺口退出 1，所以当前全快照扫描的退出 1 是上述两项明确缺口，不能忽略为全量成功。错误访问或包装失败退出 2；可用 `--source-root / --binary / --output / --workers` 指定复现范围。

报告输出到被忽略的 `<K>/output/preparation/parser-probe.json` 与 `lua-dialect-scan.json`，包含输入和探针二进制哈希；不保存完整 AST，不进入默认知识查询。`.venv`、Cargo `target` 和输出均被忽略，Cargo.lock 与版本说明纳入主项目。

## 下一步

W03 最小语法提取、全快照 facts／报告及源码查询已完成；动态 Class／属性表／值、任意 CFG 与跨文件运行关系保留限制。W04 已用本机 LuaLS 3.19.1 检查 finiteuses／equippable 两份声明、正确用法和三／六处错误，二进制 SHA-256 为 `54dde4e4eec0c4966bb9e1f1d889dbda28f610200a0b1f1db639c8cc2d478f27`；没有下载安装或变更系统 PATH。复现命令与依赖见 [工具箱](../README.md#基准接口与-fork)，范围和回调 ent|nil 检查差异见 [试点验收](../docs/reports/w04/acceptance.md)。W04 已完成，下一步 W05；游戏运行仍未执行；上节 W03 数字保留其历史范围。
