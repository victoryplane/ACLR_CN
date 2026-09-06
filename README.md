# ACLR_CN · ARMORED CORE LAST RAVEN 简体中文化 —— 教程与工具

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
├── README.md          # 本文档
├── LICENSE            # MIT 许可全文
├── docs/              # 分步技术文档（含「坑与教训」）
│   ├── 01-解包.md
│   ├── 02-文本与编码.md
│   ├── 03-字库与渲染.md
│   ├── 04-回写与压缩.md
│   ├── 05-打包与ISO.md
│   ├── 06-PSS视频.md
│   └── 07-调试与MCP断点.md
└── tools/             # 精选可复用工具脚本
```

## 管线总览

| 阶段 | 文档 | 做什么 | 产出/目标 |
|---|---|---|---|
| 1 | [docs/01-解包.md](docs/01-解包.md) | ISO9660 → AC.BIN → BND → fsliblzs 解压 | 从 ISO 提取全部文本/字库容器 |
| 2 | [docs/02-文本与编码.md](docs/02-文本与编码.md) | SJIS / MAPPING 码 / 容器 id / 文本表 | 可读可改的译文工作台 |
| 3 | [docs/03-字库与渲染.md](docs/03-字库与渲染.md) | ac0_j1 / 0A93 / ID=9 字库、位图、CLUT | 简体字库（自备字体生成） |
| 4 | [docs/04-回写与压缩.md](docs/04-回写与压缩.md) | fslzss 兼容性、等长/变长规则 | 把译文安全写回容器 |
| 5 | [docs/05-打包与ISO.md](docs/05-打包与ISO.md) | 装配、LBA/extent 验证、瘦身前移 | 可启动的汉化 ISO |
| 6 | [docs/06-PSS视频.md](docs/06-PSS视频.md) | PSS(MPEG-PS) 提取/重压/重封 | 视频级汉化 |
| 7 | [docs/07-调试与MCP断点.md](docs/07-调试与MCP断点.md) | AI + 模拟器断点动态逆向 | 破解静态分析到不了的难题 |

建议按 01 → 07 顺序阅读；每篇末尾的「坑与教训」是最值得先看的部分。

## tools/ 精选工具

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

> ⚠️ 压缩器（`fslzss_compress.py`）的自测通过只代表与自己的解压器自洽；游戏是否兼容、
> 哪些数据能重压哪些不能，务必先读 `docs/04-回写与压缩.md` 再使用。
> 字体渲染类工具只处理你**自备**的字体文件，本仓库不含任何字体。

## 前置依赖

- Python 3.x（大多数工具仅标准库；个别工具需要 Pillow / ffmpeg，见各工具顶部注释）
- 正版游戏 ISO（自备）
- 字体文件（自备）
- 文档 07 涉及的模拟器调试能力请读者自行获取对应工具

## 联系

plane &lt;1659323436@qq.com&gt;
