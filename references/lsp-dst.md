# LSP-dst fork 维护

本仓库的依赖维护参考，仅准备／检查 fork、更新固定引用或复查核验输入时读取。

独立维护仓库为 [YingSP/lsp-dst](https://github.com/YingSP/lsp-dst)，上游为 [b1inkie/lsp-dst](https://github.com/b1inkie/lsp-dst)。使用者直接克隆 fork 默认 master 分支，将 scripts 加入 LuaLS library 即可复用；无需准备 dst-wiki 或应用本地补丁。

固定 pin 对应 W04 的 176 条核验（finiteuses 83／equippable 93），两份声明和正反例已执行 LuaLS 3.19.1／Lua 5.1 检查；全库仍按条目逐步审校，游戏运行未执行。固定版本由 [lsp-dst.json](../scripts/vendor/lsp-dst.json) 记录。运行下文 setup 后，本地可读 fork 的 [维护规则](../scripts/vendor/lsp-dst/MAINTENANCE.md)、[覆盖清单](../scripts/vendor/lsp-dst/reviews/coverage.json)、reviews/components 与 tools/check_reviews.py。尚未克隆时查看 [线上维护规则](https://github.com/YingSP/lsp-dst/blob/master/MAINTENANCE.md)；版本核验使用 pin 指定内容。

2026-10-11 已发布 `1db05561ea6ea271093ea780b60d49e7499baf40`，主项目固定引用同步，维护工作树干净；setup／check 及两份声明重新导出检查通过。完整交付见 [两份试点验收](../docs/reports/w04/acceptance.md)，局部类型检查记录在 fork reviews/luals-validation.json，库级 luals_checked 保持 false，不把两份检查当全库验证。逐项证据用 fork `tools/check_reviews.py`；导出用法见 [工具箱](../README.md#基准接口与-fork)。

## 主项目引用

- scripts/vendor/lsp-dst.json 格式 v2 固定 fork URL、分支、完整 commit 及上游基线。
- scripts/vendor/lsp-dst 是被主项目忽略的独立 Git 克隆，origin 指向 fork，upstream 指向原仓库。
- 配置在克隆目录旁，纳入主仓库且不受克隆目录的忽略规则影响；重新克隆时仍能恢复固定版本。主项目的使用与维护说明在本文件，fork 内的规则由独立库维护。
- 正式核验补充、来源文件哈希与覆盖清单统一在 fork 的 reviews/ 维护，Wiki 和未来生成工具直接消费固定 commit 下的同一份输入；不在两仓库重复手改。
- W01 examples 继续固定原始上游字节作为历史对照，不改成维护工作树哈希。

```powershell
python scripts/tools/maintenance/maintain_lsp_dst.py setup --knowledge-root "<K>"
python scripts/tools/maintenance/maintain_lsp_dst.py check --knowledge-root "<K>"
```

setup 克隆 fork 并定位固定 commit。已有目录时只检查，不覆盖、reset 或自动追踪远程最新版本。check 核对固定 commit、干净工作树、远程来源与逐项证据；检查源码字节需要当前 raw/current/scripts 与对应 BUILD.txt。独立使用注解不需要 raw，只有源码复查才需要。

## 修改与发布

先在 fork 更新 reviews 的条目和证据，再修改注解与覆盖文件哈希。执行 fork 检查工具并审阅差异，提交到独立库，将已授权发布的修订推送至 origin/master。

发布后的新 commit 可用 `python scripts/tools/maintenance/maintain_lsp_dst.py pin --knowledge-root "<K>"` 更新 dst-wiki 的固定引用。pin 要求工作树干净、证据通过且该 commit 已出现在 fork 远程 master 历史中；不自动提交或推送。主项目保持原暂存区，由使用者保存引用变更。

上游更新先 fetch 与差异审阅，在独立库合并并复查受影响条目。上游 push URL 保持 DISABLED；所有维护发布走 origin。改变上游基线时，同步 fork 覆盖清单和主项目 pin metadata 后检查，不能无声批量改核验 build。

原补丁维护已迁移为 fork + commit，许可证和正式核验输入保留在 fork，数据格式使用 W01 的 1.0.0。主项目 pin metadata 的版本 2 表示引用方式，与接口数据格式版本分别解释。

## 历史样例核对

W01 bundle 的外部来源仍固定在原始上游 commit，不能用修订后的 fork 工作树代替。需要重查时，从 bundle 的 `manifest.sources` 读取该来源的实际 revision 和文件清单，在包含此提交的本地克隆中用 `git show <commit>:<path>` 导出原始字节到临时目录，保持来源内的相对路径，再执行：

```powershell
python scripts/tools/verify/validate_examples.py --source-root "lsp-dst=<历史注解临时根目录>"
```

导出文件时使用二进制读写（如 Python `subprocess.check_output` 与 `Path.write_bytes`），避免 PowerShell 文本管道或编码转换改变哈希；不切换或覆盖维护工作树。游戏来源默认使用 `raw/current/scripts/`；快照不匹配时另用 `--source-root "dst=<历史游戏 scripts 根目录>"`，并在该目录父级保留对应 `BUILD.txt`。
