# 05 · Packaging and ISO: Assembling a Bootable Image

## Background and goal

The previous chapters completed the chain "unpack → translate → font library → write-back", and what
we end up with is a pile of modified data: a larger font library, variable-length text containers,
patched menu files, and so on. This chapter handles the last step: **how to safely put these changes
back into the ISO and produce an image that the emulator can boot and the game can read normally**.

The core of this layer is not "write the bytes in" but three things:

1. Understand the **semantics of a file's placement (LBA/extent) and length (size)** in ISO9660, and
   update them in sync after any change;
2. Understand the game's constraints on things like **high offsets and sector alignment** — placement
   cannot be chosen just for convenience;
3. Establish the discipline of **placement verification** — verify with the file table, not by eyeballing
   "this looks empty here".

Every hexadecimal value in this chapter (LBA, offset, magic number) comes from actual measurements of
the original ACLR (PS2) image and the localized image, and can be used directly as a reference for
images with the same structure; but **for your own game, take the concrete values from your own file
table**.

## Prerequisites

- **Your own legitimate game ISO** (this repository provides no game files), plus the unpacked
  containers/files you intend to rewrite;
- **Python 3.x**: the standard library `struct` / `io` / `hashlib` is enough for most in-place reads,
  writes and verification;
- **ISO tools (optional)**: `mkisofs` / `genisoimage` can serve as an alternative route of "extract,
  then rebuild the file system", but rebuilding changes the LBA layout of every file — see the risk
  note below;
- An **authoritative file table**: "every file → starting LBA + byte length", exported from the ISO9660
  directory tree or an unpacking tool. It is the basis for every placement decision in this chapter; do
  not start without it.

The main route recommended here is **in-place patching + updating the directory records** (that is,
`seek`/read/write the ISO file directly, then modify the extent/size fields in the ISO9660 directory),
because this route disturbs the LBA layout the least.

## ISO9660 in a nutshell

PS2 discs commonly use the ISO9660 file system, with a logical sector size of **2048 bytes**. One LBA
number = one 2048-byte sector, and a file's byte offset in the image = `LBA × 2048`.

### 3.1 Finding the root directory from the PVD

- **Primary Volume Descriptor (PVD)**: located at **LBA 16** (byte offset `16 × 2048`).
  Its identifier is `CD001` (appearing at PVD-relative offset `+1`, 5 bytes long).
- The PVD contains a "root directory record", which points to the root directory's LBA and size.
  Measured in practice on this project: the root directory record starts at PVD-relative offset
  `+0x9C`, where the root directory LBA (little-endian) is at `+0x9C + 2`, and the root directory size
  (little-endian) is at `+0x9C + 10`.
- Once you have the root directory LBA, `seek` to `root_lba × 2048` and read `root_size` bytes, and you
  have the sequence of directory records of the root directory. You can then parse them one by one and
  recurse into subdirectories.

### 3.2 Directory record

Every file/subdirectory corresponds to one directory record. Common field offsets (relative to the
start of the record):

| Offset | Meaning |
|---|---|
| `+0` | Length of this record (bytes); use it to jump to the next one while reading |
| `+2` | extent (starting LBA), **little-endian (LE)** |
| `+6` | extent, **big-endian (BE)** — a copy of the same value in the other byte order |
| `+10` | File size (bytes), **little-endian (LE)** |
| `+14` | File size, **big-endian (BE)** |
| `+25` | File flags (`flags & 2` means this is a directory) |
| `+32` | File name length; the file name bytes start at `+33` |

The directory also contains two special entries, `.` and `..`: they are stored as "name length = 1,
name byte = `0x00` / `0x01`". Skip them when parsing the directory tree, and do not treat their fields
as an ordinary file record.

### 3.3 Both-endian

**Key semantics**: extent and size are both stored **both-endian** — the same field is written twice in
the record (LE + BE). When you change a placement or a length, **both ends must be changed at the same
time and hold the same value**; otherwise the emulator/game reads according to the old value and gets
old or misaligned data. After changing them, verify that "LE == BE for all affected records".

## Assembly workflow

### 4.1 Comparison of the three placement forms

| Form | Applicable condition | Modify ISO9660 | Typical scenario |
|---|---|---|---|
| In-place write-back | New file length is **exactly equal** to the original file | No | Equal-length text replacement, equal-length patches |
| Append at end | New file is **variable-length** | Yes: extent + size (both-endian) | Larger font libraries, variable-length translation containers |
| Append inside the container | New data goes into free space/the tail inside the container | No (when the container size stays the same) | Stuffing a new subfile into the orphan region of the main container |

### 4.2 In-place write-back

When the new file length is exactly equal to the old file's, just `seek` to `LBA × 2048` and overwrite
directly; no ISO9660 change is needed. The prerequisite is that **the internal structure of the content
is not broken**: the string pool, pointers, directory entries and so on must all keep their original
layout (the rules for equal-length replacement are in
[04 · Write-back and Compression](04-write-back-and-compression.md)). After writing, read back and
compare to confirm there is no truncation.

Example: for a certain menu file (in-game structural name `OLMENU.BIN`, 1165568 bytes), an
equal-length replacement is written back in place directly at its original LBA (`0x0506`), with no
change to the directory record.

### 4.3 Append at end

When the new file is variable-length, write the new file **after the original image's total sector
count** (i.e. at the end of the ISO file). This is the safest placement, one that "overwrites no
original data". Then update the directory record:

- extent: write LE at `+2`, BE at `+6` (the new LBA);
- size: write LE at `+10`, BE at `+14` (the new byte length).

Example: a new main container of approximately 660 MB (660333653 bytes) was appended after the original image's
total sector count (LBA `1454736`) after growing variable-length; the extent/size of the `AC.BIN;1`
directory record were then updated in both byte orders as described above. After appending, verify that
the header at that LBA is `BND\0`, and confirm that each video header `00 00 01 BA` is unaffected.

The PVD also carries a "volume space size" field. This project's experience is: **leaving that field at
its original value is fine** — the emulator/game reads via the directory records and does not depend on
it (measured in practice: playable and verified); if your target platform demands otherwise, measure it
yourself.

### 4.4 Appending inside the container (updating BND slots)

ACLR's main data file (in-game structural name `AC.BIN`) is itself a BND container: after the header
comes a **directory slot table**, each slot describing one subfile. Measured in practice, the structure
is:

- Container header: `+0x0C` is the container's total size, `+0x10` is the subfile count;
- The slot table starts at `+0x20`, **16 bytes per slot**: `eid` (4) + `offset` (4, at `+4`) + `size`
  (4, at `+8`) + `flags` (4, at `+12`).

When appending a subfile inside the container:

1. The new subfile is written into some block of free space/the tail inside the container, and its
   **offset must be 0x800 (2048)-aligned** — the game reads by sector, and this is a hard requirement;
2. Update that subfile slot's `offset` (`+4`) and `size` (`+8`);
3. If the container as a whole grows, update the total size at container header `+0x0C` (which may in
   turn require changing that container's size in ISO9660).

### 4.5 Complete steps for getting from the PVD to the target directory record

1. `seek(16 × 2048)` to read the PVD, and verify the `CD001` magic number;
2. Read the root directory record from PVD `+0x9C`, and take the root directory LBA (little-endian) and
   size;
3. `seek(root_lba × 2048)` to read the root directory, parsing directory records one by one (advancing
   by the record length at `+0`);
4. Recurse into any subdirectory (`flags & 2`) until you find the record for the target file name;
5. Record the "absolute offset of the target record in the image" together with its extent/size, for the
   subsequent patch;
6. After writing the data, go back to that record offset and update extent/size in both byte orders.

### 4.6 Complete assembly steps (in-place patch route)

1. Read the original image's PVD and get the root directory LBA/size;
2. Walk the directory tree and collect the target file's directory record offset, extent and size;
3. Decide the placement: equal-length → in-place write-back; variable-length → append at end;
4. Write the data (when appending inside the container, update the BND slot + header size at the same
   time);
5. Update the ISO9660 directory record's extent/size (both-endian);
6. Verify (see the next section); if verification fails, stop.

## Placement verification methodology

**Red line: never judge a free region by "it looks all zero".** All-zero bytes can perfectly well
appear **inside** a file (for example, padding inside a video stream); that is not "space nobody uses".

### 5.1 A real blow-up

- While assembling, we looked for the "first free sector" for the new main container, found LBA
  `915676`, and wrote in the comment "first free sector after some large file";
- In reality the video directory already starts at LBA `915631` (ES1.PSS); `915676` is just **an
  all-zero run inside ES1.PSS**, mistakenly taken for free space;
- Result: the new main container (660,333,653 B ≈ 322,430 sectors) was written from `915676` to about
  `1238105`, overwriting the **bulk** of the video region (`915631` ~ `1264644`) — **ES1~ES5 were
  destroyed and the first half of ES6 was overwritten** (the last ~26,540 sectors of the video region,
  i.e. the second half of ES6, were never written to);
- The opening video I1.PSS, however, starts at `1264645`, **after** the overwritten region — hence "the
  opening has video, but the ending is guaranteed to be a black screen", and free missions do not play
  the ending CG, so it was very hard to reproduce.

This case shows: **"looks all zero" does not equal "free"**; only "the file table's ranges do not
intersect" counts.

### 5.2 The correct verification trio

1. **Range non-intersection assertion**: taking the authoritative file table as input, compute each
   file's range `[LBA, LBA + ceil(size/2048))`, then assert that "the new file's placement range" and
   "all original file ranges" are **pairwise non-intersecting**. This step should be written as an
   automated check and run on every assembly.
2. **Magic number spot check**: after writing, read the first few bytes at the key locations and compare
   —
   - BND container header: `BND\0` (`42 4E 44 00`);
   - PSS video header: `00 00 01 BA` (MPEG-PS pack start code).
3. **Read-back comparison**: read the whole written segment back and compare it byte by byte with the
   original bytes, confirming there is no truncation and no misalignment.

## High offset limit

The game imposes a high-offset ceiling on **offset of subfiles inside a container**; appended files
cannot be piled up indefinitely toward the end.

Measured in practice on ACLR: the font library at **626.4 MiB** is readable and parts at **583.5 MiB**
are readable, while **the mission container above 628.8 MiB is not readable**; the mission loader's
offset ceiling is roughly between **626~628 MiB**. The symptom of exceeding the ceiling is that the
mission hangs on the loading screen. The fix is to move the high-offset container as a whole to a
low-offset free region (starting at approximately 519 MiB), so that all mission offsets fall within the
ceiling (after the fix, all mission offsets ≤ 524 MiB).

For troubleshooting this kind of "position-dependent" loading failure, there is one highly effective
control experiment: **put the "original data" at the "appended position"**. If the original content also
fails at the new position, then the problem is **position**, not **content** — one round settles the
direction. (Corroborating counter-example: the same data enters at a low offset and hangs at ~629 MiB;
the content did not change, the only variable is position.)

## Orphan region ≠ blank region

Between the end of the original container (approximately 544 MiB) and the start of the appended region
there may be a stretch that looks free. Measured in practice on ACLR, this approximately 63 MiB range is
**not truly free, but "orphan dead data" that is 94%+ non-zero**: leftovers of old containers that
earlier assembly runs appended and that were later overwritten/reverted, numbering as many as several
hundred.

- They are **referenced by no BND entry at all** — the game reads subfiles only through the BND
  directory, so in theory they can be safely overwritten;
- But they must **never be treated as a "blank region" and occupied at will**: before overwriting, you
  must confirm that "the target range does not overlap any referenced entry", and you must not assume
  its content is zero, nor assume that zero means safe.

In one sentence: **an orphan region is a "reclaimable overwrite target", not a "blank region".**

## Slimming and shifting forward

### 8.1 When slimming is needed

Appending at the end makes the image larger than the original. The size breakdown of ACLR's localized
image (measured in practice):

- The original image is approximately `2,979,299,328` bytes;
- Appending the localized main container at the end adds approximately `660,333,653` bytes → a total of
  approximately `3,639,632,981` bytes;
- But the old main container at LBA `3197` (approximately `544,447,952` bytes) has been dereferenced by
  the directory (`AC.BIN;1` points to the new container at the end), becoming **dead data** that sits on
  544 MB of reclaimable space for nothing.

### 8.2 The basic action of shifting forward

After deleting a stretch of dead data, every file behind it must be **shifted forward** as a whole, with
the directory records updated in sync. ACLR's actual shifting-forward case:

- The dead data starts at LBA `3197`; the following files, such as BMSS, start at LBA `269041`, so the
  shift amount `= 269041 - 3197 = 265844` sectors (`= 544448512` bytes, rounded up for alignment);
- Approximately **37 files** are affected (BMSS + ending videos ES1~ES6 + opening video I1 + key
  configuration demo + mail demo + closing video + new main container); all of their both-endian extents
  were updated;
- After shifting forward, the image shrinks from approximately 3.39 GiB to **2.88 GiB**, saving
  approximately **519 MiB**;
- Verification: file-by-file MD5 comparison of "before vs. after shifting forward" is identical
  everywhere (the shift is lossless), each video header `00 00 01 BA`, the header at the new main
  container's new LBA is `BND\0`, and the extents of the 37 files satisfy LE==BE.

### 8.3 Two disciplines that must be followed

1. **Forward copy**: shifting forward (destination < source) must **copy from low addresses toward high
   addresses**. A reverse copy first overwrites the "source data not yet read out", corrupting the data
   — the first run in this project did it backwards and the video header check failed outright.
2. **Verify before shifting forward**: the game may **hard-code LBA references for certain files**
   (historically, an assembly script hard-coded the main container's LBA and overwrote the video
   region). Shifting forward changes the LBA of every subsequent file; if the game reads by hard-coded
   LBA, it will black-screen/hang after the shift. **You must first dynamically verify whether the game
   reads these files by directory LBA or by hard-coded values; do not touch anything before that is
   verified.**

### 8.4 Video slimming (PSS variable-length truncation)

PSS videos can also be truncated at their true content length to reclaim space: truncate the video
content to the end of the last content pack, and immediately follow it with the MPEG-PS end code
`00 00 01 B9` (B9 follows the content directly; the demultiplexer stops as soon as it reads it). After
truncating, shift the files behind it forward as a whole by the corresponding number of sectors, update
the extent LBA of the affected files, and update that video's size. (For details of the PSS structure,
see [06 · PSS Video](06-pss-video.md).)

## Side effect of changing the ELF: the emulator's game CRC changes

Localization sometimes requires modifying the **main executable ELF** (the typical case: the font
library exceeds the memory region the game reserved, so it must be moved elsewhere and the "base /
end" constants in the ELF changed, see
[08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md)). This brings a consequence
**unrelated to the image data**: **the emulator's game identification CRC changes**.

- The emulator computes this CRC at boot (PCSX2 does so in `GetCRC()` in `pcsx2/Elfheader.cpp`);
  measured in practice on this project, the algorithm = **XOR of every 32-bit little-endian word across
  the whole ELF**.
- But the emulator's **per-game settings** (`gamesettings\<serial>_<CRC>.ini`) and **built-in patches**
  (`patches\<serial>_<CRC>.pnach`, with the patch library at `resources\patches.zip` in the emulator
  installation directory) are both **named by CRC** ⇒ all of them mismatch.
- What the user sees is: **"the patches I could tick before now show an empty list"** — the patches are
  not gone, it is just that "the drawer's label changed while the contents are still under the old
  label". (**GameDB is indexed by serial**, and is unaffected.)

The fix (three steps, scriptable):

1. Extract the ELF from the ISO and compute the **new CRC** with the algorithm above;
2. Copy the old per-game settings `*.ini` to the new CRC's name;
3. Extract the game's intended built-in patches from `resources\patches.zip` and write them as
   `patches\<serial>_<new CRC>.pnach`.

**Release discipline**: whenever the ELF has been touched, you must ship **the two configuration files
named after the new CRC** to testers together with the image, otherwise what they see is "an empty patch
list, settings that do not take effect".

The good news, conversely: **the CRC depends only on the ELF** — if you later rebuild only `AC.BIN`/the
font library without touching the ELF again, the CRC stays the same and this configuration set can be
reused forever.

## Pre-assembly checklist

Confirm each item before you start:

- [ ] You have an authoritative file table (LBA + size per file), and it has been used for the range
  computation;
- [ ] The new file's placement range is **non-intersecting with all ranges** in the file table (or
  explicitly falls in an "orphan region referenced by no entry");
- [ ] Variable-length files are placed at the end of the ISO (after the original total sector count),
  overwriting no original data;
- [ ] The **LE and BE of the ISO9660 directory record's extent/size have both been updated and are
  equal**;
- [ ] Subfiles appended inside a container have an **offset that is 0x800-aligned** and below the game's
  high-offset ceiling (ACLR's mission loader: approximately 626~628 MiB);
- [ ] The container header's total size (`+0x0C`) and the subfile slots' offset/size have been updated
  in sync;
- [ ] Shifting forward (if performed): **forward copy**, tail truncation, all affected extents updated;
- [ ] If the main executable ELF was changed: the **new game CRC** has been computed, and
  `gamesettings\*.ini` and `patches\*.pnach` named after the new CRC are prepared (delivered with the
  package on release, otherwise users see "an empty patch list");
- [ ] The magic number spot check passes (BND header `BND\0`, PSS header `00 00 01 BA`);
- [ ] Reading the written segment back matches the original data byte for byte;
- [ ] If video/main container placements were changed, verify in practice the key paths: opening,
  ending, missions, garage, and save/load.

### 9.1 The four-step quick self-check that must be done after assembly

1. The target file's first few bytes at the **new LBA** are correct (BND container = `BND\0`,
   PSS = `00 00 01 BA`);
2. In the directory record, the file's **extent LE == BE** and **size LE == BE**;
3. The written segment matches the original data **byte for byte** after reading it back;
4. Recompute with the file table: **the new placement range does not intersect any file range**.

Only when all four are green do you move on to testing in the emulator.

## Pitfalls and lessons

| Symptom | Root cause | How to avoid |
|---|---|---|
| In the main-line ending mission, after beating the Boss and before the results screen, there is **always a black screen**; free missions cannot reproduce it | The new main container's placement was misjudged as the "first all-zero free sector", when it was actually an all-zero run inside the ending video ES1.PSS, so it overwrote ending videos ES1~ES5 and the first half of ES6; the opening video I1 is **after** the overwritten region, which is why the opening was normal and only the ending went black | The placement must be at the end of the ISO or a free region verified against the file table; after assembly, automatically assert that the new range does not intersect any file range |
| Individual missions hang on the loading screen and cannot be entered | The mission container was appended above ~628 MiB, and the mission loader cannot read such a high offset (ceiling approximately 626~628 MiB) | Keep appended subfiles' offsets below the ceiling; for a free placement, prefer "the orphan region after the end of the original data"; use a two-way controlled comparison of "original data at the appended position" to separate content from position |
| Video header verification fails after shifting forward | Shifting forward (destination < source) but copying in reverse from high to low, overwriting source data not yet read out | Always **copy forward** (low → high) when shifting forward |
| A range "looks free" so it is occupied directly | The 63 MiB range is 94%+ non-zero; it is leftover old containers from early assembly runs that were later overwritten/reverted (an orphan region), merely referenced by no BND entry | An orphan region is reclaimable, but you must first confirm no entry references it; do not occupy it at will as a "blank region" |
| Black screen or hang after slimming/shifting forward (should it occur) | The game may hard-code LBA references for certain files, and shifting forward changes those files' LBAs | Before shifting forward, dynamically verify where the game's LBA for these files comes from (directory vs. hard-coded); do not touch it lightly until verified |
| After changing the placement, the emulator still reads the old data | Only one end of the ISO9660 extent/size both-endian pair was changed, or the two ends hold inconsistent values | After changing, verify LE==BE and also verify by reading back |
| An image with an ELF patch shows an "**empty patch list**" in the emulator, and per-game settings do not take effect | Changing the ELF ⇒ the game identification CRC changes, while per-game settings and built-in patches are **named by CRC** (GameDB is keyed by serial, so it is unaffected) | Compute the new CRC, copy `*.ini` / `*.pnach` to the new CRC's names, and ship them with the image (see chapter 08 for details) |

## Related documents

- [01 · Unpacking](01-unpacking.md) —— the complete structure of ISO9660, BND and container unpacking, the upstream basis for this chapter's directory/slot table fields.
- [04 · Write-back and Compression](04-write-back-and-compression.md) —— where the modified files come from: equal-length/variable-length write-back and compression compatibility.
- [06 · PSS Video](06-pss-video.md) —— the details of PSS truncation, the B9 end code and video remuxing.
- [07 · Debugging and MCP Breakpoints](07-debugging-and-mcp-breakpoints.md) —— how to dynamically verify the game's LBA references/loader behavior.
- [08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md) —— when the ELF must be changed, how to change it, and the accompanying game CRC change and configuration delivery.
