# 04 · Write-back and Compression

## Background and goal

This document solves one problem: putting already-translated text safely "back into" the game's containers. Write-back is not simply changing a few bytes — it must satisfy three layers of constraints at the same time:

- **Compression layer**: the modified data must pass through the game's own decompressor (fsliblzs / LZSS).
- **Length layer**: replacement must not change the relative position of strings (equal length), otherwise offset references break.
- **Structural layer**: the "implicit structure" of a string pool — separators, block markers, identifiers — must be preserved verbatim.

If you only care about "is the translation correct?", you will usually get bizarre results like "icons are there, text is blank" or "the game hangs when entering the garage". This document proceeds in the order "compression compatibility → equal-length/variable-length → structural fidelity → write-back checklist", and collects the pitfalls and lessons at the end.

## Prerequisites

- Unpacking is already done (BND nesting, fsliblzs decompression, see [01 · Unpacking](01-unpacking.md)) along with text/encoding analysis (SJIS, MAPPING codes, container id, see [02 · Text and Encoding](02-text-and-encoding.md)).
- Every Chinese character used in the translation already has a corresponding glyph in the font library (see [03 · Fonts and Rendering](03-fonts-and-rendering.md)); write-back is only responsible for putting "text that can be displayed" into the correct position.
- It is advisable to have Python 3 (the standard library is enough) and a tool that can compare byte by byte / view hex, for verification after write-back.

---

## 1. fslzss / fsliblzs compression compatibility

### 1.1 Format at a glance

A large number of containers in the game are `fsliblzs` compressed files (this game contains 2469 such containers in total). The header is 0x2C bytes:

| Offset | Field | Endianness / value |
|---|---|---|
| 0x00 | magic `fsliblzs` (8 bytes) | ASCII |
| 0x10 | total file size (including the 0x2C header) | u32 LE |
| 0x14 | compression flag | u32 = 1 |
| 0x20 | window / block size hint | always 0x00000100 (256) in the original; the game's decompressor does not read it |
| 0x24 | decompressed size | u32 BE |
| 0x2B | raw flag | 0 = compressed / 1 = stored as-is (raw) |
| 0x2C | start of the LZSS stream | — |

The LZSS stream is the classic layout of "8 operations per group, 1 flag byte per group, LSB-first bit order":

- flag bit = 0: literal byte, pass 1 byte straight through.
- flag bit = 1: back-reference of 2 bytes `[b1, b2]`:
  - `dist = (b1 << 4) | (b2 >> 4)` (12 bits)
  - `len = (b2 & 0xF) + 1` (1..16)
  - `src = max(0, current output length - 0x1000) + dist`
- End marker: the back-reference `00 00` (length nibble == 0).

The complete reverse-engineering conclusions on the game-side decompressor (function location, window semantics, end detection, etc.) are in [01 · Unpacking](01-unpacking.md).

### 1.2 A lossless round-trip ≠ game compatibility

The easiest mistake to make when writing a compressor is to use "can my own decompressor decompress it back?" as the acceptance criterion. That only proves the compressor and the decompressor are **self-consistent**; it does not prove the game can decompress it, let alone that the other data paths are intact.

This project ran into this once, measured in practice: after decompressing part data, editing the description, and recompressing with a self-written compressor, several part textures in the garage 3D preview were corrupted (after entering a mission / the test arena, the same parts were fine again). Binary-searching the location gave this rule:

| Data | Contents | Handling strategy |
|---|---|---|
| 5xxxx (e.g. 51309) | parameters + 3D model + textures + name + description (approximately 99 KB) | **Keep the original compression; never recompress with a third-party compressor** |
| 6xxxx (e.g. 61309) | parameters + name + description text (approximately 16 KB) | can be decompressed → edit the description → recompress |
| dialogue `.mes` | plain text | can be recompressed |

The key fact: **the part description text shown in the garage is actually provided by 6xxxx** (a 16 KB small text; the game decompresses it fine after recompression); the description inside 5xxxx has never been displayed by the garage. Therefore translating part descriptions only requires touching 6xxxx.

Also note: the raw (0x2B=1) flag has no effect on the part loader — it still decompresses it as a compressed stream, and the result is a blank 3D preview. raw is only valid for a few file types (the only raw file in the original is 0xFA00).

### 1.3 A more precise conclusion (quoting 01)

After subsequently reverse-engineering the game's decompressor, the above attribution of "binary broken, text fine" was further corrected: the game has only one fsliblzs decompressor, and its behavior is **byte-for-byte identical** to the reference decompression implementation (window 0x1000, dist relative to the window start, length = nibble+1, end determined only by nibble==0), and it **does not read the 0x20 header field at all**; measured in practice, the recompressed model data of 188,000 bytes is also restored byte-by-byte under the game's algorithm.

This means the LZSS algorithm itself is not the culprit; the real cause is more likely in the **loading / directory layer before decompression** (BND directory offset/size write-back). So the operating rule from 1.2 (don't recompress 5xxxx) is still the safety floor, but when troubleshooting this kind of bug you should check "directory / size synchronization" first, rather than hastily suspecting the compression algorithm itself. For detailed conclusions see [01 · Unpacking](01-unpacking.md).

### 1.4 Making recompressed data fit back into its slot: why greedy is not enough, and how optimal parsing fixes it

The equal-length discipline of §2.1 requires that "the recompressed data must not exceed the original
slot". This is exactly where a hand-written compressor trips: **a greedy compressor often produces
*larger* output than the game's own compressor**. Measured in practice over **all 2470** fsliblzs
containers of the ISO:

| encoder | total output, all 2470 containers | vs. the original files |
|---|---|---|
| greedy (3-byte prefix table + longest match, `MIN_MATCH = 3`) | 389,463,280 B | 102.84% (**bigger than the game's own**) |
| **optimal parse** | 368,853,184 B | **97.39%** |

For the 523 model + texture records (ids 5xxxx) the difference is decisive: greedy 103.43% (only
**45/523** fit their original slot), optimal parse 98.01% (**523/523 fit**).

> This also supplies a mechanistic piece of supporting evidence for "pitfall 1: recompressing 5xxxx →
> corrupted hangar textures": the write path of the time was "replace in place + zero-pad", so as soon
> as the new stream was bigger than the original entry it **overflowed into the next entry's data
> area** — which is itself a form of data corruption. (Supporting evidence, not a proven sole cause.)

**The original's secret**: reverse-engineering the factory streams token by token shows that
**40–50% of their matches have length 2**. A `len = 2` token costs 2 bytes and covers 2 bytes, so it
**saves nothing by itself** — but it merges two operations into one, which shrinks the flag-byte
envelope and lets the rest of the parse land in better positions. That is the signature of **optimal
parsing**; a greedy longest-match encoder simply cannot see it.

**How to do it (three steps, container format untouched)**:

1. **Match search**: a 3-byte hash chain walked near-to-far; the first hit for a given match length is
   the **shortest** distance for that length;
2. **Allow `len = 2` matches** (greedy discards them outright);
3. **Optimal parse**: a one-dimensional DP for the globally cheapest token sequence. The cost unit is
   1/8 byte — the flag byte is always written whole, so it can be **exactly amortized** over the
   operations: literal = 9/8, match = 17/8. The DP result is optimal under that model.

**Safety net**: greedy and optimal parses are both computed and the **smaller one is returned** — the
output can never be larger than the old encoder's.

**Tool and measurements**: `tools/fslzss_compress.py` uses optimal parsing by default
(`--mode greedy` reproduces the historical behaviour byte for byte). On 12 real containers extracted
from the original image (3,192,992 B of decompressed data in total): greedy totals **107.09%** (bigger
than the original files), optimal **94.54%**, and round trips are **12/12 byte-identical**. The largest
container (1.9 MB) is the clearest case: greedy 108.9% (would not fit its slot) → optimal parsing
**92.7%, i.e. 7.3% smaller than the game's own compression**.

**Three boundaries to remember together**:

1. **A passing self-test is not game compatibility**: optimal parsing changes how the stream is built
   (it uses `len = 2` matches). Even though it only emits constructs the original decompressor must
   accept (`dist` always in 1..0xFFF and never 0, `len` 2..16, at least one literal byte before the
   end marker), you **still have to verify in game** (enter the garage once, fight one mission) before
   relying on it.
2. **Speed**: pure-Python optimal parsing trades time for size — measured at **3.6–14.8 KB/s** counted on
   the *decompressed* data (a 131 KB container takes about 9 s; a 1.9 MB container about 9 minutes),
   while greedy runs at roughly 730 KB/s, two orders of magnitude faster. `--chain-max 128` is about 4×
   faster at roughly +0.3% size; records above 8 MB automatically fall back to greedy.
3. **Conservative choice**: since the "only touch 6xxxx" path of §1.2 is already validated, **leave
   5xxxx alone if you can**; use optimal parsing only when 5xxxx must be recompressed, and accept the
   in-game verification cost of item 1.

---

## 2. Equal-length and variable-length replacement

### 2.1 Rules

- **Equal-length replacement: safe, you can just do it.** Example: `総(0x918D)→综(0x89C5)`, `対(0x91CE)→对(0x88BB)` — both are 2 bytes → 2 bytes, no shifting.
- **Variable-length replacement: forbidden by default.** Strings are often referenced by offset / index; a length change shifts every subsequent string and invalidates all the references.

### 2.2 Why variable length blows up

Take MRB's STR segment as an example: strings start at 0x20, size/count are recorded at 0x14/0x18 in the header, and outside the segment there are 2146 u32 values falling within the 0x20~0xEA0 range, i.e. a large number of strings are referenced by external offsets. Any single length change (even ±2 bytes) shifts the subsequent strings → the references break → the game hangs when entering the garage.

Common variable-length replacements include:

- Adding or removing characters: `移動力→移动性能` (+2 bytes)
- Fullwidth ↔ halfwidth: `ＥＮ→EN` (−2 bytes)

**Fullwidth → halfwidth intuitively "shortens" the text, but it is equally a length change and equally forbidden.** To perform a variable-length replacement you must first reverse-engineer the reference structure clearly (whether it is a string index or a byte offset) and update all references in step; otherwise treat it as forbidden across the board.

---

## 3. Structural fidelity: more than length

"Equal-length replacement" only guarantees that the total file length is unchanged; it **does not guarantee that the internal structure of the pool is unchanged**. Separators, block markers and the distribution of NUL segments are all structure that must be preserved with separate care.

### 3.1 A typical accident: 0x00 padding destroys the string pool

In the key guide's string pool, the original NUL segment structure is strictly **{single NUL, double NUL}**: a single NUL is the string separator, a double NUL is "end of screen block". One version of the write-back padded the difference by which "the translation is shorter than the original" with **0x00**, and also replaced the trailing fullwidth spaces with 0x00, producing arbitrary-length NUL segments ranging from 1 to 20 in the pool:

| Version | NUL segment length distribution | Result |
|---|---|---|
| original | `{1:358, 2:97}` | normal |
| faulty write-back | `{1:112, 2:52, 3:56, 4:6, 5:59, …, 20:2}` | tag location fails → text blank |
| after the fix | `{1:358, 2:97}` | position-by-position identical to the original |

The symptom is "key icons present, text blank": the icons (○×△□) go through the geometry / symbol glyph region and are unaffected; the text goes through string-pool location, and if the pool structure is broken it cannot be located. When troubleshooting this "icons present, text blank", if the icons and the text share the same font library, the font library is basically fine, and you should check the **string location / pool structure** first.

### 3.2 The correct way to pad

Use equal-length replacement + pad with a **fullwidth space 0x8140** rather than 0x00, and do not touch a single trailing NUL:

```python
# After writing the translation, fill the original content region [start, nul_idx) with fullwidth spaces; the trailing NUL(s) are kept as-is
pad = content_len - len(enc)
p = start + len(enc)
while pad >= 2:
    out[p] = 0x81; out[p+1] = 0x40; p += 2; pad -= 2
if pad == 1:          # the translation contains halfwidth ASCII (e.g. RGB/COM), leaving a 1-byte difference
    out[p] = 0x20     # pad with a halfwidth space (anything non-NUL is safe)
```

- For an even difference use 0x8140 (fullwidth space); for an odd difference (the translation contains halfwidth ASCII) use 0x20 (halfwidth space — safe as long as it is not NUL).
- The trailing NUL (single / double) is not touched at all → the NUL segment structure is position-by-position identical to the original.

This lesson shows in reverse: **reverse-engineering conclusions must land in the implementation verbatim.** The conclusion said "pad with 0x8140" but the implementation wrote 0x00 — a one-character difference is the blank-text bug.

---

## 4. MES / MRB / container write-back checklist

### 4.1 Three tables that must stay in sync

Whenever you modify any container, after write-back check it item by item against the following checklist.

**Compression layer (fsliblzs header)**

| Field | Requirement |
|---|---|
| 0x10 total size | includes the 0x2C header, and matches the actual file size after recompression |
| 0x24 decompressed size | BE endianness; the game allocates its buffer based on this |
| 0x2B raw flag | do not write 1 for part data (raw is not supported by the part loader; `0x14` is the compression flag) |
| alignment | in the original, every container's total size is a multiple of 16; failing to pad means the loader cannot read a whole quadword, the tail data is wrong (the symptom is a mission loading forever) |

**Container layer (BND)**

| Field | Requirement |
|---|---|
| inner BND header 0x0C | total container size; the game uses it to determine the boundary of the data region, and if it is not updated after appending data the data is judged out of bounds |
| inner BND entry table | the offset / size of every entry; must be kept in sync after relocation or appending |
| outer BND directory | same as above; for relocation at the AC.BIN level, see [05 · Packaging and ISO](05-packaging-and-iso.md) |

**Text layer (.mes)**

`.mes` structure: header 0x10 + entry table count×16 + sub-pointer table count×8 + text region; each line is UTF-16LE and ends with `00 00`. When rebuilding:

- Update the pointer / size of every string in the entry table and the sub-pointer table.
- Convert a halfwidth character at the end of a line to fullwidth (the original's fullwidth convention at line ends, to avoid the high byte 0x00 of a halfwidth character sitting next to the `00 00` terminator and creating a boundary ambiguity).
- Append new data to the end of the container, 16-byte aligned.

### 4.2 Reference layer and identifier layer

- **Offset / index references**: strings referenced by external offsets, such as those in the STR segment, can only be replaced at equal length; to change the length you must update all references in step (see section 2).
- **Control identifiers**: an MRB contains not only display text but also a large number of control identifiers (such as `Head_攻撃力`, `String_Param後`, `Warning_腕部重量過多`, `SpecBar_前`). **The Japanese part of these identifiers is itself the identifier**; blindly replacing across the whole file changes it → the game cannot find the control → the screen crashes. Only pure display labels (such as the `Head_*` / `String_*` attribute names) need changing, and they must match the attribute category label character for character (including Simplified forms, fullwidth/halfwidth and suffixes).
- **Display label ≠ state key**: the same piece of text can appear simultaneously in the two guises of "state key" and "display label" (the name entry tabs are one example). Before changing anything, confirm the render source; do not edit a state key as if it were display text.

### 4.3 A positive example of equal-length replacement

The render source of the name entry tabs (かな / カナ / 英数 / 漢字 / 記号) is the dialogue block of `NameEntry.mrb` / `NameEntry2.mrb`, not some global string pool. The structure, measured in practice:

- 3 blocks inside each .mrb, 5 labels per block, arranged in a fixed order within the block, with a label interval of **0x30**.
- In each 0x30 record, the label field is at **+0x18**, in the format **4 bytes SJIS + 4 bytes 0x00**.
- Equal-length replacement is enough: swap the labels character by character, according to the code table, for the Chinese codes whose glyphs have already been injected, and verify that all of them fall inside the font library's range table.

The counter-example: following old notes, someone changed the "short label with the same name" in another string pool; the tab display did not change and the built-in keyboard went blank as well — because that one was actually a state machine key, not the render source. The signal "I changed it and nothing happened" is itself a reminder: what you changed was not the render source.

---

## Pitfalls and lessons

### Pitfall 1: recompressing 5xxxx → corrupted textures in the garage 3D preview

- **Symptom**: several part textures in the garage 3D preview are corrupted, the same parts are fine after entering a mission / the test arena; the description text is always fine.
- **Root cause**: 5xxxx (model + texture binaries) was also decompressed→recompressed; but the description in 5xxxx has never been displayed by the garage — the description text is actually provided by 6xxxx.
- **How to avoid**: translate only 6xxxx (the description text) and leave 5xxxx under the original compression untouched. When troubleshooting write-back bugs, use bisection and restore the three variables "changed content / recompressed / moved the location" one at a time.
- **Update (2026-09)**: there is also a mechanistic piece of supporting evidence — the greedy compressor of the time produced **larger** output than the factory data (102.84% over all containers), and the write path was "replace in place + zero-pad", so anything that did not fit **overflowed into the next entry's data area**, which is itself a form of corruption (see §1.4). With optimal parsing all 523 5xxxx records fit; but you still have to do the in-game verification yourself, so the guidance above stands.

### Pitfall 2: 0x00 padding → blank key guide text

- **Symptom**: in the key guide bar at the bottom of the garage, "key icons present, text blank".
- **Root cause**: the difference left by a shorter translation was padded with 0x00, destroying the pool's {single NUL, double NUL} structure.
- **How to avoid**: pad the difference with 0x8140 (fullwidth space; 0x20 for an odd difference) and keep the trailing NUL as-is; after write-back, verify that the NUL segment distribution matches the original.

### Pitfall 3: blind MRB replacement → the garage will not open

- **Symptom**: after doing a whole-file 2-byte replacement on Assembly*.mrb, the garage will not open.
- **Root cause**: the Japanese parts of control identifiers such as `Warning_*` / `String_Param*` / `SpecBar_*` are the identifiers themselves, and mismatch after replacement.
- **How to avoid**: first distinguish "display text" from "identifiers"; perform equal-length replacement only on pure display labels, and make sure they match the matching table character for character.

### Pitfall 4: variable-length replacement of the STR segment → the game hangs when entering the garage

- **Symptom**: after doing a variable-length replacement on the MRB STR segment plus NUL padding at the end of the segment, the game hangs when entering the garage.
- **Root cause**: the strings are referenced by external offsets / indexes, and the length change shifted the subsequent strings.
- **How to avoid**: by default only do equal-length replacement; variable length requires first reverse-engineering the reference structure and updating all references in step.

### Pitfall 5: changed it and nothing happened → wrong render source

- **Symptom**: after changing the name entry tab labels in the string pool, the tab display is unchanged and the built-in keyboard is blank as well.
- **Root cause**: the real render source is the .mrb dialogue block; the one in the string pool is a state machine key.
- **How to avoid**: verify the render source before changing anything (byte-search for every copy with the same name + look at the structure); "changed it and nothing happened" = what you changed is not the render source.

### Pitfall 6: the round-trip lossless self-test passes and the game still errors

- **Symptom**: the self-written compressor's round-trip is byte-for-byte identical, yet once installed in the game there is still texture corruption / infinite loading.
- **Root cause**: the self-test only proves self-consistency, not game compatibility; later reverse engineering confirmed that the LZSS algorithm itself is identical to the game's, so the cause is more likely in the directory / size synchronization layer (quoting [01 · Unpacking](01-unpacking.md)).
- **How to avoid**: treat "the compression algorithm is correct" and "the container fields are synchronized correctly" as two independent things and accept them separately; alignment, size and directory entries are all indispensable.

---

## Related documents

- [01 · Unpacking](01-unpacking.md) —— fsliblzs decompressor reverse engineering and the nested BND structure
- [02 · Text and Encoding](02-text-and-encoding.md) —— SJIS / MAPPING codes / container id
- [03 · Fonts and Rendering](03-fonts-and-rendering.md) —— where the glyphs for the translation come from
- [05 · Packaging and ISO](05-packaging-and-iso.md) —— outer directory, LBA / extent placement verification
