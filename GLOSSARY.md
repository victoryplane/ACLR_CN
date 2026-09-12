# GLOSSARY · 术语表 / Terminology for the Chinese ↔ English documentation

> 本文件是中英双语文档的**唯一译法口径**。写/改任何一篇英文文档前先读它；
> 术语表中已有的词必须照用，不得另创译名。
> This file is the single source of truth for terminology in the bilingual docs.
> Read it before writing or editing any English document; never invent a different term.

## 0. 硬性规则 / Hard rules for translation

1. **数字逐字不变。** 所有十六进制数、十进制数、地址、常量、字节序列、文件名、路径、命令行
   必须与中文原文**逐字符相同**（`0x29000`、`0x1C03150`、`FEBE1992`、`SLPS_254.62`、
   `50 C1 A5 24`、`tools/elf_addr.py`…）。不许四舍五入、不许改格式、不许省位数。
   *All numbers, addresses, constants, byte strings, file names, paths and command lines must be
   reproduced verbatim. Never reformat, round or drop digits.*
2. **结构一一对应。** 标题的层级与顺序、表格的行列数、代码块个数、列表项数量、引用块用法
   都必须与中文版一致。
   *One-to-one structure: heading order and depth, table rows/columns, code-block count, list items,
   blockquote use.*
3. **代码块**：中文**注释**译成英文；代码本体（标识符、字面量、格式）与 ASCII 示意图**逐字符保持**，
   不要重新对齐或换行。
   *Code blocks: translate Chinese comments; keep code tokens and ASCII diagrams byte-identical
   (do not re-align or re-wrap).*
4. **不增不减**技术点：不合并、不拆分、不概括、不删章节；「坑与教训」每一条都要有对应的一条。
   *No added, merged, split, summarized or omitted technical points.*
5. **链接**：英文版的篇内互链指向 `docs/en/` 下的同名文件（与中文版基名相同），
   例如 `[05 · Packaging and ISO](05-packaging-and-iso.md)`。
   *Intra-doc links point to the sibling file in `docs/en/` with the same ASCII base name.*
6. **语气**：面向逆向/汉化同行的直接、务实技术写作；直译优先于意译，但英文必须通顺。
   不要为了顺溜丢掉限定词（「实测」= *measured in practice*、「约」= *approximately*、
   「本项目」= *this project*）。
7. **占位符可以译，真名不能译。** 文档里由使用者自己提供的示例文件名/路径
   （如「编辑后的画面.mkv」）**可以**换成英文占位名（`edited_video.mkv`）；
   但**游戏与仓库里真实存在的文件名、路径、选项、字段名必须逐字保留**
   （`AC.BIN`、`font.bnd`、`0A93`、`eeMemory.bin`、`.p2s`、`tools/…`、`--from` 等）。
   *Placeholder names supplied by the reader may be localized; real file names, paths, options and
   field names stay verbatim.*
8. **术语表里没有的词**：直接用你判断的英文，并在该篇里保持一致；
   如属重要概念，请在交付说明里点出来，便于补进本表。
   *Words missing from this glossary: pick a sensible English term, keep it consistent within the
   document, and mention it in your hand-off so it can be added here.*

## 1. 八篇文档的英文标题 / Titles of the eight documents

文件基名两语言相同（ASCII），放在 `docs/zh/` 与 `docs/en/` 下。

> 下表给的是**简称**。实际 H1 保留原中文标题的副标题（冒号之后那半句），
> 例如 `# 02 · Text and Encoding: SJIS, MAPPING codes and text tracing` 对应
> `# 02 · 文本与编码：SJIS、MAPPING 码与文本追踪`。文件名的数字前缀与短横线写法见下表左列。

| 基名 / file | 中文标题 | English title |
|---|---|---|
| `01-unpacking.md` | 01 · 解包 | 01 · Unpacking: ISO → AC.BIN → BND → fsliblzs |
| `02-text-and-encoding.md` | 02 · 文本与编码 | 02 · Text and Encoding |
| `03-fonts-and-rendering.md` | 03 · 字库与渲染 | 03 · Fonts and Rendering |
| `04-write-back-and-compression.md` | 04 · 回写与压缩 | 04 · Write-back and Compression |
| `05-packaging-and-iso.md` | 05 · 打包与 ISO | 05 · Packaging and ISO: Assembling a Bootable Image |
| `06-pss-video.md` | 06 · PSS 视频 | 06 · PSS Video |
| `07-debugging-and-mcp-breakpoints.md` | 07 · 调试与 MCP 断点 | 07 · Debugging and MCP Breakpoints |
| `08-font-capacity-and-elf-patching.md` | 08 · 字库容量与 ELF 补丁 | 08 · Font Capacity and ELF Patching |

## 2. 固定章节名 / Mandatory section names

| 中文 | English |
|---|---|
| 背景与目标 | Background and goal |
| 前置依赖 | Prerequisites |
| 坑与教训 | Pitfalls and lessons |
| 衔接其他文档 | Related documents |
| 现象 | Symptom |
| 根因 | Root cause |
| 规避 | How to avoid |
| 教训 | Lesson |
| 实测 | measured (in practice) |
| 已排除 / 排除 | ruled out |
| 判据 | criterion |
| 主判据 | primary criterion |

### 2.1 标题编号与交叉引用 / Heading numbering and cross-references

| 中文写法 | 英文写法 |
|---|---|
| `## 一、二、三、` | `## 1.` `## 2.` `## 3.`（阿拉伯数字 + 点） |
| `## 第 N 步：…` | `## Step N: …` |
| 中文标题本身不带编号（如 05、07 篇） | 英文同样不加编号 |
| `### 3.1 / 4.2` 子节 | 原样保留 `### 3.1 / 4.2` |
| 篇内引用「第八节」 | "section 8" |
| 跨篇引用「见 03 §八」 | "see 03 §8" |

### 2.2 工具输出语言 / Language of tool output

`tools/` 下的脚本统一约定：**运行期输出（结果 / 警告 / 错误 / 提示）以英文为主**（可在括号内附中文原词，便于中文读者对照），
`--help`（若该脚本有）为英文，docstring 中英双语（先英文，再 `中文说明`）。
因此文档里引用工具输出时**照抄英文原文**——中文版与英文版**引用同一段英文输出**，
理由与代码块相同：那是程序输出，不是叙述文字。

## 3. 术语对照 / Term table

### 3.1 字库与渲染 / Fonts and rendering

| 中文 | English | 说明 |
|---|---|---|
| 字库 | font library | 一整套字形容器（`0A93`、`ac0_j1`、`ID=9`） |
| 字形 | glyph | 单个字的位图块 |
| 字形槽 | glyph slot | 字形在字库里的槽位（0 起） |
| 位图 | bitmap | |
| 位图区 | bitmap region | |
| 区间表 | range table | 码点区间 → 槽位 |
| 字形表 | glyph table | 每字 24 B 的 UV/tail/宽高条目 |
| 页表 | page table | |
| 头 / 头部 | header | |
| 纹理描述符 / texdesc | texdesc | 保留原文 |
| 调色板 / CLUT | CLUT | 保留 CLUT |
| 交错布局 / 线性布局 | interleaved layout / linear layout | |
| 变宽（比例字体） | proportional | |
| 固定宽 | fixed-width | |
| 槽位数 / 字形数上限 | glyph capacity | |
| 惰性单槽上传 | lazy single-slot upload | |
| 采样 | sampling | |
| 渲染 | rendering | |
| 解码 | decode | |
| 上传 | upload | |
| 顶对齐 / 基线 | top-aligned / baseline | |
| 质心居中 | centroid centering | |
| 发糊、重影 | blurry, ghosting | |
| 融化（全体字形错乱） | melted / garbled | |
| 串位 | shifted / misaligned | |
| 缺笔画 | missing strokes | |
| 笔画 | stroke | |
| 全角 / 半角 | fullwidth / halfwidth | |

### 3.2 容器、文件与镜像 / Containers, files and images

| 中文 | English | 说明 |
|---|---|---|
| 容器 | container | BND 等 |
| 归档 | archive | |
| 子文件 | subfile | |
| 目录槽 / 条目 | directory slot / entry | |
| 空闲区 | free space / free region | |
| 孤儿区 | orphan region | 无条目引用的死数据区 |
| 死数据 | dead data | |
| 落点 | placement | 数据写到哪个 LBA/offset |
| 扇区 | sector | |
| 高位偏移 | high offset | |
| 上限 | ceiling / limit | |
| 装配 | assembling | |
| 瘦身 | slimming | 缩小镜像体积 |
| 前移 | shifting forward | 删除死数据后整体前移 |
| 回写 / 回填 | write-back | |
| 等长 / 变长 | equal-length / variable-length | |
| 压缩 | compression | |
| 解压 | decompress | |
| 资源 | asset | |
| 主程序 / ELF | main executable / ELF | |
| 程序头 | program header | |
| 段（LOAD 段） | segment | |
| 虚拟地址（VA） | virtual address (VA) | |
| 文件偏移 | file offset | |
| 加载地址 | load address | |
| 基址 | base address | |
| 末尾常量 | end constant | |
| 预留区 / 缓冲区 | reserved area / buffer | |
| 容量 | capacity | |
| 溢出 / 越界 | overflow / out of bounds | |
| 覆盖 | overwrite | |
| 搬迁 | relocation | 把数据搬到别处 |
| 空洞（段外 RAM） | hole (RAM outside any segment) | |

### 3.3 文本与本地化 / Text and localization

| 中文 | English | 说明 |
|---|---|---|
| 汉化 / 中文化 | (Simplified) Chinese localization | |
| 译文 | translation | |
| 语料 | corpus | |
| 码位 / 码点 | code point | |
| 区间 | range | |
| 全宽 / 半宽（标点） | fullwidth / halfwidth | 标点 |
| 断句 / 换行 | line breaking | |
| 译名 | translated term / name | |
| 校对 | proofreading | |
| 工作台 | workbench | 译文工作台 |
| 测试者 | tester | |
| 反馈 | feedback | |
| 任务 | mission | |
| 机库 / 机库界面 | garage | |
| 部件 | part | |
| 属性页 | attribute page | |
| 界面 / 菜单 | screen / menu | |
| 名单 | roster | |
| 对话 | dialogue | |
| 系统消息 | system message | |
| 结局 / 开场 | ending / opening | 视频 |
| 奖励 | reward | |

### 3.4 调试与逆向 / Debugging and reverse engineering

| 中文 | English | 说明 |
|---|---|---|
| 逆向 | reverse engineering | |
| 反汇编 | disassembly | |
| 指令 | instruction | |
| 立即数 | immediate | |
| 寄存器 | register | |
| 断点 / 条件断点 | breakpoint / conditional breakpoint | |
| 命中 | hit | 断点命中 |
| 帧步进 | frame stepping | |
| 即时存档 | savestate | `.p2s` |
| 存档槽位 | save slot | |
| 纹理转储 | texture dump | |
| 显存 | VRAM | |
| 主存 / EE RAM | main RAM / EE RAM | |
| 逐字节比对 | byte-by-byte comparison | |
| 连续差异段 | contiguous diff run | |
| 判据 | criterion | |
| 补丁（内建补丁） | patch (built-in patch) | `.pnach` |
| 序列号 | serial | `SLPS-25462` |
| 模拟器数据目录 | emulator data directory | |
| 调试桩 | debug stub | GDB 调试桩 |

## 4. 第一轮翻译中新增/确认的术语 / Terms settled during the first translation pass

> 这些词是在八篇译文里实际用到的口径，后续修改请沿用；新文档请优先查这一节。
> Titles in §1 are the short form; documents may carry a subtitle after a colon
> (`02 · Text and Encoding: SJIS, MAPPING codes and text tracing`), matching the Chinese H1.

| 中文 | English | 备注 |
|---|---|---|
| 双端序 | both-endian | ISO9660 的 extent/size 双写；动词短语用 "in both byte orders" |
| 卷空间大小 | volume space size | ECMA-119 对 PVD 偏移 80 字段的叫法 |
| 回读 / 回读比对 | read back / read-back comparison | |
| 大条目 | large entry | `AC.BIN` 顶层 BND 里体积很大的子文件 |
| 条目表 / 子指针表 | entry table / sub-pointer table | |
| 文本区 | text region | `.mes` 里的 UTF-16LE 文本区 |
| 控件标识符 | control identifier | |
| 按键提示 | button prompts | 也可 "key guide"（对应文件名 `keyguide`） |
| 渡鸦名单 | Raven roster | 文件名 `RankerInfo`/`RavenInfo` 保留原文 |
| 战况报告 | mission report | |
| 说话人行 / 说话人名 | speaker line / speaker name | |
| 键位演示 / 邮件演示 | key configuration demo / mail demo | 菜单里的演示视频 |
| 装配脚本 | assembly script | |
| 装载 / 加载 | load | 装载函数 = load function；装载链 = load chain |
| 斜切 | shear | 刻意不用 "skew"（避免与纹理/字形度量混淆） |
| 现场 | the scene / in place | 运行时现场 = the runtime scene |
| 正文 | body | 文本载荷主体 |
| 落码 | assign the code | 与「落点 = placement」区分 |
| 唯一性确认 / 三方确认 | confirm uniqueness / three-way evidence | |
| 嵌套（大条目里再嵌一层） | nesting (another layer inside a large entry) | |
| 第 N 步（文档标题） | Step N: … | 08 篇之外的步骤式文档统一用 "Step N" |
| 验证三件套 | verification trio | |
| 区间不相交断言 | range non-intersection assertion | |
| 可回收的覆盖目标 | a reclaimable overwrite target | |
| nibble / window / 回引 token / 结束标记 | nibble / window / back-reference token / end marker | LZSS 语境，nibble 不译 |
| 判决性证据 | decisive evidence | |
| 全绿 / 反向验证 | all green / reverse verification | |
| 实机 | real hardware | 与「模拟器里」相对 |
| 一刀切（到底） | cuts cleanly (runs to the end) | 形容差异从某偏移起一路到底 |
| 屋子 / 肚子（比喻） | the room the game left for it / belly | 保留比喻，不要改成中性说法 |
| 字形格描述字 | glyph cell descriptor | |
| 位图基址 | bitmap base (address) | 英文文档里两种写法都出现过，二者均可 | |
| 振铃 / 粘连 / 发毛刺 | ringing / blobbing / fringed | 渲染质量语境 |
| 就地覆盖 | overwrite in place | |
| 原版（未改动的零售版） | the original / the original version / the original (retail) | 三种写法均可用 | |
| 入场名字库 | entry-name font library | 32×32 竞技场入场名那套 |
| 解复用 / demuxer | demux / demuxer | 不译 demuxer |
| 重压（画面） | re-encoding | 与「重封装 = remux」区分 |
| 真缩短模式 | genuine shortening mode | 与等长模式相对 |
| 本仓 | this repository | 本作/本项目 = this project |

## 5. 保留原文不译 / Keep as-is

`BND`、`fsliblzs`、`fslzss`、`PSMT4`、`4bpp`、`CLUT`、`texdesc`、`tail`、`ID=9`、`0A93`、
`ac0_j1`、`ac0_j6`、`AC.BIN`、`font.bnd`、`SLPS_254.62`、`SLPS-25462`、`GameDB`、`pnach`、`MCP`、
`GDB`、`PSS`、`MPEG-PS`、`LBA`、`ISO9660`、`PVD`、`extent`、`SJIS`、`MAPPING`、`UTF-16LE`、
`PCSX2`、`PS2`、`ACLR`、`ARMORED CORE LAST RAVEN`、`.p2s`、`eeMemory.bin`、`zstd`、`ELF`、
以及所有工具文件名与命令行。
