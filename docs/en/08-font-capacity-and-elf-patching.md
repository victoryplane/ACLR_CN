# 08 · Font Capacity and ELF Patching: When "Correct Data" Still Breaks Glyphs

> This document is about the hardest class of glyph corruption to track down: **the font library file itself is byte-for-byte correct,
> the 16-byte alignment is correct too, and the upload and sampling code is not at fault either,
> yet certain characters are simply broken on screen — and "which characters exactly are broken" changes with the scene.**
> The root cause is not in the file: it is that **the RAM buffer the game reserved for the font library cannot hold our font library** — the excess glyphs
> land in the engine's own RAM, get covered by the data the engine writes every frame, and on upload are faithfully copied into VRAM.
>
> This document gives you the means to pin the fault down (pull the runtime copy of the font library out of a savestate and compare it byte by byte with the ISO), the fix
> (move the font library out of the reserved area + change two constants in the ELF), and **the side effect you must remember to handle after editing the ELF**:
> the emulator's game CRC changes, so every per-game setting and patch named after the CRC stops matching.

## Background and goal

The constraint given by 03 · Fonts and Rendering is "structurally correct + 16-byte aligned"; this document adds **a third hard constraint:
capacity**. The relationship between the three can be remembered like this:

| Constraint | Symptom when violated | Scale of the damage |
|---|---|---|
| Structure / byte order / tail addressing | Glyphs shifted, mirrored, squashed | the specific glyphs involved |
| 16-byte alignment | **All** glyphs garbled and melted after upload | the whole library |
| **Capacity (this document)** | Only **the slots past the reserved area** break, and **they change with the scene** | every slot after one "overflow boundary" |

Goal of this document: when you run into "the data is all correct, the alignment is correct too, yet individual characters are broken, and changing level changes which characters are broken", you have
a troubleshooting path that **can produce decisive evidence**, and a fix that **cures the problem at the root without touching the translations or shrinking the font library**.

## Prerequisites

- Following 01 · Unpacking and 03 · Fonts and Rendering, you can already extract and rebuild the target font library (this document uses ACLR's `0A93` in-mission dialogue font library as the example).
- **An emulator savestate** (PCSX2's `.p2s`) — this is the primary source of evidence in this document; no debugger and no breakpoints are needed.
- Python 3 + the standard-library `zipfile`; decompressing zstd needs `zstandard` (a third-party package).
- The target game's main executable ELF (extracted from your own image), plus a tool that **can disassemble little-endian MIPS**.

## 1. First, determine which class the symptom belongs to

The three classes of problem look very similar, but investigating them mixed together wastes a great deal of time. Use this table to point yourself in the right direction first:

| Symptom | Looks more like | First thing to do |
|---|---|---|
| A certain character is **uniformly blurry**, greyish, jagged, but structurally intact | rendering/quantization (see 03 §5 CLUT) | work back from a texture dump to the real CLUT and match by nearest brightness |
| **All** glyphs garbled, melted, shifted, yet the data is all correct | alignment / layout (see 03 §8) | check the bitmap offset mod 16, `interleaved` vs `linear` |
| **Only a few characters** break (missing strokes, top half misaligned, as if smeared over by other data), and **the broken characters change when you change level/scene** | **capacity overflow (this document)** | pull a copy of the font library out of a savestate and compare it byte by byte with the ISO |

The last row has two **highly characteristic** clues; seeing them should push your thinking in this direction:

1. **The same character breaks differently in different scenes**, and within one scene some characters may be fine while others are broken;
2. **Change the text, and the broken location does not follow the text** — what is broken is "a certain glyph slot", not "a certain piece of text".

> One boundary case to add: not every instance of "a single character is broken" is a capacity problem. Another character in this project (`〇`) is broken because
> **the glyph data itself does not match the CLUT brightness levels** (the bitmap nibble in that slot uses different levels from the surrounding glyphs, so its
> brightness lands on a dark level and it looks like it is missing strokes). That is a rendering/data problem, and the right remedy is to **redraw that slot**.
> So the criterion in this document is not "a single character is broken" but **"the broken location drifts with the scene"**.

## 2. Step one: pull the runtime copy of the font library out of a savestate

PCSX2's `.p2s` is a **ZIP container**, in which `eeMemory.bin` is a snapshot of EE main memory (32 MB), and the members are compressed with **zstd** (method = 93 in the ZIP, which standard libraries before Python 3.14 do not recognize, so you must decompress it yourself):

```python
import io, struct, zipfile, zstandard

def read_ee_ram(p2s_path):
    """Extract the 32 MiB EE main-memory image from a .p2s savestate."""
    with zipfile.ZipFile(p2s_path) as z:
        info = z.getinfo('eeMemory.bin')      # the member is zstd-compressed (ZIP method = 93)
        try:
            return z.read(info)               # Python 3.14+: the standard library supports zstd natively
        except NotImplementedError:           # earlier versions: fetch the compressed data yourself and hand it to zstandard
            with open(p2s_path, 'rb') as f:
                f.seek(info.header_offset)
                nlen, elen = struct.unpack_from('<HH', f.read(30), 26)
                f.seek(info.header_offset + 30 + nlen + elen)
                raw = f.read(info.compress_size)
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as r:
        return r.read()

ram = read_ee_ram(r'...\SLPS-25462 (XXXXXXXX).01.p2s')
print(len(ram))                               # 33554432 = 32 MiB
```

Once you have the RAM image, **find the font library's runtime copy in RAM**. The least-effort locator is the font library's own
**range table bytes** (take the first few bytes of the range table from the ISO font library and just `ram.find(...)`):

```python
ram_off = ram.find(iso_font[0x40:0x40 + 32])       # first 32 bytes of the range table
print(hex(ram_off))                                # e.g. measured in practice in this project: 0x1C03150
```

This step also settles another key question along the way: **which fixed address the font library is loaded to** —
measured in practice in this project, three different sessions on different dates all gave `0x1C03150`; that address is needed later.

## 3. Step two: compare byte by byte with the font library in the ISO (primary criterion)

Cut the copy out of RAM, compare it byte by byte with the font library in the ISO, and **count "contiguous diff runs"** rather than just counting differing bytes:

```python
n   = len(iso_font)
cpy = ram[ram_off:ram_off + n]
runs, start = [], None
for i in range(n):
    if cpy[i] != iso_font[i]:
        if start is None:
            start = i
    elif start is not None:
        runs.append((start, i)); start = None
if start is not None:
    runs.append((start, n))
print(runs[:10], '总差异段数 =', len(runs))
```

Result measured in practice in this project (this is the "decisive evidence"):

```
Below 0x29000  : completely clean (byte-for-byte identical)
first differing byte: 0x29002   (0x29000 is exactly the start of the 1025th glyph)
After 0x29000  : diff runs all the way to the end of the font library (61 runs / 1,078 bytes differ in total)
                 the diff runs are not contiguous — the overwriting data occasionally matches the bytes it overwrote,
                 but "not a single byte below the boundary was touched" is decisive
```

The tools in this repository can run this whole check for you:

```bash
# 1) Which address was this data loaded to? (output for this example: that file's base address = 0x1C03150)
python tools/savestate_ram.py locate "<savestate>.p2s" font.bin --at 0x40 --len 32

# 2) compare byte by byte with the in-memory copy; --from skips the header pointer region that gets rewritten to absolute addresses after loading
python tools/savestate_ram.py diff "<savestate>.p2s" font.bin --addr 0x1C03150 --from 0x8F80
#    before patching → diff runs start at 0x29002 and continue to the end
#    after patching  → 0 runs, 0 bytes (completely identical)
```

> **A detail that is easy to misjudge**: once the container is loaded into memory, the header's "file offset" pointers are rewritten by the game into
> **runtime absolute addresses**. So when comparing whole files, the beginning (the pointer fields at `0x20..0x34` in this example) **will always**
> show a short diff run — that is not corruption. To judge "has it been overwritten", look at the **data region**; just use `--from` to skip the header.

**Key conclusion: the corruption is not random — it starts at font-library offset `0x29000` and cuts cleanly to the end.**
A hard boundary in terms of "file offset" means the problem is not in the glyph data, not in the text and not in the renderer,
but in the fact that **the game put the font library in a buffer of limited size** — everything past the boundary was covered by somebody else's data.

It also explains "why the broken characters change": **for those glyph slots past the boundary, which one gets overwritten and what it gets overwritten with
depends on what the engine happens to write into that RAM at the time**, hence the per-frame/per-scene differences.

> Troubleshooting tip: if you cannot find a copy of the font library in the savestate, first confirm that this screen **really did load** this font library
> (the same text may go through a different font library on a different screen; see the "current font pointer" item in 07 · Debugging and MCP Breakpoints).

## 4. Root cause: the font library exceeds the RAM buffer the engine reserved

Convert the boundary above into an absolute address and everything falls into place (values for `0A93`, measured in practice in this project):

```
font load address   B = 0x1C03150        (fixed, identical across sessions)
start of corruption = B + 0x29000
engine static data immediately after it starts at E = 0x1C2C150 = B + 0x29000     ← the boundary matches exactly
```

In other words: **the usable area the game reserved for this font library is only `0x29000` = 167,936 bytes**,
immediately followed by the engine's own data (in this project a **512-byte** structure, located by the "font library end" constant).
Our localized font library, however, is **190,976 bytes**, exceeding it by 23,040 bytes = **180 glyph slots**
(slot numbers counted as "which glyph within the bitmap", starting from 0; that is, everything after the 1025th glyph).

Why does the original release not have this problem? Do the capacity arithmetic and it becomes clear:

| | Bitmap offset | Glyph count | Bitmap bytes | Total font library size | Exceeds the reserved area (`0x29000`)? |
|---|---|---|---|---|---|
| Original | `0x67E0` | 877 | 112,256 | 138,848 | ✅ comfortable (28 KB to spare) |
| Localized | `0x8F80` | 1205 | 154,240 | 190,976 | ❌ **23,040 B over** |

The localized build uses more characters than the original, so the bitmap region keeps growing onward, **past the room the game left for it**.

## 5. Capacity budget: work out "what the ceiling in glyphs is" first

This budget can be computed **before you start adding glyphs**, so you do not waste the effort:

```
bitmap bytes available = E − (B + bitmap offset)              # E = start of the engine data immediately after the font library
maximum glyph count    ≈ bitmap bytes available / bytes per glyph
```

Substituting this project's values: `E − B = 0x29000`, bitmap offset `0x8F80` ⇒
`(0x29000 − 0x8F80) / 128 = 131,200 / 128 = 1025` glyphs.

In other words: **in the original game's memory layout, this font library can hold at most 1025 characters** (including ASCII/symbols).
The localization needs 1205 ⇒ there are two paths:

| Option | Feasibility |
|---|---|
| A. Slim down to within 1025 characters | ❌ not feasible in this project: "1035 Han characters + 95 ASCII" alone is 1130 slots; merging range tables squeezes out at most a few dozen more slots, still not enough |
| B. **Move the font library out of the reserved area** and let the engine know the new boundary | ✅ feasible, see below |

> This budget holds for every bitmap font library that has "a fixed load address + other data immediately after it".
> Run the arithmetic before you grow a font library; it is far cheaper than hunting through savestates afterwards.

## 6. A cheap decisive experiment: swapping glyphs between slots

Before changing any code, spend ten minutes on this experiment to separate "a content problem" from "a position problem" once and for all:

> **Swap** the glyph in **one slot you know is safe** with the glyph in **one slot you know is a victim** (swap only the bitmap data; the text stays the same).

Result measured in practice in this project: after moving the glyph data of `满` (a safe slot) to the victim slot's position,
**what is broken on screen is no longer the position of that original character, but the text that "that slot" maps to**;
conversely, put the victim character's glyph in the safe slot and it displays normally.

**Conclusion: which character is victimized is decided by "the glyph slot / data offset", and has nothing to do with the text content or with the renderer.**
This is the same kind of bisection thinking as "put the original data at the appended position" in 05 · Packaging and ISO —
**change one variable and see what the symptom follows.**

## 7. The fix: move the font library outside the ELF segments

The idea is straightforward: since everything past `B + 0x29000` is taken by the engine, **put the font library somewhere roomier**
and change both of the ELF's "font library base address" and "font library end" constants.

### 7.1 First, establish a reliable VA ↔ file-offset mapping

The prerequisite for editing an ELF is "knowing at which offset inside the file a given virtual address lives". Do not approximate by intuition; compute it from the program headers:

```
file offset = VA − (p_vaddr − p_offset)        # for the LOAD segment that contains that VA
```

The main executable ELF in this project has a text segment with `p_offset = 0x100` and `p_vaddr = 0x100000`, so:

```
file offset = VA − 0xFFF00
```

This repository's `tools/elf_addr.py` can print all of this directly: the `info` subcommand lists every LOAD segment and its respective delta, and
`map <ELF> <address>` tells you which class a given VA falls into — "file data / runtime-only mapping (BSS) / hole (RAM outside any segment)"
— **this distinction matters a lot when you pick a relocation placement**.

⚠️ **This mapping is a pitfall we already chased down**: an early script used an "assemble it yourself from the program headers" approach,
and ended up off by `0x100` overall (every instruction it fetched was wrong, and wrong conclusions were even drawn from them).
**Always use `VA − 0xFFF00`, and before every ELF edit reverse-check one known instruction with it as a sanity check.**

### 7.2 Find every site that references the "font library base address / font library end"

In MIPS a 32-bit constant is assembled from `lui` + `addiu`, so searching the disassembly for the **high/low 16-bit combinations** of these two constants
finds every reference site (this repository's `tools/elf_addr.py find-const` does exactly this: it also finds the paired
`addiu`/`ori` and checks whether the registers match). Measured in practice in this project:

```
font base   0x1C03150 = lui 0x1C0 + addiu +0x3150     4 occurrences
font end    0x1C2C150 = lui 0x1C3 + addiu −0x3EB0     3 occurrences
```

> A mnemonic worth remembering: MIPS instructions are fixed-length 4 bytes and **stored little-endian**, and `lui`'s immediate occupies exactly the low 16 bits of the instruction word,
> so **the immediate's low byte is that instruction's first byte in the file** — "change `lui 0x1C0` to `lui 0x1D7`"
> in a hex editor means **changing 1 byte** (`C0` → `D7`). `addiu`'s 16-bit immediate occupies bytes 0–1 in the same way
> (for example `addiu ...,−0x3EB0` is encoded as `50 C1 xx xx`; making it `+0x1B50` gives `50 1B xx xx`).

### 7.3 Pick a new placement

The new address must satisfy all of the following at the same time:

1. **It falls outside every LOAD segment of the ELF** (so it cannot overlap the code/data segments);
2. it is a piece of RAM that is **measured in practice to be unused** (confirm it by savestate comparison + a full playthrough; do not just look and say "this looks empty");
3. leave room at the tail for the **full font library size**, and do not conflict with the growth direction of the heap/stack.

The new base address chosen in this project: `0x1D73150` (the new font library occupies `0x2EA00` = 190,976 bytes).

### 7.4 Patch contents (measured in practice in this project: 10 bytes in total)

> The "VA" column below is the virtual address; the real **file offset = VA − 0xFFF00** (the delta of the text segment in this project) is given in parentheses as well.

| Group | Purpose | Old value → new value | VA (file offset) |
|---|---|---|---|
| A (4 × `lui`) | font library base address | `0x1C03150` → `0x1D73150` | `0x24D764`(`0x14D864`), `0x24DBB0`(`0x14DCB0`), `0x24DBC8`(`0x14DCC8`), `0x24DD08`(`0x14DE08`) |
| B (3 × `lui`) | font library end (start of the engine data) | `0x1C2C150` → `0x1DA1B50` | `0x24D768`(`0x14D868`), `0x24DBCC`(`0x14DCCC`), `0x24DD0C`(`0x14DE0C`) |
| B (3 × `addiu`) | low 16 bits of the end constant | `−0x3EB0` (`50 C1 A5 24`) → `+0x1B50` (`50 1B A5 24`) | `0x24D778`(`0x14D878`), `0x24DBD8`(`0x14DCD8`), `0x24DD18`(`0x14DE18`) |

Each reference site changes only **1 byte** (`lui` changes the first byte of the instruction word; `addiu` changes the 2nd byte,
i.e. file offset `0x14D879` / `0x14DCD9` / `0x14DE19`), for a total of **10 bytes**.

**But we recommend you do not hand-edit it.** Generate it with a single command from this repository's tools:

```bash
python tools/elf_addr.py patch <unpatched ELF> 0x1C03150 0x1D73150 --out step1.elf
python tools/elf_addr.py patch step1.elf        0x1C2C150 0x1DA1B50 --out final.elf
```

It finds every reference site automatically, decides which bytes need changing (including "the new constant's low 16 bits changed too, so the `addiu` has to be changed as well"),
and **writes a copy only — it never modifies anything in place**. This project's final ELF was generated by exactly this command —
the result is **byte-for-byte identical** to the hand-patched version from back then (same md5).

**Why the "end" constant must be changed along with it** — this is the second pitfall this project stepped into, and it deserves a note of its own:

> The first version of the relocation **only touched the high 16 bits of "base address" and "end"** (4 × `lui` + 3 × `lui`),
> that is, it let the end constant **move along with the base address and keep the relative relationship `base address + 0x29000` unchanged** (a very natural thing to do),
> and the result was that **4 slots were still broken**.
> The reason: that 512-byte block of engine data is **located via the "font library end" constant**, so wherever the font library moved, it followed,
> and so it landed at `new base address + 0x29000` — while the new font library is much larger than `0x29000`,
> that data **landed right in the belly of the new font library** and went on covering glyph slots 1025–1028.
> Only after "end" was changed to **the new font library's own real end** (`new base address + font library size` = `new base address + 0x2EA00`,
> that is, after the low 16 bits of the 3 × `addiu` were changed too) did the engine data land **after** the font library, and the problem disappeared completely.

Lesson: **when you relocate the object described by a "base address + end" constant pair, you must change both,
and "end" must express the new object's own real length rather than reuse the old object's boundary.**

## 8. Side effect of editing the ELF: the emulator's game CRC changes

**This section is where release goes wrong most easily; make sure you read it to the end.**

When it boots a game, the emulator computes a **game identification CRC** (PCSX2 does this in `GetCRC()` in `pcsx2/Elfheader.cpp`).
Measured in practice in this project, the algorithm is:

```
CRC = the 32-bit little-endian words of the whole ELF file, XORed word by word (a tail shorter than 4 bytes is ignored)
```

> Note: this project's ELF length is a multiple of 4, so "how the tail is handled" does not affect the result;
> with another game, **go by the CRC the emulator actually displays** (visible in the game list/log),
> and use the algorithm above only to **predict** what the value will become after patching.
> This is also an emulator implementation detail that may differ between versions — this project's approach is:
> validate the algorithm against an "unpatched ELF", confirm that the computed value equals the value the emulator displays, and only then use it to predict the new value.

Three values measured in practice (same game, only 10 bytes of the ELF differing):

| Version | ELF patch | game CRC |
|---|---|---|
| Unpatched (`最终修复96` and earlier) | none | `FEBE1992` |
| First relocation (`最终修复98`) | 7 sites (4 base address + 3 **high** 16 bits of end; end still equals "base address + 0x29000") | `FEBE198B` |
| Final version (`最终修复99`) | 4 base-address sites + 6 end sites | `FEBEC38B` |

**Editing the ELF changes the CRC**, and these two kinds of emulator object **are named after the CRC**:

- **per-game settings**: `gamesettings\<serial>_<CRC>.ini`
- **built-in patches**: `patches\<serial>_<CRC>.pnach` (the patch library lives in `resources\patches.zip` in the emulator install directory)

(**The game database GameDB is indexed by serial**, so it is unaffected.)

So on the user side a very strange symptom appears: **"the patches I used to be able to tick off now show an empty list"** —
the patches are not gone; it is that "the drawer's label changed, and the contents are still under the old label".

**What to do about it** (three steps in principle + one command from this repository):

```bash
python tools/pcsx2_crc.py <ISO> --install --data "<PCSX2 data directory>" \
       --prog "<emulator install directory>" --old-crc FEBE1992
```

```python
# 1. extract the main executable ELF from the ISO and compute its CRC
crc = 0
for i in range(len(elf) // 4):
    crc ^= struct.unpack_from('<I', elf, i * 4)[0]

# 2. copy the old per-game settings to the new CRC's name
shutil.copyfile(f'gamesettings/{SERIAL}_FEBE1992.ini', f'gamesettings/{SERIAL}_{crc:08X}.ini')

# 3. pull this game's built-in patches out of the emulator's resources/patches.zip and write them under the new name
#    patches/<SERIAL>_<CRC>.pnach
```

**Release discipline**: as soon as the ELF has been touched, you must send **those two configuration files named after the new CRC** (`*.ini` + `*.pnach`)
to your testers together with the image; otherwise all they see is "the patch list is empty and the settings have no effect".
The CRC depends only on the ELF, so **if you afterwards only redo `AC.BIN`/the font library without touching the ELF again, the CRC stays the same**,
and this configuration can keep being reused.

## 9. Acceptance checklist (go through every item after editing the ELF)

Run it against a **new savestate** (one freshly saved inside the patched ISO); only all green counts as fixed:

| Item | Check |
|---|---|
| V1 | a **complete font library header** can be decoded at the new base address (`size`/range count/glyph count/all pointers self-consistent) |
| V2 | the four relocation pointers == new base address + original offset (proving the pointers were correctly rewritten to offsets relative to the new base address) |
| V3 | **there is no font library header at the old base address any more** (proving it really moved, rather than a copy being left behind) |
| **V4** | **bitmap-region diff runs between the RAM copy of the font library and the ISO font library = 0** (**primary criterion**: the engine no longer rewrites glyphs) |
| V5 | spot-check the glyph slots that used to be victimized; they equal the ISO byte for byte |

V4 is the only criterion that truly shows "the problem is cured at the root": the other items can only prove "it was moved to the right place",
and only V4 can prove "**nobody overwrites it any more**". Final measurements in this project: V1–V5 all pass, bitmap-region diff runs = 0,
and real-hardware confirmation on the user side showed the victimized characters back to normal.

V4 is also the item in this toolset that is easiest to reproduce:

```bash
python tools/savestate_ram.py diff "<patched savestate>.p2s" font.bin --addr 0x1D73150 --from 0x8F80
# → [IDENTICAL] this range matches completely: nothing has overwritten it.
```

> Reverse verification matters just as much: run the same set of checks against an **old savestate** (one taken before the patch) and it should **correctly report "failed"**
> (the font library header is still at the old base address, and the victimized slots are still rewritten). Only if the script can tell before from after is the conclusion trustworthy.

## 10. Pitfalls and lessons

1. **A few characters break, and which ones break changes with the scene** → the font library exceeds the RAM buffer the game reserved, and the out-of-bounds part gets covered by engine data →
   take a copy of the font library out of a savestate and compare it byte by byte with the ISO, and see **whether the differences start at a fixed file offset and cut cleanly from there**;
   compute the capacity budget (`end constant − base address − bitmap offset`) before deciding whether to grow the font library or move it.
2. **Assuming "the alignment is right, so everything is fine"** → alignment is only a requirement of the DMA upload; **capacity is another, independent constraint** →
   work out "how many glyphs fit at most" before growing the font library.
3. **Relocating but only changing the base address, and a few slots are still broken** → the small block of data the engine locates via the "end" constant moved along with it into the interior of the new font library →
   when relocating a "base address + end" constant pair, **end must express the new object's own real length**.
4. **Computing VA→file offset by hand from the program headers, off by 0x100** → a faulty mapping implementation, so what you read are misaligned instructions and you draw wrong conclusions from them →
   always use `file offset = VA − (p_vaddr − p_offset)`; in this project that is `VA − 0xFFF00`, and before every edit reverse-check one known instruction against it.
5. **After editing the ELF, users report "the patch list is empty"** → the game CRC changed, and per-game settings and patches are named after the CRC →
   compute the new CRC, copy `*.ini` / `*.pnach` to the new names, and **ship them with the release package**.
6. **All zeros ≠ free (the ELF-editing edition)** → picking a RAM placement that "looks unused" → you must confirm by measurement (savestate comparison + a full playthrough)
   that nobody uses that address range; do not just look at zero bytes.
7. **Releasing after verifying only that "it moved correctly"** → V1–V3 only prove it moved to the right place; they cannot prove nobody overwrites it any more →
   you must take "RAM copy vs ISO bitmap-region diff runs = 0" as the primary criterion, and do reverse verification with an old savestate.
8. **When comparing whole files, the first few bytes never match and get mistaken for corruption** → after the container is loaded, the game rewrites the header's "file offset" pointers
   into runtime absolute addresses → when comparing, use `--from <data region start>` to skip the header and look only at the data region.
9. **`.p2s` will not open (`zipfile` reports method 93)** → the members are zstd-compressed and older standard libraries do not support it →
   install `zstandard`; or just use this repository's `tools/savestate_ram.py` (it reads the compressed data itself via the local file header before decompressing).

## Related documents

- [01 · Unpacking](01-unpacking.md) — extracting `AC.BIN` / `font.bnd` / the `0A93` font library and the main executable ELF from the ISO.
- [03 · Fonts and Rendering](03-fonts-and-rendering.md) — font library structure, bitmap layout, CLUT and 16-byte alignment (the first two of the three constraints in this document).
- [04 · Write-back and Compression](04-write-back-and-compression.md) — writing the rebuilt font library back, and compression compatibility.
- [05 · Packaging and ISO](05-packaging-and-iso.md) — assembling, placement validation, slimming and shifting forward (the image-side counterpart to this document's ELF patch).
- [07 · Debugging and MCP Breakpoints](07-debugging-and-mcp-breakpoints.md) — dynamic evidence-gathering such as breakpoints and byte-by-byte savestate comparison.
- This repository's `tools/`: [`savestate_ram.py`](../../tools/savestate_ram.py) (savestate memory comparison),
  [`elf_addr.py`](../../tools/elf_addr.py) (VA↔offset, constant-reference location and patch generation),
  [`pcsx2_crc.py`](../../tools/pcsx2_crc.py) (game CRC and configuration repair).
