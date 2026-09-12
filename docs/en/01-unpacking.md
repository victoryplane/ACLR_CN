# 01 · Unpacking: ISO → AC.BIN → BND → fsliblzs

One-line positioning: this document lays out a reproducible technical path that starts from the PS2 disc image of *Armored Core: Last Raven*, goes through the ISO9660 file system, the AC.BIN main archive, the BND directory and the fsliblzs compressed stream, and finally arrives at text containers that can be analyzed and written back (.mes / .dat / .mrb and so on).

## Background and goal

ACLR stuffs almost all of its game assets into one main archive, **AC.BIN**. To do text translation, font replacement or asset analysis, the first step is not to change content but to walk this data chain end to end on its own:

```
ISO9660 disc image
  └─ AC.BIN                         top-level BND archive
      ├─ entry (fsliblzs compressed container) → after decompression may be an inner BND
      │    └─ inner BND → text containers (.dat / .mes / .mrb …)
      ├─ entry (uncompressed, data directly)
      └─ large entry (internally embeds another offset/size table + path table, indexing several nested BNDs, e.g. the font package)
```

The target reader of this document has nothing but a legitimate disc image and Python 3: following the format descriptions and pseudocode below, you can reproduce the "binary → text container" chain on your own, without depending on any ready-made toolkit.

## Prerequisites

- **Python 3**: the standard library is all you need; this document gives decompression and parsing pseudocode you can use directly as a reference.
- **A legitimate disc image (ISO)**: bring your own. This document neither provides nor tells you how to obtain any game file or font.
- A general-purpose archive tool that can read **ISO9660** (only used to export AC.BIN out of the image; optional, any tool supporting that file system will do).

## Step 0: Extracting AC.BIN from the ISO

A PS2 disc image is usually an ISO9660 file system. AC.BIN is the main data archive inside it, and its exact path varies by release, so confirm it yourself in the image's file listing and then export it.

Incidentally: the **main executable ELF** on the disc (release string and offset differ per region/revision, so go by the one in your own image) is the best material for validating a decompressor. Measured in practice, this release has only a single fsliblzs decompressor, located at file offset **0x1AA220**. The algorithmic conclusions in Steps 2 and 3 of this document (window, dist semantics, end marker, etc.) were all derived from disassembling that function plus a byte-by-byte comparison against a reference implementation; other region versions/revisions may have a different offset, so confirm it yourself.

If you want to **change constants in the ELF** (for example, after localization the font library exceeds the memory region the game reserved for it and must be relocated), you will need the VA ↔ file offset mapping: computed from the program headers, `file offset = VA − (p_vaddr − p_offset)`. In this game's main executable ELF the text segment is `p_offset=0x100 / p_vaddr=0x100000`, hence **file offset = VA − 0xFFF00** (using an approximate value shifts everything by `0x100`, and every instruction you read is wrong). For the related procedure and the side effects of changing the ELF, see [08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md).

## Step 1: Parsing the top-level BND of AC.BIN

AC.BIN is a BND archive:

| Offset | Length | Meaning |
|---|---|---|
| 0x00 | 4 | magic `BND\0` (`42 4E 44 00`) |
| 0x00–0x1F | 32 | header (contains the magic; the remaining fields are not needed by the unpacking in this document) |
| from 0x20 | one slot per 16 bytes | directory table, up to the start of the data region |
| data region | — | the actual bytes of each subfile |

A directory slot is 16 bytes, and all fields are **little-endian**:

```
struct dir_entry {        // top-level AC.BIN
    u32 id;               // entry ID
    u32 offset;           // byte offset relative to the whole AC.BIN
    u32 size;             // byte count
    u32 flags;            // unused at this level
};
```

Measured in practice, in this release the data region starts at **0x13800** (the directory table runs from 0x20 all the way to the start of the data region, approximately 5000 slots; the exact count varies by release). The more robust approach is not to hardcode that value but to scan the directory and take the first slot whose "offset is plausible, offset+size is within bounds, and size>0" as the start of the data region, then collect valid entries slot by slot over the interval [0x20, start of data region).

One example measured in practice: this release has a large entry `id=0x12C, offset=0x90C800, size=0x42BD370` (approximately 70 MB), and the font assets are hidden inside it (see "Nesting: another layer embedded inside a large entry" at the end of Step 3).

## Step 2: fsliblzs decompression

Many BND entries are themselves another `fsliblzs` compressed container and must be decompressed first. The file header layout is as follows:

| Offset | Length | Meaning |
|---|---|---|
| 0x00 | 8 | magic `fsliblzs` (uncompressed data has a separate `rawdata` magic and is dispatched by the layer above) |
| 0x10 | 4 | total file size (LE, including the 0x2C-byte header) |
| 0x14 | 4 | compression flag (LE, =1) |
| 0x20 | 4 | window size hint; measured in practice it is always 256 (`0x00000100`) in original samples, but **the game's decompressor does not read it** |
| 0x24 | 4 | decompressed size (**BE**, used only by the raw branch) |
| 0x2B | 1 | raw flag; when ==1 it takes the "copy through uncompressed" branch (almost never used in the game) |
| 0x2C | — | start of the LZSS compressed stream |

A few key facts established by disassembly:

- **The 0x20 field is ignored**: the decompressor reads only 0x2B (raw flag) and 0x24 (raw branch only); the compressed path does not even read 0x24 and relies solely on the in-stream end marker to stop. Writing 0x20 as 0 or as 256 gives exactly the same decompressed result. The plausible inference is that it is a "window size hint in units of 16 bytes" (256×16=4096=0x1000), but the game hardcodes the window and ignores this field.
- **window = 0x1000 (4096)**, hardcoded.
- **dist is relative to the start of the window**: `src = max(0, current output length − 0x1000) + dist`, not counted backwards from the current position.
- **length = nibble + 1** (1..16, 16 at most).
- **end marker = `length nibble == 0`** (the game looks only at the nibble, not at dist).

The LZSS stream uses a flag byte scheme with **LSB-first bit order**: every 8 operations form a group, preceded by one flag byte; bit0 of the flag corresponds to the 1st operation, bit1 to the 2nd, … bit7 to the 8th.

- flag bit = 0 → literal, pass through 1 byte directly.
- flag bit = 1 → back-reference token, 2 bytes `[b1, b2]`:
  - `dist   = (b1 << 4) | (b2 >> 4)` (12 bits)
  - `nibble = b2 & 0xF`
  - `length = nibble + 1`
  - `src = max(0, pos − 0x1000) + dist`, copied byte by byte.

Reference pseudocode (equivalent to the game's algorithm; overlapping matches are copied byte by byte, so it is safe):

```python
WINDOW = 0x1000

def decompress(blob, stream_off=0x2C):
    assert blob[:8] == b'fsliblzs'
    if blob[0x2B] == 1:                     # raw branch, almost never used
        size = int.from_bytes(blob[0x24:0x28], 'big')   # BE decompressed size
        return blob[stream_off:stream_off + size]       # raw start offset, see item 9 of "Pitfalls and lessons"
    out = bytearray()
    i, flag, bit = stream_off, 0, 0
    while i < len(blob):
        if bit == 0:
            flag, i, bit = blob[i], i + 1, 0x01       # LSB first
        if flag & bit:
            b1, b2 = blob[i], blob[i + 1]
            i += 2
            dist  = (b1 << 4) | (b2 >> 4)
            nibble = b2 & 0xF
            if nibble == 0:                 # end (the game only looks at the nibble)
                return bytes(out)
            length = nibble + 1             # 1..16, 16 at most
            base = len(out) - WINDOW
            if base < 0:
                base = 0
            src = base + dist               # relative to the start of the window
            for _ in range(length):         # byte by byte, overlap-safe
                out.append(out[src]); src += 1
        else:
            out.append(blob[i]); i += 1
        bit <<= 1
        if bit == 0x100:
            bit = 0
    return bytes(out)
```

> Note: some reference implementations judge the end marker as `dist==0 and nibble==0` (that is, `00 00`); the game judges only `nibble==0`. Measured in practice, valid streams contain no token with `nibble==0 and dist≠0`, so the two are equivalent on real data.

## Step 3: The inner BND and the path table

If decompressed data starts with `BND\0`, it is an inner BND (mission container, font package, etc.). The field semantics of the inner and top-level forms are **different**:

| Offset | Length | Meaning |
|---|---|---|
| 0x00 | 4 | magic `BND\0` |
| 0x10 | 4 | file count (LE) |
| from 0x20 | one slot per 16 bytes | file table, "file count" entries in total |
| path table | — | a sequence of NUL-terminated strings starting at the first entry's path_offset |

An inner file table slot:

```
struct inner_entry {
    u32 id;               // subfile ID (also the path table index)
    u32 offset;           // subfile byte offset
    u32 size;             // byte count
    u32 path_offset;      // points to a string in the path table
};
```

Path table parsing: starting from the first entry's `path_offset`, split on `0x00` and read out a run of **ASCII** path names in order; the `i`-th string corresponds to the subfile with `id==i`. Write each subfile out as the slice `dec[offset:offset+size]`: `.dat / .mes / .mrb` and the like are text containers (among them, **MES is plaintext text**).

### Nesting: another layer embedded inside a large entry

Assets such as fonts are often **not top-level entries**. Measured in practice, in this release the large entry `id=0x12C` (`offset=0x90C800`) embeds another index layer inside: the path table is a string region, followed by a 16-byte-per-slot `{id, offset, size, name_offset}` table whose offsets are relative to the start of the large entry's data (0x90C800). This is how a nested BND such as `font.bnd` can be found; measured in practice that font package has 7 copies, only the 1st of which is actually loaded, the rest being development-time backups. Inside `font.bnd` there is again a standard inner BND: header 0x20, directory of 10 entries, followed by a leftover development path string (garbage), and the data region starts at 0x210.

So when "drilling down layer by layer", be careful: **the base of a subfile offset differs per layer** — in inner BNDs such as mission containers the offset is directly relative to the decompressed buffer, whereas the table inside a large entry is relative to the start of that large entry's data. Verify the base every time you descend a layer.

## A reproducible path (end to end)

1. Using a tool that can read ISO9660, export **AC.BIN** out of the image (the path varies by release, confirm it yourself).
2. Parse the top-level BND directory to get the `{id: (offset, size)}` entry table (see the pseudocode approach in Step 1).
3. Slice each entry as `blob[offset:offset+size]`; if the first 8 bytes are `fsliblzs`, decompress it with Step 2.
4. If the decompressed result starts with `BND\0`, parse the inner file table and path table as in Step 3.
5. Write the subfiles out under their path names; `.mes` (plaintext text), `.dat`, `.mrb` and the like are text containers.
6. When you cannot find the font / font library, check whether a large entry (such as `id=0x12C`) contains another offset/size table + path table inside, and drill down one more layer.

## Pitfalls and lessons

**1. Changing the header's 0x20 field makes no difference either way**
- Symptom: you see `256` at header offset 0x20 and suspect that "256 vs 0" decides whether decompression succeeds.
- Root cause: disassembly confirms that the game's decompressor (0x1AA220 in this release) never reads 0x20; the window 0x1000 is hardcoded, the compressed path does not even read 0x24, and it relies solely on the in-stream end marker.
- How to avoid: do not make compatibility judgments based on 0x20; decompression looks only at the magic, 0x2B, 0x24 (raw) and the in-stream marker.

**2. dist is relative to the start of the window, not to the current position**
- Symptom: treating dist as "how many bytes to count backwards" as in common LZSS, the decompressed data comes out misaligned.
- Root cause: source address = `max(0, current output length − 0x1000) + dist`.
- How to avoid: take the source strictly by that formula, never use "current position − dist".

**3. The end marker looks only at nibble==0**
- Symptom: the reference implementation requires `dist==0 and nibble==0` to end, while the game looks only at the nibble.
- Root cause: the game code returns as soon as `b2 & 0xF` is 0, without checking dist.
- How to avoid: valid streams contain no token with `nibble==0 and dist≠0`, so the two are equivalent on real data; decide clearly which criterion your parser uses and do not mix them.

**4. Overlapping matches must be copied byte by byte**
- Symptom: when `dist < length` (RLE-style back-reference), copying the whole run with a single memcpy produces wrong output.
- Root cause: the decompressor's fast path (an 8-byte unroll for length ≥9) is also "read one, write one" in byte order.
- How to avoid: implement the copy byte by byte (`out.append(out[src]); src += 1`).

**5. Directory slots are not all valid; the start of the data region must be detected automatically**
- Symptom: the directory region contains empty slots with `size==0` or with offset/size out of bounds.
- Root cause: the directory is a sequence of 16-byte slots from 0x20 to the start of the data region, and some slots are empty.
- How to avoid: filter slot by slot; take the first slot with "a plausible offset and size>0" as the start of the data region (measured in practice 0x13800 in this release), and do not hardcode the entry count.

**6. Top-level and inner BNDs have different field semantics**
- Symptom: using one and the same parser for both layers, the 4th field is misread and path names come out as garbage.
- Root cause: a top-level slot is `{id,offset,size,flags}` (flags unused); an inner slot is `{id,offset,size,path_offset}`, and the inner form has a u32 file count at 0x10 whereas the top-level form relies on scanning.
- How to avoid: parse the two layers separately; do not share field assumptions.

**7. The path table is a sequence of NUL-terminated strings**
- Symptom: treating the path table as a fixed-length field reads misaligned.
- Root cause: the path table starts at the first entry's path_offset and is a run of ASCII strings separated by 0x00, used by indexing with the entry id.
- How to avoid: split on 0x00, accumulate string by string, then index by id.

**8. Assets such as fonts are not top-level; you must drill down one more layer**
- Symptom: `font.bnd` / font library files cannot be found in the outer directory.
- Root cause: the fonts are stuffed inside a large entry (`id=0x12C` in this release), which internally indexes several nested BNDs with an offset/size table + path table (font.bnd has 7 copies, only 1 of which is loaded).
- How to avoid: for large entries, check whether they contain a BND / path table structure and drill down layer by layer; note that the base of a subfile offset differs per layer.

**9. The starting point of the rawdata branch differs by implementation**
- Symptom: for a `0x2B==1` raw file, different implementations read the data at different offsets.
- Root cause: the reference implementation takes data from 0x30, while the game disassembly shows 0x2C, and neither fully matches the sample's actual layout (the real data is at 0x30).
- How to avoid: raw files are extremely rare (only a few samples in the original version); if you really need to handle the raw path, check the starting point against what you measure in the sample and do not blindly trust any one implementation. The compressed path is unaffected.

**10. The decompressor has no out-of-bounds / infinite-loop protection**
- Symptom: an invalid or truncated stream may read out of bounds or even loop forever.
- Root cause: the game's decompressor validates neither the upper bound of dist nor the output limit, and the output buffer size is pre-allocated by the caller according to the 0x24 (BE) size.
- How to avoid: in your own implementation add a `src < len(out)` check and a step-count limit; when parsing the directory also always validate that `offset+size` stays within bounds.

## Related documents

- [02 · Text and Encoding](02-text-and-encoding.md): after unpacking, the string pool, encoding, line breaks and byte alignment of the text containers are covered in the next document.
