# ACLR_CN · ARMORED CORE LAST RAVEN — Simplified Chinese localization: tutorials & tools

**English** | [简体中文](README.zh-CN.md)

> A community localization research project: the technical roadmap for localizing
> **ARMORED CORE LAST RAVEN** (PS2) into Simplified Chinese.
> This repository contains **tutorials and tools only — no game files whatsoever**.

## What this is

A complete technical write-up plus a reusable toolset answering one question:
*how do you reverse-engineer and localize the text, font libraries and videos of an old PS2 game?*
It comes from real work on **ACLR**, but the methodology — unpacking, font libraries, write-back,
ISO assembly — transfers to other PS2 titles (FromSoftware's earlier Armored Core games in particular).

## Legal

- All documents and tools here are released under the **MIT license** (see [LICENSE](LICENSE)):
  free to use, modify and redistribute, including commercially, as long as the copyright notice is kept.
- Game copyright belongs to the original companies (FromSoftware / the original publisher).
  This project neither contains nor distributes **any game files**.
- Bring **your own legally owned ISO**, and do all of this on your own copy.
- Bring your own font too (for example the open-source [Noto family](https://fonts.google.com/noto)).
  No font files are shipped here.
- The techniques described are for study and research. Do not use them to infringe on anyone's rights.

## Repository layout

```
ACLR_CN/
├── README.md            # this document (English)
├── README.zh-CN.md      # 简体中文说明
├── GLOSSARY.md          # 中英术语表 / terminology shared by both language editions
├── LICENSE              # MIT
├── docs/
│   ├── zh/              # Chinese technical documents (01 … 08)
│   └── en/              # English technical documents (same file names as docs/zh)
└── tools/               # reusable, dependency-light Python scripts
```

Both language editions use the **same ASCII base file names**, so switching between them is
just a matter of swapping `docs/zh/` for `docs/en/`. Run `python tools/check_docs_i18n.py`
to verify the two editions stay in sync (missing translations, mismatched numbers or addresses,
broken links, structural drift).

## Pipeline overview

| Stage | Document | What it does | Result |
|---|---|---|---|
| 1 | [01 · Unpacking](docs/en/01-unpacking.md) | ISO9660 → AC.BIN → BND → fsliblzs decompression | every text / font container extracted |
| 2 | [02 · Text and Encoding](docs/en/02-text-and-encoding.md) | SJIS / MAPPING codes / container ids / text tables | an editable translation workbench |
| 3 | [03 · Fonts and Rendering](docs/en/03-fonts-and-rendering.md) | ac0_j1 / 0A93 / ID=9 font libraries, bitmaps, CLUT | a Simplified Chinese font library |
| 4 | [04 · Write-back and Compression](docs/en/04-write-back-and-compression.md) | fslzss compatibility, equal-/variable-length rules | translations written back safely |
| 5 | [05 · Packaging and ISO](docs/en/05-packaging-and-iso.md) | assembling, LBA/extent validation, slimming and shifting | a bootable localized ISO |
| 6 | [06 · PSS Video](docs/en/06-pss-video.md) | PSS (MPEG-PS) extraction / re-encode / remux | localized videos |
| 7 | [07 · Debugging and MCP Breakpoints](docs/en/07-debugging-and-mcp-breakpoints.md) | driving the emulator from an AI through debug stubs | answers static analysis cannot reach |
| 8 | [08 · Font Capacity and ELF Patching](docs/en/08-font-capacity-and-elf-patching.md) | font capacity ceiling, savestate forensics, ELF patching | fixes "correct data, broken glyphs" for good |

Read 01 → 08 in order; the **Pitfalls and lessons** section at the end of every document is the part
worth reading first. If your only symptom is *"a few glyphs broke after I grew the font library,
and which glyphs break changes from scene to scene"*, jump straight to document 08.

A **Chinese edition with identical file names** lives in [docs/zh/](docs/zh/) — read it in
[README.zh-CN.md](README.zh-CN.md).

## tools/

Every tool's module docstring is bilingual (English first, then 中文说明), and all runtime console
output — results, warnings, errors, hints — is in English (a short Chinese gloss may follow in
parentheses). Run a script with no arguments, or with `--help` where that script supports it, to see
its usage. A few modules are libraries with no CLI entry point (`font_render.py`, `pss_remux.py`):
import them instead of running them.

| Script | Purpose | Dependencies |
|---|---|---|
| `fslzss2.py` | fsliblzs container decompression (LZSS stream; `selftest` / `decompress`) | stdlib |
| `fslzss_compress.py` | fsliblzs LZSS compressor — **optimal-parse encoder by default** (recompressed 5xxxx records fit back into their original slots); `--mode greedy` reproduces the historical encoder byte for byte. ⚠️ a lossless round-trip is **not** game compatibility, see docs/04 | stdlib |
| `bnd.py` | BND archive parser | stdlib |
| `test_inner_bnd.py` | structural self-check of inner BND files (imports `fslzss2`) | stdlib |
| `parse_mes.py` | `.mes` dialogue table parser (UTF-16LE text area) | stdlib |
| `extract_pss.py` | pull `.PSS` files out of an ISO by LBA/size list | stdlib |
| `pss_remux.py` | shared PSS remux helpers (imported by v3; the early variable-length pack CLI is retired, see docs/06 pitfall 1) | stdlib |
| `pss_remux_v3.py` | PSS remuxer (fixed 16 KB packs; `B9` right after the content, trailing padding after `B9`; writes `.pss` or back into an ISO) | stdlib + this repo's `pss_remux` |
| `pss_to_mp4.py` | PSS → MP4 remux | external `ffmpeg` (on PATH or via the `FFMPEG` env var) |
| `font_render.py` | your font → glyph bitmaps (4bpp / grayscale quantization) | Pillow (`fontTools` optional, variable fonts only) |
| `render_atlas.py` | glyphs → texture atlas layout | Pillow |
| `savestate_ram.py` | pull memory snapshots out of an emulator savestate (`.p2s`) and compare them **byte by byte** with a file (contiguous-diff-run criterion) | stdlib + `zstandard` (for zstd members) |
| `elf_addr.py` | ELF32/MIPS: VA ↔ file offset mapping, `lui`+`addiu` constant-reference finder, constant-relocation patch generator (writes a copy only) | stdlib |
| `pcsx2_crc.py` | compute / predict the emulator's game CRC; repair per-game settings and patch file naming after an ELF edit | stdlib |
| `check_docs_i18n.py` | verify the Chinese and English documents stay in sync (missing translations, mismatched numbers/addresses, broken links) | stdlib |

> ⚠️ A passing self-test in `fslzss_compress.py` only proves it round-trips with its own decompressor.
> Whether the game accepts the result — and which data may be recompressed at all — is a different
> question: read [docs/en/04-write-back-and-compression.md](docs/en/04-write-back-and-compression.md) first.
> The font tools only ever process **your own** font files; this repository ships none.

## Prerequisites

- Python 3.x (most tools are stdlib-only; a few need Pillow / ffmpeg / zstandard — see each script's header)
- your own legally obtained game ISO
- your own font file
- the emulator debugging capabilities used by document 07 must be obtained by you

## Contact

victory plane &lt;1659323436@qq.com&gt;
