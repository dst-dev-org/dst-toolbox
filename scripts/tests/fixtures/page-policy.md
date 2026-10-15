# Synthetic validation policy

Only a deterministic test input. Production validators require the actual
installed dst-wiki-skill write-format.md via --format. This is not a maintained
copy of the production policy or a Wiki page.

| 文件类别 | 最多行数 | 最大字节 |
|---|---:|---:|
| 根导航 | 80 | 8 KiB |
| 索引 | 160 | 16 KiB |
| 知识页 | 200 | 16 KiB |
| cookbook | 300 | 24 KiB |

### 源码知识页分档

| size_class | 适用情况 | 最多行数 | 最大字节 |
|---|---|---:|---:|
| `simple` | Single concern | 120 | 8 KiB |
| `standard` | Typical reference | 200 | 16 KiB |
| `complex` | Coupled mechanisms | 400 | 32 KiB |

## 标签

- 测试：component, cookbook, overview, modding
