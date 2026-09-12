# 03 · Fonts and Rendering

> This document answers one question: how Chinese characters in a PS2 game are actually "drawn", and how — without touching the game's rendering code — to stuff Simplified Chinese glyphs produced from your own font into the game's existing font libraries so that they display correctly along the game's existing decode, upload and sampling chain.

## Background and goal

Text rendering in ACLR (ARMORED CORE LAST RAVEN) is not OS-level TrueType rendering; it is several sets of **bitmap font libraries** built into the game: every character is pre-rasterized into a small bitmap, and at runtime the game looks up the table by character code, fetches the bitmap, uploads it to VRAM and samples it to draw. What the localization has to do is not "swap the font engine", but:

1. Reverse engineer the **file structure** of each font library (header, range table, glyph table, bitmap region, CLUT).
2. Use your own font to render the needed Simplified Chinese glyphs into the **bitmap format** the game expects (4bpp indexed pixels + a specific arrangement).
3. **Append or overwrite** the new glyphs into the font library, while honouring the game's hard constraints on alignment, size and offsets.

Target output: one font library that covers the characters used in Simplified Chinese, whose glyphs are crisp on real hardware and whose look matches the rest of the interface.

## Prerequisites

- A legitimate game image (bring your own), plus the font library containers extracted as described in [01 · Unpacking](01-unpacking.md) (`font.bnd` inside `AC.BIN`, and `0A93` in the top-level archive).
- Python 3 + Pillow: Pillow's FreeType backend handles rasterizing TTF/OTF into grayscale images.
- A Chinese sans-serif (heiti) font of your own (for example the open-source Noto family; this tutorial does not supply — and does not recommend — any particular font file).
- Basic concepts: the PS2 GS **4bpp indexed texture (PSMT4)** and the **CLUT (palette)** — pixels store an index from 0–15 and the real colour comes from a CLUT lookup.
- For encoding background see [02 · Text and Encoding](02-text-and-encoding.md): SJIS, MAPPING codes (hand-made high code points), UTF-16LE.

## 1. Overview of the font library system

The game has three main font libraries, with different encodings and bitmap formats; they cannot be mixed:

| Font library | Use | Encoding | Bitmap cell | Key features |
|---|---|---|---|---|
| `ac0_j1` | Garage / menus / system messages / roster / mission list | SJIS → glyph slot | 512B per row = 32×32 PSMT4 | **proportional** (8px/16px), **interleaved layout**, `tail×512` addressing |
| `0A93` | In-mission dialogue | Unicode range → glyph slot | 128B per glyph = 16×16 4bpp | **fixed-width**, linear layout, **16-byte alignment** |
| `ID=9` (internally called `ac0_j6`) | TUNE parameter labels / attribute page labels | MAPPING codes + natural SJIS | 128B per glyph = 16×16 4bpp | small font library; appending requires **pad alignment** and **syncing size in three places** |

Both `ac0_j1` and `ID=9` are subfiles inside `font.bnd` (`ac0_j1` is subfile 0, `ID=9` is subfile 9); `0A93` is a standalone font library container in the top-level archive.

## 2. Common structural skeleton: header, range table, glyph table

These font libraries share the same "`.fnt`-style" skeleton; only the semantics of a few fields differ. Taking `ac0_j1` as the example:

```
0x00  ver   = 0x0101
0x04  size  = total bytes of the whole library
0x0E  rows  = number of bitmap rows(each row 512B)
0x10  pages = 1(only one texture page)
0x12  flags = 0x02(bit0=0 → variable-width/proportional)
0x40  range table(8B per entry)
0x250 glyph table(24B per entry)
0x14280 glyph cell descriptor = 0x55408000(PSMT4 size/format)
0x142D0 bitmap region(512B per row)
```

`0A93`'s header fields are similar, but its offsets are given through pointer fields:

```
0x0A  range count n
0x0C/0x0E  glyph count g
0x10  pages = 1
0x12  flags = 0x03(fixed-width)
0x20  range table pointer = 0x40
0x24  glyph table pointer
0x28  texdesc(112B,texture descriptor)
0x30  bitmap pointer
0x34  pitch = 128(bytes per glyph)
```

Two common entry formats:

- **Range entry (8B)**: `[start u16][end u16][first glyph slot u16][reserved u16]`. Its purpose is to map a contiguous run of code points onto a contiguous run of glyph slots.
- **Glyph entry (24B)**: `[u0,v0,u1,v1 four floats(UV)][width u16][height u16][tail u16]`. `tail` is the key field for locating the bitmap.

The decode chain (taking `ac0_j1` as the example):

```
character code → binary-search the range table → glyph slot g → the tail in the glyph entry → row number
      → bitmap base address + tail×512 → upload to VRAM → sample and draw by UV
```

## 3. Structural details of the three font libraries

### 3.1 `ac0_j1`: a proportional font (not fixed 16×16)

This is the one most easily misjudged. `ac0_j1` has `+0x12 = 0x02`, so it is a **proportional/variable-width font**: one 512B row (a 32×32 texture) is laid out on an 8px grid with a **variable number of glyphs**, rather than a fixed 4 per row of 16×16.

UV steps measured in practice:

- U steps: `0 / 0.25 / 0.5 / 0.75 / 1.0` (4 columns, 8px grid)
- V steps: `0 / 0.5 / 1.0` (2 rows, 16px)
- Width distribution (845-glyph sample): **770 glyphs 16px wide + 75 glyphs 8px wide**, height uniformly 16px

The number of glyphs per row is likewise not fixed: measured in practice there are rows with 1, 2, 3, 4 and even 6/7/8 glyphs. For example, the row with `tail=0` is "1 16px glyph (occupying 2 columns) + 6 8px glyphs", 7 glyphs in total.

**Conclusion**: for `ac0_j1`, you must not assume "4 16×16 glyphs per row in four quadrants". The four quadrant UV values happen to coincide with 16px glyphs, but the bitmap arrangement rule is entirely different.

### 3.2 `0A93`: fixed-width 16×16, Unicode ranges

`0A93` is a fixed-width font library: each glyph is 16×16 @4bpp = 128B, located by `bitmap + tail×128`, with UV always `(0,0,1,1)`. It maps directly through a Unicode range table (dialogue text is written back as UTF-16LE); the original has 671 ranges / 877 glyphs.

**The glyph capacity ceiling is not 877 — but nor can you "expand it freely"**: the upload is a **lazy single-slot upload** — at render time only the current 16×16 glyph is uploaded into a fixed VRAM slot, independently of the total texture height, so the **VRAM side** will not overflow just because there are more glyphs. To expand to 1000+ glyphs you must satisfy **both** constraints **at the same time**: **16-byte alignment** (section 8) and **not exceeding the RAM buffer the game reserves for this font library** (section 9, and [08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md)). Satisfy only the former and you fall into the pit of "a few characters break, and which ones break changes with the scene".

### 3.3 `ID=9`: the small TUNE label font library

Subfile 9 of `font.bnd`, responsible solely for TUNE parameter labels and attribute page labels. Key points:

- The header `+0x08 = 0x10` (glyph width 16) is a **fixed field that must be preserved as-is when rebuilding**.
- Range table 8B per entry; glyph table 24B per entry (`tail` at `+22`).
- Bitmap linear 4bpp, located by `bitmap + tail×128`; **`tail` is the bitmap row number, not the glyph index** (in the original small font library the tails themselves are out of order).
- CLUT at page table `+0x30`, 16 entries × 4B, **out-of-order** nibble→alpha.
- Layout order: `header 0x40 + range table + glyph table + page table 0x10 + texdesc 0x20 + CLUT 0x40 + bitmap (128B×n)`; **the data following the page table must be 16-byte aligned**.

## 4. Bitmap: interleaved layout vs linear layout

**This is the core of the "glyph shifted/split" class of bugs**; the two layout rules must not be mixed.

### 4.1 Linear layout (`0A93`, `ID=9`)

4bpp packs 2 pixels per byte, **low nibble = left pixel** (even column), high nibble = right pixel. Pseudocode for writing a pixel:

```python
def set_px(block, x, y, v):
    # 16x16, 8 bytes per row
    bi = y * 8 + x // 2
    if x % 2 == 0:
        block[bi] = (block[bi] & 0xF0) | v        # left pixel → low nibble
    else:
        block[bi] = (block[bi] & 0x0F) | (v << 4) # right pixel → high nibble
```

Note: write the high and low positions the wrong way round and the glyphs come out **mirrored or broken**; this is a common pitfall.

### 4.2 Interleaved layout (`ac0_j1`)

Each row of `ac0_j1` is 512B = 32×32 PSMT4, in an **interleaved** arrangement:

```
16 bytes per row = [left 16px 8B][right 16px 8B]
upper 16 rows = [col0|col1]      lower 16 rows = [col2|col3]
byte order = col0r0 col1r0 col0r1 col1r1 ... col0r15 col1r15
         col2r0 col3r0 col2r1 col3r1 ... col2r15 col3r15
```

That is, "the left and right columns alternate row by row" rather than the linear style of "col0 as 128B contiguous, then col1 as 128B contiguous". The byte-level addressing formula (4bpp PSMT4 interleaved):

```
block_offset = 0x142D0 + tail*512 + half*256 + i*16 + (col%2)*8
half = 0 if col < 2 else 1     # upper / lower half: col 0/1 upper, 2/3 lower
col  = int(u0*4)               # the column this glyph sits in, 0..3 (8px grid: U steps 0/0.25/0.5/0.75)
                               # a 16px-wide glyph spans two adjacent columns; take its left one
i    = 0..15                   # the 16 rows within a row: 16 bytes each = two 8-byte lanes
```

> Two easy mistakes: (1) `half*256` already accounts for the upper/lower half, so the within-column and, when sampling, the bytes of neighbouring glyphs are read crossing into one another, which shows up as **the top and bottom halves of the glyph shifted and vertically squashed**.

## 5. CLUT palette and "out-of-order"

A 4bpp pixel stores an index from 0–15, and the final colour is `RGBA(128,128,128, ALPHA[v])`, where `ALPHA` is the 16-entry table that ships with the font library. For example, the alpha table of `0A93`:

```
ALPHA = [0,0,51,59,16,128,85,59,24,111,103,93,119,8,69,34]
```

**The biggest pitfall is that the CLUT is not a linear "the bigger the index, the brighter" gradient — it is out of order.** On a 32×32 entry-name font library, reverse-engineered pixel by pixel from a PCSX2 texture dump, the real nibble→(brightness, alpha) mapping comes out as:

```
0:(0,0)   1:(255,128)  2:(224,96)  3:(32,0)   4:(64,32)
5:(192,96) 6:(160,64)  7:(128,64)  8:(96,32)  9:(32,32)
10:(160,96) 11:(96,64)
```

Key facts:

- The alpha of the white core `nib1` is **128 (semi-transparent)**, not 255.
- The alpha of `nib3` is **0 (fully transparent)**.
- The brightness of `nib2~11` is **out of order**: `2 > 5 > 10 > 6 > 7 > 11 > 8 > 4 > 9 > 3`.

Consequence: if you preview with "a 16-level smooth ramp you imagined", the preview looks fine while real hardware comes out greyish and fringed. The correct approach is: **reverse-engineer the real CLUT from a game texture dump, then quantize by nearest match against the CLUT's RGB brightness** (below the threshold counts as transparent). Pseudocode for grayscale→nibble quantization:

```python
def quantize(gray):
    a = gray                          # 0..1
    target = round(min(1.0, a ** gamma) * 128)  # gamma controls stroke weight
    nib = nearest(target, CLUT_BRIGHTNESS)       # nearest by brightness, not by index
    return nib
```

## 6. Rendering chain and sampling

The sampling parameters of the two main font libraries differ; confirmed at machine-code level:

- **`ac0_j1`**: the glyph cell descriptor `0x55408000` decodes to **U_scale=32, V_scale=2**; the sampling coordinates are `U = 2.0 + u0*32`, `V = 2.0 + v0*2` (the `+2.0` is padding). 4 8px columns in U and 2 rows in V — exactly the signature of a proportional font. (The older conclusion "U=V=32" was a miscalculation.)
- **`0A93`**: **U_scale=V_scale=16**, UV always `(0,0,1,1)`, sampling a whole 16×16 cell (offset `+2.0`), never overwritten at runtime; the upload is a **lazy single-slot upload** (the glyph goes up to VRAM `0x3A60`, the CLUT 8×2 goes up to `0x3FC0`).

`ac0_j1`'s tail→bitmap function carries a bounds check (`tail < row count`) and returns `bitmap base address + tail×512`; the renderer then uses the glyph-table UV to locate the col/half within the row.

## 7. Replacement workflow (pseudocode)

The complete "own font → font-library glyph" workflow laid out:

```python
# 1. Collect the character set: the characters the translation actually uses + all of ASCII + the fullwidth/symbol characters needed
chars = collect_chars()

# 2. Render glyph by glyph: rasterize in a 32px em fullwidth box → grayscale (do not crop the ink)
#    Optional: 2×2 box-average downscale to the target cell; when you need bolding use "take max over several subpixel offsets" rather than an outline
for ch in chars:
    gray = render_32px(ch)            # FreeType rendering
    gray = box_downsample_2x2(gray)   # 2:1 box average, avoids LANCZOS ringing
    # 3. Contrast curve: gray = gray ** gamma(a gamma slightly above 1 tightens the strokes)
    # 4. Quantize: grayscale → nearest match against the real CLUT brightness → nibble
    block = pack_4bpp(gray, layout)   # layout = 'linear' or 'interleaved'
    glyphs.append(block)

# 5. Rebuild the range table (sort by code point, merge contiguous ranges) + the glyph table (UV/tail/width/height)
# 6. Compute the bitmap offset, padding after the glyph table to 16-byte alignment when necessary
# 7. Sync every size field (header, directory entry, path table entry)
# 8. Overwrite/append in place, keeping the total size of the containing container and of the whole image unchanged
```

Among these, "no shadow" and "no outline" are the key to a consistent look: an outline thickens strokes and at low resolution easily fills in the gaps between strokes (blobbing), which is especially visible at small sizes.

## 8. 16-byte alignment: unaligned → all glyphs melt

`0A93`'s texdesc / CLUT / bitmap are uploaded by the game with **DMA** and must be **16-byte aligned**. When they are unaligned, the data itself is entirely correct, but after upload **all glyphs are garbled and melted**.

The key formulas (`0A93`):

```
bitmap offset = 0x40 + n*8 + g*24 + 112
mod16    = 8*(n + g) mod 16
```

Because `8*(n+g) mod 16` depends only on the parity of `n+g`:

> **The bitmap is 16-aligned only when the "range count n" and the "glyph count g" have the same parity.**

The original 671 ranges / 877 glyphs (both odd) → aligned; whereas "822 ranges / 877 glyphs" (different parity) → unaligned → broken. The fix: insert `pad = (-texdesc_off) % 16` bytes after the glyph table (it can only ever be 0 or 8 bytes) and correct the texdesc's relative pointers accordingly. Data anchors:

- Original: 671 ranges / 877 glyphs, bitmap `@0x67E0` (16-aligned).
- After the fix: 822 ranges / 877 glyphs, bitmap `@0x6CA0` (aligned after adding 8 padding bytes).

**Lesson**: when changing a binary format, "the data is correct ≠ it runs". Characters right, glyphs right, ranges right, CLUT right — miss only the byte alignment and everything breaks. When investigating "the data is all correct yet it breaks", check **alignment / bounds / parity** first.

## 9. The third constraint: capacity — the glyph count must not exceed the RAM buffer the game reserves

At runtime `0A93` is loaded to a **fixed RAM address**, and **immediately after it sits the engine's own data**: the space left for the font library is finite.
Once the font library overruns it, **the part of those glyphs that crosses the boundary is living in the engine's RAM**, gets overwritten by the data the engine writes every frame, and at upload time the **already-polluted RAM** is faithfully copied into VRAM.

Its symptom is highly characteristic: **it is not the whole library that breaks, but "those glyph slots past the boundary", and which characters break changes with the scene**
(who gets overwritten and with what while on the same screen depends on what the engine happened to write into that memory at the time).

Capacity estimate (work it out before you start expanding the font library):

```
max glyph count ≈ (font library end constant − font library load address − bitmap offset) / bytes per glyph
```

Measured in practice for `0A93`: usable region `0x29000` = 167,936 B, bitmap offset `0x8F80` ⇒ **at most approximately 1025 glyphs**.
The original 877 glyphs (138,848 B) fit comfortably; the localized 1205 glyphs (190,976 B) **exceed it by 23,040 B = 180 slots**,
which is exactly the root cause of "a few characters break, and change to a different scene and the broken characters change again" — **unrelated to alignment, and unrelated to the translation**.

The forensics (pull the font library's **runtime copy** out of a savestate and compare it byte by byte against the font library in the ISO to see whether the differences start in one clean cut at a fixed offset), the fix (move the font library out of the reserved region and change the two "base / end" constants in the ELF), and the emulator game CRC change you **must** handle after editing the ELF, are all in [08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md).

## 10. Appending glyphs: pad alignment, size syncing and zero expansion

### 10.1 Pad alignment

Appending glyphs (changing the range count or glyph count) makes the bitmap offset drift, so a rebuild tool should uniformly pad by `(-off) % 16` after the glyph table (section 8). The same holds for `ID=9`: the data after the page table must stay 16-byte aligned.

### 10.2 Syncing size in three places (a lesson from appending to `ID=9`)

After changing a subfile's size you cannot change just one place, or it will either have no effect or crash. You need to sync:

1. the size at `font.bnd` header `+0x0C`;
2. the size in that subfile's entry in the `font.bnd` directory table;
3. the entries in the outer archive's path table that point to this subfile (the same subfile may be registered several times, for example 7 path-table entries `0x031A–0x0326`).

### 10.3 Zero-expansion constraint

All three font libraries are embedded in larger archives, and **their overall size cannot change**:

- There is no free gap after the `font.bnd` containing `ac0_j1`; expanding it requires moving the whole thing, and adding rows in place is forbidden;
- `ID=9` can only **overwrite in place** the dead data region after `font.bnd`, and **must not insert bytes** — inserting shifts all following data and directly causes a VIF FIFO crash;
- Adding glyphs therefore can only use "**overwriting original Japanese glyph slots that no game text references**", not adding new rows.

**Deciding whether a slot is free requires scanning the entire corpus**: the translation corpus, menu/UI text, the roster, reports — not one of them may be missed. A typical accident: mistaking Greek letter code points for free slots. The game's menus/UI and dialogue speakers (such as `Ω：`) actually use the Greek letter range `0x839F–0x83B6` (Α–Ω), for example `0x839F=Α`, `0x83A0=Β`, `0x83B5=Ψ` — injecting Simplified Chinese glyphs into these slots garbles every part of the interface that should show a Greek letter. The only criterion for calling a slot "free": that code point occurs 0 times in the **entire corpus**.

## 11. Pitfalls and lessons

Each item is organized as "symptom → root cause → how to avoid".

1. **The top and bottom halves of a glyph shifted/squashed** → an interleaved font library was written with a linear arrangement → before writing bitmaps, confirm whether the target font library is `interleaved` or `linear`, and write byte by byte with the matching alignment formula.
2. **Misaligned yet no data error can be found** → a proportional font was treated as fixed 16×16 four-quadrant → before investigating rendering misalignment, tally the glyph-table UV steps and confirm "fixed-width vs proportional".
3. **The data is all correct but all glyphs melt** → texdesc/CLUT/bitmap not 16-byte aligned (n and g of different parity) → after rebuilding, force `(-off) % 16` padding, then correct the relative pointers.
4. **The preview is fine but real hardware is greyish/fringed** → quantization used an imagined linear ramp while the real-hardware CLUT is out of order → reverse-engineer the real nibble→(brightness,α) from a texture dump and quantize by nearest brightness.
5. **Glyphs mirrored/broken** → the high and low positions of even columns were written the wrong way round inside the 4bpp byte → remember "even column = low nibble, odd column = high nibble".
6. **Wrong characters/shifting** → the bitmap was computed as "glyph index × 128/512", ignoring that `tail` is the bitmap row number → always address bitmaps through the `tail` field (`tail×512` or `tail×128`), never through the glyph index.
7. **Crash or no effect after appending** → only the header size was changed, not the directory/path table → make a checklist and sync every location that references that subfile's size in one go.
8. **The added glyphs overwrote glyphs the game is using** → free slots were only scanned against the translation corpus → before deciding a slot is free, scan the entire corpus (including menu/UI text and the Greek letter range) and confirm the code point occurs 0 times.
9. **Inserting bytes causes a VIF FIFO crash/subsequent data misaligned** → bytes were inserted in the middle of an archive → overwrite in place only, never insert; zero expansion.
10. **Characters uneven in height** → re-rendering each character with "centroid centering" lets each character's centre of mass drift → use top alignment/baseline alignment uniformly (draw the character at a fixed y on the canvas, top-aligned by ascent), with the bottom aligned to the row baseline.
11. **Stroke ends uneven in weight/blurry** → rendering used fractional coordinates, producing half-pixel misalignment, or supersampling + downscaling + level pushed the AA into near-white/near-black step transitions (banding) → rasterize at integer coordinates; reproduce the original font library's rasterization size and filtering as closely as you can, or quantize directly against the real CLUT.
12. **Complex-stroke characters lose strokes or have horizontal slips at low resolution** → the hinting of direct 16px rendering makes strokes too thin for some characters → you can try rendering at high resolution and downscaling (taking care that the downscaling filter does not introduce ringing), with the final verdict from visual inspection on real hardware; a few stubborn glyphs need to be re-rendered individually.
13. **Only a few characters break, and change to a different scene and the broken characters change again (data all correct, alignment correct too)** → the font library exceeded the RAM buffer the game reserves for it, and the out-of-bounds glyph slots were overwritten by engine data → work out the capacity budget before expanding the font library (section 9); obtain evidence by "taking a runtime memory copy and comparing it byte by byte against the ISO", and if necessary move the font library outside the reserved region ([08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md)).

> General principle: when rendering is misaligned, check the "data layout" first rather than the "data content"; key numbers (scale, tail, alignment, CLUT order) must be re-verified against the bytes or machine code — do not cite second-hand conclusions.

## Related documents

- [01 · Unpacking](01-unpacking.md) —— how to extract `AC.BIN` / `font.bnd` / `0A93` font library containers from the ISO.
- [02 · Text and Encoding](02-text-and-encoding.md) —— SJIS, MAPPING codes, container ids and text table structure (where the font libraries' code points come from).
- [04 · Write-back and Compression](04-write-back-and-compression.md) —— fslzss compatibility and the equal-length/variable-length rules when writing glyphs/text back.
- [05 · Packaging and ISO](05-packaging-and-iso.md) —— assembling font libraries into the image, verifying LBA/extent placement, and slimming.
- [07 · Debugging and MCP Breakpoints](07-debugging-and-mcp-breakpoints.md) —— when static analysis cannot get there, use emulator breakpoints to capture the renderer's sampling parameters and the real CLUT dynamically.
- [08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md) —— font library capacity ceilings, gathering evidence from savestates, moving the font library out of the reserved region (ELF patching), and the resulting emulator game CRC change.
