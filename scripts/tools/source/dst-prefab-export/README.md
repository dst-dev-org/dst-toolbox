# DST Wiki Prefab 注册表导出

将 `dst-prefab-export` 文件夹复制到 DST 安装目录的 `mods` 下，在本地测试世界启用这个服务端模组。做原版对账时只启用此模组。进世界后在主模拟端控制台执行：

```lua
c_prefab_catalog()
```

命令从本分片的 Lua 注册表读取数据，向游戏持久化目录写入 `dst-wiki-prefabs-<分片 ID>.json`。控制台报告回读成功时会显示文件名和注册数量。可在 Windows 的 Klei 存档目录下查找该文件。需要区分不同模式或分片的运行环境时，在各自的服务器控制台分别导出。确认 Steam build 后可传入相应编号，作为人工核对的 `snapshot`。`game_version` 保留游戏自身版本号。

## 字段与口径

- `entries[].name` 是实际注册名，`strings_name` 是当前语言中同名 `STRINGS.NAMES` 键的值。动态显示名另查对应实现。
- `source_file` 是本次记录到的实际加载文件。一个共享工厂返回的多个注册按该字段汇总。未观察到加载文件时留空。`factory_source` 仅用于定位构造函数，通用 helper 的函数位置和加载文件可能不同。`mod_root` 标记从模组目录加载的文件。
- `kind` 优先区分皮肤、无 Lua 构造器和后缀线索，其余采用游戏图鉴类型或 `uncategorized`。`scrapbook_type` 保留图鉴分类。后缀、图鉴和名称表都可用于分诊。
- `status=confirmed` 表示在本分片的 `Prefabs` 表中观测到。生成资格、正常玩法可达性、真实组件和完整 Wiki 覆盖仍按各自证据核验。`world` 记录存档实际加载的世界预制物，老版导出的 `world` 可能是各地图共用的实体名。

## 提取与对账

将原始导出放入知识仓 `output/coverage`。磁盘文件可能带有 `KLEI     1 ` 保存头，脚本可直接读取。下方 T 和 K 分别是工具箱与知识仓的实际绝对路径，游戏 build 和分片按实测替换。若导出已记录 Steam build，可省略 `--steam-build`。每次生成使用一个新输出目录。

```powershell
$out = '<K>/output/coverage/prefab-26474873-shard-1'
python -X utf8 -B '<T>/scripts/tools/verify/prepare_prefab_catalog.py' `
  '<K>/output/coverage/dst-wiki-prefabs-1.json' --steam-build 26474873 --output-dir $out `
  --chinese-po '<K>/raw/current/scripts/languages/chinese_s.po' --knowledge-root '<K>'

rg -n '皮弗娄牛|^beefalowool,' "$out/prefab-names.csv"
Import-Csv -LiteralPath "$out/coverage-by-file.csv" |
  Where-Object { [int]$_.matched -gt 0 -and [int]$_.unmatched -gt 0 }
```

- `registrations.json` 保留原始注册字段，过滤导出模组自己的资产标记，可交给 `verify_page_coverage.py --registrations`。其他模组注册随输入保留。
- `prefab-names.csv` 是两列速查表。以简中环境导出时填名称表原值，未命中时留空。
- `--chinese-po` 复用查名脚本的 PO 解析，输出名称差异与对应行号。
- `--knowledge-root` 复用页名与别名匹配，输出按加载文件分组的匹配和未匹配注册，并在 `summary.json` 中列出别名冲突和知识仓源码版本。两版不同时将报告用于分诊。未匹配名中包含皮肤、放置预览和内部对象，排批前按实际角色核验。
- 用可重复的 `--source-file prefabs/plantables.lua` 或 `--prefab dug_berrybush` 限定对账范围，同时使用时取交集。注册总表和名称 CSV 仍生成全量。摘要记录源码快照是否同版以及参与名称对照的 PO SHA-256。
