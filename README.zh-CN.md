# ACLR_CN · ARMORED CORE LAST RAVEN 简体中文化 —— 教程与工具

[English](README.md) | **简体中文**

> 本项目是社区汉化研究项目，面向 **ARMORED CORE LAST RAVEN**（PS2）的简体中文化技术路线。
> 本仓库**只包含教程与工具，不含任何游戏文件**。

## 这是什么

一份「如何把一个 PS2 老游戏的文本/字库/视频逆向并汉化」的完整技术笔记与可复用工具集。
内容源自真实项目实践，以 **ACLR** 为对象，但其中的解包、字库、回写、ISO 装配等方法论
对同类 PS2 游戏（FromSoftware 早期 AC 系列）也有参考价值。

## 法律声明

- 本仓库内所有文档与工具采用 **MIT 许可**（见 [LICENSE](LICENSE)），可自由使用、修改、商用，需保留版权声明。
- 游戏版权归原公司（FromSoftware / 原发行商）所有；本项目不包含也不提供任何游戏文件。
- 使用者需**自备正版游戏 ISO**，一切操作请针对自己合法持有的副本进行。
- 字体请自备（例如开源的 [Noto 系列](https://fonts.google.com/noto) 等）；本仓库不提供任何字体文件。
- 本仓库中的方法仅用于学习与研究，请勿用于侵犯他人权益的用途。

## 目录结构

```
ACLR_CN/
├── README.md            # 英文主文档（English）
├── README.zh-CN.md      # 本文档
├── GLOSSARY.md          # 中英术语表（两语言版本共用的译法口径）
├── LICENSE              # MIT 许可全文
├── docs/
│   ├── zh/              # 中文技术文档（01 … 08，含「坑与教训」）
│   └── en/              # 英文技术文档（与 docs/zh 同名）
└── tools/               # 精选可复用工具脚本
```

两个语言版本使用**完全相同的 ASCII 文件名**：切换语言只要把 `docs/zh/` 换成 `docs/en/`。
用 `python tools/check_docs_i18n.py` 可以校验两版是否同步（漏译、数字/地址不一致、链接失效、结构漂移）。

## 管线总览

| 阶段 | 文档 | 做什么 | 产出/目标 |
|---|---|---|---|
| 1 | [01 · 解包](docs/zh/01-unpacking.md) | ISO9660 → AC.BIN → BND → fsliblzs 解压 | 从 ISO 提取全部文本/字库容器 |
| 2 | [02 · 文本与编码](docs/zh/02-text-and-encoding.md) | SJIS / MAPPING 码 / 容器 id / 文本表 | 可读可改的译文工作台 |
| 3 | [03 · 字库与渲染](docs/zh/03-fonts-and-rendering.md) | ac0_j1 / 0A93 / ID=9 字库、位图、CLUT | 简体字库（自备字体生成） |
| 4 | [04 · 回写与压缩](docs/zh/04-write-back-and-compression.md) | fslzss 兼容性、等长/变长规则 | 把译文安全写回容器 |
| 5 | [05 · 打包与 ISO](docs/zh/05-packaging-and-iso.md) | 装配、LBA/extent 验证、瘦身前移 | 可启动的汉化 ISO |
| 6 | [06 · PSS 视频](docs/zh/06-pss-video.md) | PSS(MPEG-PS) 提取/重压/重封 | 视频级汉化 |
| 7 | [07 · 调试与 MCP 断点](docs/zh/07-debugging-and-mcp-breakpoints.md) | AI + 模拟器断点动态逆向 | 破解静态分析到不了的难题 |
| 8 | [08 · 字库容量与 ELF 补丁](docs/zh/08-font-capacity-and-elf-patching.md) | 字库容量上限、存档逐字节取证、ELF 补丁 | 数据全对却个别字坏；扩字库后的根治 |

建议按 01 → 08 顺序阅读；每篇末尾的「坑与教训」是最值得先看的部分。
若你只是**扩了字库就出现「个别字坏、换个场景坏的字又变了」**，可以直接跳到第 8 篇。

**英文版文件名与中文版完全相同**，见 [docs/en/](docs/en/) 与 [README.md](README.md)。

## tools/ 精选工具

每个工具的模块 docstring 为中英双语（先英文，再接「中文说明」），运行期输出（结果 / 警告 / 错误 / 提示）
以英文为主（后面可附简短中文原词）。不带参数运行（或在该脚本支持时加 `--help`）即可看到用法。
少数模块是纯函数库、没有命令行入口（`font_render.py`、`pss_remux.py`），按模块导入使用。

| 脚本 | 用途 | 依赖 |
|---|---|---|
| `fslzss2.py` | fsliblzs 容器解压（LZSS 流，selftest/decompress） | 标准库 |
| `fslzss_compress.py` | fsliblzs LZSS 压缩器 ⚠️ 往返无损≠游戏兼容，见 docs/04 | 标准库 |
| `bnd.py` | BND 归档解析 | 标准库 |
| `test_inner_bnd.py` | 内层 BND 结构自检（依赖同仓 fslzss2） | 标准库 |
| `parse_mes.py` | .mes 对话文本表解析（UTF-16LE 文本区） | 标准库 |
| `extract_pss.py` | 按 LBA/size 清单从 ISO 抽取 .PSS | 标准库 |
| `pss_remux.py` | PSS 重封装公共函数库（仅供 v3 导入；早期变长 pack CLI 已弃用，见 docs/06 坑1） | 标准库 |
| `pss_remux_v3.py` | PSS 重封装器（固定 16KB pack；B9 紧跟内容、尾部 padding 放 B9 之后；可输出 .pss 或写回 ISO） | 标准库 + 同仓 pss_remux |
| `pss_to_mp4.py` | PSS → MP4 转封装 | 外部 ffmpeg（PATH 或 FFMPEG 环境变量） |
| `font_render.py` | 自备字体 → 字形位图渲染（4bpp/灰度量化） | Pillow（fontTools 仅可变字体时可选） |
| `render_atlas.py` | 字形 → 纹理图集排布 | Pillow |
| `savestate_ram.py` | 从模拟器即时存档（`.p2s`）取内存快照，与文件**逐字节比对**（连续差异段判据） | 标准库 + `zstandard`（解 zstd 成员时） |
| `elf_addr.py` | ELF32/MIPS：VA↔文件偏移、`lui`+`addiu` 常量引用定位、常量搬迁补丁生成（只写副本） | 标准库 |
| `pcsx2_crc.py` | 算 / 预测模拟器的 game CRC；改过 ELF 后修复 per-game 设置与补丁的命名 | 标准库 |
| `check_docs_i18n.py` | 校验中英双语文档是否同步（漏译、数字/地址不一致、链接失效） | 标准库 |

> ⚠️ 压缩器（`fslzss_compress.py`）的自测通过只代表与自己的解压器自洽；游戏是否兼容、
> 哪些数据能重压哪些不能，务必先读 [docs/zh/04-write-back-and-compression.md](docs/zh/04-write-back-and-compression.md) 再使用。
> 字体渲染类工具只处理你**自备**的字体文件，本仓库不含任何字体。

## 前置依赖

- Python 3.x（大多数工具仅标准库；个别工具需要 Pillow / ffmpeg / zstandard，见各工具顶部注释）
- 正版游戏 ISO（自备）
- 字体文件（自备）
- 文档 07 涉及的模拟器调试能力请读者自行获取对应工具

## 联系

victory plane &lt;1659323436@qq.com&gt;
