# 02 · Text and Encoding: SJIS, MAPPING codes and text tracing

> ACLR's text layer is not a single encoding: the Japanese source contains both natural SJIS and UTF-16LE dialogue, and the Chinese localization introduces MAPPING codes on top of that.
> This document explains the differences between the three encodings, the container id numbering, the structure of the text tables, and the tracing method for going "from game text back to the write-back position".

## Background and goal

ACLR's (PS2) visible text is scattered across hundreds of containers, and the encodings are inconsistent, so a generic tool searching for it directly often finds nothing.
This document solves three things:

1. Lay out the encoding systems that coexist inside the game, and how each one is identified;
2. Explain the "container id" numbering and build the intuition for locating "text → container → file → offset";
3. Give the byte structure of `.mes` dialogue tables and SJIS text, and record the pitfalls hit during reverse engineering and localization.

This document covers "text and encoding" only. For unpacking and compression see 01, for the font library and rendering see 03, for write-back see 04, for packaging see 05.

## Prerequisites

- You can already extract AC.BIN from the ISO and parse its top-level BND entries (see 01-unpacking.md).
- You can decompress fsliblzs containers and parse the inner BND file table inside a mission container (see 01-unpacking.md).
- A scripting environment that can read binary in any encoding and do offset location (Python 3 is enough).
- A hex viewing/comparison tool, for checking bytes and edits.

## 1. Encoding systems

At least three encodings coexist in the game text; you must tell them apart before touching anything, otherwise you will "find it, but edit it wrong".

### 1.1 Natural SJIS (Japanese source text)

Most non-dialogue text is standard Shift-JIS:

- Mission briefings `MissionDataSXX.dat` (a subfile of the inner BND inside a mission container)
- Mission details `missionRemark.bin`
- Menu text `Message.bin`, etc.

Identification and scanning characteristics:

- Two-byte lead byte ranges `0x81–0x9F` and `0xE0–0xEF`, trail bytes `0x40–0x7E` and `0x80–0xFC`; halfwidth katakana `0xA1–0xDF`.
- Scanning heuristic: on a valid lead byte take 2 bytes; treat `0x0A`/`0x0D` as a line break and continue; treat `0x20`/`0x00` as end of string; then decode as shift_jis.

For this kind of text "byte = SJIS code point", and the final glyph is determined by the slot of that SJIS code point in the font library (font library details in 03).

### 1.2 Dialogue UTF-16LE

The in-mission dialogue/radio scripts `sXXX.mes` are not SJIS but **UTF-16LE**:

- 2 bytes per character `[b0 b1]`, little-endian value `(b1<<8)|b0` is the Unicode code point:

  ```
  character = chr((b1 << 8) | b0)
  ```

- Single-character encoding examples: `B7 30` = シ (U+30B7), `FC 30` = ー (U+30FC), `E9 30` = ラ (U+30E9); `1F 75` = 生, `53 4F` = 体, `75 51` = 兵, `68 56` = 器.
- Control codes: `0A 00` = line break (U+000A); `00 00` = end of entry (U+0000, not part of the text); `XX FF` = fullwidth character U+FFXX (e.g. `1A FF` = ：U+FF1A, `01 FF` = ！U+FF01).
- Speaker line format: `speaker name + ：(U+FF1A) + \n + dialogue body`.
- A few "speaker only" entries end with a single `0x0A` (odd length); decoding these needs separate handling, and you cannot apply the "two bytes per group" divisibility assumption.

Scale reference: of 343 mission containers, 328 contain dialogue, 6005 lines in total, 851 distinct characters, and full decoding yields 0 replacement characters.

### 1.3 MAPPING codes (introduced by the localization)

After the Chinese localization a large number of Chinese characters have no glyph in the original font library, so they cannot be written as natural SJIS directly. The approach is to assign such a Chinese character a
**MAPPING code point**: the text stores this code, while the corresponding slot of the target font library holds the glyph for that character.

- Typical range `0x88xx`, example: 对 = `0x88BB`.
- In essence it is an explicit mapping of "code point → extended font library glyph slot", falling inside the SJIS-compatible code point space (the font library looks up code points through the range table).
- Besides `0x88xx`, other free SJIS code points are also used for mapping (e.g. relocated to `0x9457`, `0x974B`, `0x955F`, etc.).

Key constraint: MAPPING code points must be chosen from empty slots that "never occur anywhere in the whole corpus", otherwise they will collide with the source text or with other screens (see pitfall 5.2).

### 1.4 The output encoding is decided by the target font library

Which encoding a given translation is written back in depends on which font library ultimately renders it:

| Rendering path | Font library indexing | Text output encoding |
|---|---|---|
| Menu/attribute pages (ac0_j1 with extended glyphs) | SJIS code point + MAPPING slot | MAPPING codes (`0x88xx`, etc.) |
| Dialogue (0A93 Unicode font library) | Unicode code point | Unicode code point (UTF-16LE) |
| Natural Japanese text without extended glyphs | Original SJIS glyphs | Natural SJIS |

The same character may need different encodings on different screens: "use whichever encoding the font library that renders the translation output uses". Confirm the rendering font library before deciding the encoding,
otherwise you get wrong characters or blanks (see pitfall 5.3).

## 2. Container ids and text ownership

At the top level AC.BIN is one BND archive, and each entry is identified by a numeric id, which is the "container id". The first step of locating text is to
find the corresponding container id by content category:

| Container id | Content |
|---|---|
| `0x2000–0x8000` | Outer mission containers (343 of them); the inner BND holds `.mes` dialogue and `MissionDataSXX.dat` briefings |
| `0x3A0` / `0x3A7` / `0x3A8` | Arena text |
| `0x3A1` | Mission details missionRemark |
| `0x3A2` / `0x3A9` | Mission report (mission) |
| `0x3A4` / `0x3A5` / `0x3A6` | Raven roster RankerInfo / RankerInfo2 / RavenInfo |
| `0x432` / `0x433` | System messages dialog.fmg / linehelp.fmg |
| `0x436` | Part descriptions new_AllParts.bin |
| `0x043C–0x043F` | Attribute/TUNE help asm_disp |
| `0x0335` / `0x0439` | Button prompts keyguide |
| `0x001A` / `0x0A90` | In-mission interface messages |
| `0x0AE–0x0FB` / `0x1EC–0x234` | Request mail / mission reports |

The outer mission containers are a nested structure: the data block the id points to is first decompressed with fsliblzs, the decompressed data begins with the BND magic, and then the inner
BND file table is parsed to get the subfiles. Subfiles are distinguished by inner id: dialogue `.mes` is inner id=3 and the briefing `MissionDataSXX.dat`
is inner id=6.

## 3. Text table / message table structure

### 3.1 The .mes dialogue table

Layout inferred from the `sXXX.mes` of mission 001 as a sample (different missions may have slightly different structures, so measure in practice yourself):

- `0x00`: u32 entry count `count`.
- `0x04`: header configuration area (variable length).
- From `0x10`: `count` 16-byte entries, where `+0x0C` is a pointer that points to the secondary pointer table.
- Secondary pointer table: each item is 8 bytes = `[text pointer][00 00 00 00]`, and the text pointer points to the body.
- Body: a UTF-16LE string, terminated by `00 00`.

Decoding order: read `count` → take the `+0x0C` pointer of each entry → jump to the secondary pointer table and take the text pointer → read UTF-16LE from the text pointer up to the `00 00`
boundary.

### 3.2 SJIS text (briefings / descriptions)

The briefing `MissionDataSXX.dat` and `missionRemark.bin` use natural SJIS and have no pointer table like the one in `.mes`; extract fields directly by
"string scanning + SJIS decoding" (location / mission name / faction / body / time, etc.). The offset and
length of each field must be aligned by measuring in practice inside the specific container.

### 3.3 Presentation layer: the line break ⏎ and line width (→ 03/04)

The line break control code in the text is uniformly recorded as **⏎** (U+23CE) in the translation workflow; it is only a marker for "line break" and does not enter the font library character set;
the actual bytes are `0x0A` in SJIS and `0A 00` in dialogue UTF-16LE.

Dialogue line width has a hard constraint: **every line ≤ 20 fullwidth characters**. Line breaking rules: do not hang structural words (的/着/得/也/还/把/被…) at the end of a line,
do not let fragments of "的/地/得" appear at the start of a line, merge whenever possible, and the line count need not align with the Japanese. For width and rendering, and for write-back details, see
03-fonts-and-rendering.md and 04-write-back-and-compression.md respectively.

## 4. Text tracing methodology

The general workflow from "seeing a line in the game" to "which byte at which location must be edited":

1. **Determine the category**: first decide which category the line belongs to: dialogue / briefing / arena / system message / menu / part / mission details / mail /
   report / roster / interface message, etc.
2. **Pin down the container**: look up the container id by category (see the table above); if it is mission text, further locate the outer mission container id (the `0x2000–0x8000` range).
3. **Decompress + locate inside**: decompress the mission container with fsliblzs first, then parse the inner BND to get the subfiles and offsets.
4. **Locate by encoding**: locate the byte range of the target string inside the subfile according to the encoding characteristics — SJIS by lead byte scanning, UTF-16LE by
   decoding 2-byte code points and then matching.
5. **Confirm uniqueness**: the same line may appear in several containers/copies; confirm with three-way evidence of "string + surrounding context + container"
   so that you do not edit the wrong copy.
6. **Record the write-back position**: register "container id → inner file → offset within the file → length"; the write-back script uses this to do equal-length/variable-length replacement
   (rules in 04).

The core deliverable is a five-column "text → position" table: **category / container id / source file / translation / write-back script**; all text edits
are located according to this table, and after editing you must fill back into this table too.

## 5. Pitfalls and lessons

### 5.1 Treating dialogue codes as "custom SJIS" and hunting for a conversion table

- Symptom: the dialogue code points contain a large number of invalid SJIS lead bytes, and no "dialogue code → SJIS" conversion table can be found however hard you try.
- Root cause: the dialogue codes are Unicode (UTF-16LE) to begin with; no conversion table exists.
- How to avoid: verify code points with known characters first (read a stretch of dialogue bytes as little-endian and see whether the expected katakana/kanji come out), and do not presume
  that "there must be a custom mapping table".

### 5.2 MAPPING code collision (Greek letters already occupy them)

- Symptom: after assigning some Chinese characters to `0x83xx` code points, the Greek letters in menus/UI turn into wrong Chinese characters.
- Root cause: code points such as `0x839F`=Α, `0x83A0`=Β, `0x83B5`=Ψ are actually in use in menus/UI; only part of the corpus was scanned, so they were misjudged as "free".
- How to avoid: judging a code point free requires scanning the whole corpus (all text sources); the seemingly free `0x83xx` range may already have a use; only assign the code
  once confirmed, and after assigning it still cross-check the whole text to see whether the original use is affected.

### 5.3 Encoding and font library mismatch → wrong characters/blanks

- Symptom: after the translation is written back, wrong characters, missing characters or a whole blank stretch appear; "missing characters on the left + remaining text left-aligned".
- Root cause: the same screen has separate rendering font libraries (attribute pages go through MAPPING codes, TUNE labels go through the ID=9 small font library, help text goes through the ac0_j1
  large font library), and the encoding was written as the code point of a different font library, or the target font library has no corresponding glyph filled in.
- How to avoid: first confirm the rendering font library and indexing method of the target screen, then decide the output encoding; new characters must have their glyphs filled into the corresponding font library (see 03).

### 5.4 Mistaking a single 00 byte for a separator

- Symptom: early dialogue extraction mis-parsed U+XX00 characters such as 最 (U+6700).
- Root cause: a single `0x00` byte was treated as a line separator, but for UTF-16LE the low byte of a U+XX00 character is exactly `0x00`, so it was split wrongly.
- How to avoid: read UTF-16LE directly from the raw bytes with the double zero `00 00` as the boundary; do not split on a single `0x00` byte.

### 5.5 Individual characters render blank (blank even though the data is all correct)

- Symptom: some character in the TUNE screen (e.g. 力, code point `0x97CD`) has glyph data that is correct at the byte level, yet always renders blank.
- Root cause: the renderer has an unsolved bug for that code/glyph slot combination; unrelated to the data.
- How to avoid: there is no need to fight such rendering bugs — reword the translation to go around that character; whether you can go around it must be measured in practice per screen. For render chain analysis see
  03-fonts-and-rendering.md.

## Related documents

- 01-unpacking.md: ISO9660 → AC.BIN → BND → fsliblzs decompression, to get the containers and bytes used in this document.
- 03-fonts-and-rendering.md: ac0_j1 / 0A93 / ID=9 font libraries, range tables, bitmaps, CLUT, and the glyph placement of MAPPING code points.
- 04-write-back-and-compression.md: fslzss compatibility, equal-length/variable-length replacement rules and the write-back script.
- 05-packaging-and-iso.md: assembling after the text is edited, LBA/extent verification and the bootable product.
