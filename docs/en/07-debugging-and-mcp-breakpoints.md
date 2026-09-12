# 07 · Debugging and MCP Breakpoints: Driving the Emulator with an AI for Dynamic Reverse Engineering

> This document is about "method". When static disassembly has run out of road, how to have an AI
> use the emulator's debugging interface (a GDB debug stub, a debug server, or a wrapper exposed
> as MCP tools) to set breakpoints, grab registers and dump memory, pushing reverse engineering
> into places static analysis can never reach.
> This document only describes methodology and the scenarios it applies to. It does not provide or
> bundle any debugging tool or MCP implementation; readers must supply and obtain the corresponding
> tools themselves.

## Why it works: the combined value of AI + dynamic breakpoints

Static disassembly covers a large amount of code, but it has inherent blind spots:

- **Indirect calls cannot be followed**: PS2 games make heavy use of `jalr` (register jumps) and
  indirect calls through virtual function tables; the call target is often only known at runtime.
  Some virtual tables even live in the BSS region and are only populated at runtime, so static
  reading cannot reach them.
- **The true value only exists at runtime**: global state such as "the pointer to the font object
  currently in use" may switch every frame. Static analysis only sees the instructions that read and
  write it, not what it actually equals at this moment.
- **Some data is only generated at runtime**: for example the font CLUT (color lookup table) may be
  computed at runtime, and no complete table can be found in the static disassembly.

The value of AI is this: it can read through large stretches of disassembly, understand call chains,
propose falsifiable hypotheses, and work out "which register to read, which memory address to read,
and in which function to set a breakpoint in order to verify this hypothesis".
When these debugging actions are wrapped into an interface the AI can call directly (typically
**MCP, Model Context Protocol**), the AI can complete a closed loop on its own:

**set breakpoint → hit → read registers/memory → compare against expected values → fix the breakpoint condition → try again.**

The role dynamic breakpoints play here is that of a "falsifier": static analysis can only list a
number of "possible chains", while one dynamic hit compresses "possible" into "fact" — which font
object is currently running, what this function actually returned, what this texture finally got
drawn as. Once all three are in hand, the loop is closed.

This cycle turns reverse engineering from the slow trial and error of "guess by hand + edit the file
+ restart to verify" into "many rapid rounds of verification in a row". More importantly, it is
repeatable and traceable: the register values of every hit are objective evidence that can be written
straight into a conclusion, avoiding "it feels like" guesswork.
In real projects, many hard problems that static analysis had chipped at for a long time without
a solution converge on the true culprit within a few rounds of dynamic breakpoints.

## Prerequisites

- **A PS2 emulator** (such as a PCSX2-class one), supplied by yourself, able to run the target game
  normally.
- **Debugging capability supplied by yourself**: pick one or a combination —
  - the emulator's **GDB debug stub** (connect with a multi-architecture GDB to set breakpoints and
    read registers/memory);
  - the emulator's own **debug server / debug extension**;
  - wrap the debugging capabilities above into **MCP tools** for the AI to call directly (this
    repository does not provide that implementation).
- The ability to read MIPS disassembly, to recognize registers such as `$a0/$a1/$v0` and basic
  load/store/jump instructions.
- A legitimate game ISO, supplied by yourself (see the repository README for the legal notice).

You do not need every capability in place at once: first use zero-cost means such as savestates and
frame stepping to verify the direction, then decide whether to bring in a debug server or an MCP
wrapper.

One bonus: PCSX2 savestate files (`.p2s`) are ZIP containers holding a zstd-compressed EE RAM image
(32 MB). Once decompressed you can read the true memory values of one instant of the game **offline**,
which amounts to photographing the "runtime scene" and taking it home to analyze — a cheap substitute
for dynamic debugging.

The concrete approach (no debugger, no breakpoints, the lowest cost):

```python
import io, zipfile, zstandard

with zipfile.ZipFile(p2s) as z:
    info = z.getinfo('eeMemory.bin')   # 32 MiB EE main RAM snapshot
    raw = z.read(info)                 # Python 3.14+: the stdlib supports zstd members natively

with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as r:
    ram = r.read()                     # afterwards you can find / slice / compare byte by byte freely
```

> Version note: the member is **zstd** (ZIP method = 93). From Python 3.14 on, `zipfile` supports it
> natively; earlier versions throw `NotImplementedError` when reading it, and you have to compute the
> data offset from the local file header yourself, pull out the compressed data and hand it to
> `zstandard` (see [08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md) for the
> complete form).

`tools/savestate_ram.py` in this repository turns this into three subcommands you can use directly:
`list` (list members), `locate` (search out "which address this piece of data was loaded to"),
`diff` (compare byte by byte against a memory copy and report contiguous diff runs).

With this 32 MB memory image, many problems that "static analysis cannot pin down" degrade into
**one byte-by-byte comparison**: for example, compare "a copy of some piece of data in memory"
against "the original data in the file" and see **at which offset the difference starts** — this
project used exactly this trick to locate problems of the kind "the font library exceeded the RAM
buffer reserved by the engine, and the out-of-bounds part was overwritten by the engine"
(for the complete case and the fix, see
[08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md)). Such comparisons are
**read-only** and can be repeated at will, far faster than setting breakpoints one by one, and are
also well suited to serving as a pre-filter for a breakpoint plan.

## Approach and workflow

### Step 1: lay the groundwork with static analysis, and list the "hypotheses to verify"

First disassemble offline, find the addresses of the suspicious **decode / load / upload / render**
functions, and for each address write down "if the hypothesis holds, what value should be seen here".

For example, to verify "is the wrong character caused by the rendering layer reading the wrong glyph":

- at the render function entry, `$a0` should equal the tail (row number) of the target character;
- the global font object pointer `0x2B23D0` should equal the object base address of the large font
  library ac0_j1;
- the bitmap address returned by the render function should equal `bitmap base address + tail × 512`.

These "expected values" are the reference baseline for comparing against later breakpoint hits.

### Step 2: reproduce the target screen with a save slot

In the emulator, navigate to the target screen and use a **save slot** to freeze the picture at the
scene. If you suspect the problem happens on a particular frame "while rendering is in progress",
you can first enable **frame stepping** (pausing frame by frame) to hold that frame, then save.

This step does not depend on a debug server; it can be done with only the emulator's built-in frame
stepping and savestates, which makes it the cheapest starting point. A savestate can be read on the
spot, or decompressed into an EE RAM image and read offline; its value is turning "a phenomenon that
happens at an unpredictable time" into "a stable scene that can be sampled repeatedly".

### Step 3: set a conditional breakpoint to narrow the hit range

Setting an unconditional breakpoint directly on a function address is usually drowned by a flood of
hits from irrelevant characters and irrelevant frames.
The correct approach is to **filter with a condition**, breaking only on the one occurrence you care
about. For example:

```
break *0x14dfb0 if $a0 == 847
```

`0x14dfb0` is the tail→bitmap locating function, and `847` is the tail value of one target character.
This way it only hits at the instant that character is rendered, and one hit gets you the key argument.

### Step 4: after the hit, grab registers / memory / textures

After the hit, take these in turn:

- **Registers**: such as `$a0` (argument) and `$v0` (return value), to determine what the function
  actually computed;
- **Memory**: such as the bitmap base address `+0x30` and row byte count `+0x34` in the font object header,
  and the current font pointer `0x2B23D0`, to determine whether the object is the one you thought it was;
- **VRAM/textures**: export VRAM or a texture dump to see directly "what this character finally got
  drawn as".

Taken together, the three kinds of evidence are usually enough to decide which link in a chain is
actually broken.

### Step 5: cross-validate against the static analysis and converge by bisection

Map the actual values back to the expected values listed in step 1:

- all match → this chain is fine, go check the next one;
- one mismatch → that point is the dividing line; keep bisecting upstream/downstream.

Static analysis gives "where it looks suspicious", dynamic analysis gives "what is actually there";
the two advance in alternation.

### Three complementary dynamic routes

1. **Frame stepping + savestates**: zero cost, try it first. It can freeze the instant "while
   rendering" and read memory from it.
2. **Conditional breakpoints reading registers**: precise. Suited to capturing the argument/return
   value of "one particular call".
3. **Code injection log**: the most thorough. Inject a small trampoline at the target function entry
   that writes the key registers to a fixed unused address, then run the game normally, save, and
   read that address offline. No precise breakpoint is needed, which suits cases where the breakpoint
   condition is hard to write or where hits are too frequent.

**Recommended workflow summary**:

1. Reproduce the target screen with a save slot (freeze the frame with frame stepping if necessary);
2. Set conditional breakpoints on the decode / load / render functions;
3. After a hit, export registers, memory and a texture dump;
4. Compare against the static expected values and converge by bisection;
5. Record the conclusions, and clean up any leftover breakpoints.

## Applies when

- **Static disassembly has hit its limit**: when indirect calls, virtual function tables and
  pointers that are only populated at runtime cannot be followed statically.
- **The font/rendering chain is misaligned**: the static data chain (encoding → range table → glyph
  table → bitmap) is entirely correct, yet the game still displays the wrong character, and the wrong
  character can only be caught dynamically at the instant of rendering.
- **The CLUT is unknown**: the color lookup table is generated at runtime or out of order, and cannot
  be found in the static disassembly.
- **Runtime state such as "which screen goes through which font library"**: the same piece of text
  data may go through different font libraries on different screens, so you can only read the current
  font pointer and measure it in practice.
- **When a specific call needs to be confirmed**: for example, whether the argument of some function
  really is the value you think it is.

## Case studies

The cases below are all taken from real problems encountered in ACLR reverse engineering practice,
keeping only the technical path and omitting process details.

### Case 1: the data chain is entirely correct, yet the wrong characters are displayed ("强→刚")

- **Symptom**: paired, systematic wrong characters appear on the mission selection screen:
  强 (0x88AA) → 刚, 击 → 靶, 友 → 味.
- **Static result**: the entire data chain encoding → range table → glyph table → bitmap is correct;
  the render locating function `0x14dfb0` does indeed locate the bitmap with `tail × 512`.
  At the static level there is no foothold for anything that could produce this wrong character.
- **Static counter-evidence**: the tail differences of the three wrong-character pairs show no
  pattern (+110 / +141 / +13), and in "友 → 味" the 友 is a character that already existed in the
  original version and was not changed by the injection — this ruled out the two explanations of
  "injection error" and "a uniform tail offset".
- **Key dynamic step**: measuring the savestate in practice revealed that, at the instant the
  savestate was taken on the failing screen, the current font pointer `0x2B23D0` pointed at a
  27-glyph **menu font**, not at the large font library ac0_j1.
  In other words, that screen **was not going through the statically verified rendering chain at
  all**, but through another chain that had not yet been located.
- **Conclusion**: the wrong character is not inside the known chain. Only by dynamically catching the
  font pointer and the render function arguments at "the instant of rendering" can the chain that is
  actually being used be found.

### Case 2: the TUNE screen's dedicated small font library and the blank 力 glyph

- **Symptom**: in the parameter labels of the booster TUNE screen, 力 (0x97CD) has 100% correct data
  but renders blank, while 量 (0x97CA) renders normally — the two code points differ by only 3.
- **Static + savestate localization**: the labels use neither the large font library ac0_j1 nor the
  dialogue font library 0A93, but a **45-character small font library (ID=9)** inside font.bnd; the
  main executable's decode function `0x14dd00` does not participate in this path at all.
- **Dynamic value**: for problems of this kind — "the data is right but it renders wrong" — static
  analysis can only prove the data is not wrong; it cannot prove that the renderer really decoded
  this code point. You have to set a breakpoint on the decode function to see whether the code point
  really gets decoded, and read the font pointer to confirm which object is actually being used,
  before you can separate "a decoding problem" from "a rendering problem".
- **Boundary**: in the end the mechanism behind this code point was never fully pinned down on the
  renderer side, and it could only be worked around by adjusting the wording of the translation.
  This shows that dynamic debugging can narrow the range quickly, but when faced with irregular
  renderer behavior you still need to leave yourself some room.

### Case 3: reverse-engineering the runtime CLUT pixel by pixel

- **Symptom**: the glyph quality of arena entry names never matched between the local preview and the
  the picture on real hardware.
- **Method**: take the emulator's **texture dump** (a 32×32 RGBA PNG) and align it pixel by pixel
  against the locally stored 4bpp nibble glyphs, reverse-engineering the real runtime
  `nibble → (RGB, alpha)` mapping of the game's CLUT.
- **Result**: the CLUT is **out of order** — the alpha of white-core nib1 is 128 (semi-transparent)
  rather than 255, nib3 is fully transparent, and the brightness of nib2~11 does not vary
  monotonically with the number.
  After re-quantizing the glyphs according to the real CLUT, the preview and the picture on real hardware agreed
  from then on.
- **Experience**: never imagine the CLUT by the linear intuition of "the bigger the number, the
  brighter"; reverse-engineering it from a game texture dump is the correct answer.

### Case 4: catching the BITBLTBUF source/destination addresses of the upload chain

- **Symptom**: after the whole upload/rendering chain had been statically reverse-engineered, one
  contradiction remained — in the code, tail only determines the source bitmap address and does not
  enter the VRAM destination coordinates, which directly conflicts with the phenomenon that "glyph
  splitting still occurs on newly added rows".
- **Method**: this last link could not be dug out statically, so the upload had to be caught
  dynamically: set a breakpoint on the instruction that writes `BITBLTBUF`, capture its source and
  destination addresses, and compare the difference between "a newly added row" and "an original
  row" to locate the root of the contradiction.
- **Conclusion**: some truths (where one upload actually wrote) exist only at runtime and simply
  cannot be seen in the static code.

### Case 5: using breakpoints to catch the load/decode chain and locate which step the "shear" happens in

- **Symptom**: the entry-name font looks "sheared to the right" in the game, but it is unclear
  whether this happens at the font library loading stage or at the per-frame drawing stage.
- **Method**: pause the game at the single-character decode function `0x255830` and follow the call
  chain back from the breakpoint, obtaining the complete load chain "single-character decode ←
  per-character loop ← decompress and upload the texture atlas ← select the font library by flag ←
  font initialization ← screen top level".
- **Conclusion**: this chain executes **at load time** and contains no shearing/transformation
  whatsoever; the "sheared to the right" actually happens at the per-frame drawing stage and has
  nothing to do with the load chain. The breakpoint turned the problem of "following virtual
  functions statically is very slow" directly into the conclusion "a complete call chain has been
  caught".

### Case 6: the whole library's data is correct, individual characters are broken and drift with the scene (the font library crosses the engine's RAM boundary)

- **Symptom**: in in-mission dialogue, the upper half of some character (such as `足`) is missing a
  chunk or misaligned, and it is **equally broken on screen as well** (not a problem with a dump or
  the emulator); within the same mission **only certain characters are broken**, and after switching
  to another scene the broken characters change.
- **Static result**: the entire chain encoding → range table → glyph table → bitmap is correct;
  16-byte alignment is satisfied as well; the upload path disassembles to only a single 128-byte
  transfer whose destination VRAM address is even a constant, so no possibility of any "overwrite"
  is visible.
- **Key dynamic step (and one that needs no breakpoints)**: stop the game at the scene and save a
  savestate, decompress the 32 MB EE RAM, find the font library's copy in memory, and compare it byte by byte
  against the font library in the ISO: the difference **appears after offset `0x29000` within the font
  library** (the first differing byte is `0x29002`, and `0x29000` is exactly the start of the 1025th
  glyph), with contiguous diff runs all the way to the end (61 runs / 1,078 bytes in total); while
  **below `0x29000` not a single byte was touched**.
- **Conclusion**: a hard boundary at a "file offset" ⇒ the RAM buffer the game reserved for this font
  library is only `0x29000`; the font library is bigger, and **those 180 out-of-bounds glyph slots
  live inside the engine's memory and are overwritten by per-frame writes**, so the upload merely
  copies the **already contaminated RAM** faithfully into VRAM. The fix is to **move the font library
  out of the reserved area and change the base address/end constant in the ELF**, not to change the
  translation and not to shrink the font library.
- **Experience**:
  1. **"The data is all correct yet it is broken" does not have "alignment" as its only cause**; when
     the broken position **drifts with the scene**, the first thing you should do is "take a runtime
     memory copy, compare it byte by byte against the file, and see whether the difference begins with a
     clean cut at one **fixed offset**".
  2. **When the same character is broken differently in different scenes**, it is almost certainly a
     "position / overwrite" class problem rather than a "glyph data" problem — this is the same
     approach as the bisection method for "content problems" and as "putting the original data at an
     appended position" in [05 · Packaging and ISO](05-packaging-and-iso.md).

## Notes

- **Tools supplied by yourself**: the GDB stub, debug server, MCP wrapper and so on must all be
  obtained by readers on their own; this repository provides no downloads and bundles no tool itself.
- **Narrow the breakpoint conditions**: if you can filter by register/memory value, you must filter;
  otherwise a flood of irrelevant hits wastes a lot of back and forth.
- **Large memory reads are silently truncated**: read memory in small steps; do not read too large a
  range in one go.
- **Clean up breakpoints thoroughly**: the structure of the list returned by the clear-breakpoint
  interface may not match intuition; remove them one by one and then query again to confirm, so that
  leftover breakpoints do not disturb the next round.
- **Load-type functions only trigger once**: font library loading usually executes only once at
  startup or when entering a screen, so setting the breakpoint after the game is already running is
  too late — set the breakpoint first and then trigger the load, or prefer static/file analysis.
- **Capture values quickly**: tracking continuously for a long time easily freezes the emulator or
  breaks the trace; after a breakpoint hit, take everything you need in one go and do not run a long
  full trace.
- **The debugging interface has limited capabilities**: some debugging interfaces do not offer the
  ability to read VRAM/GS; in that case fall back to a "texture dump" to obtain the VRAM result.
- **R5900 disassembly must be double-checked**: the PS2's EE is an R5900 (a MIPS variant) containing
  MMI/128-bit instructions, so a general-purpose disassembler may mislabel them; do not draw
  conclusions at a mislabeled spot (see below).

## Pitfalls and lessons

**Symptom**: static analysis concluded that the render function "contains no tail multiplication",
yielding the contradictory conclusion that "the two characters should render as the same glyph".
**Root cause**: the R5900's three-operand `MULT rd, rs, rt` writes the low 32-bit result back to both
the GPR `rd` and LO; the general-purpose disassembler mislabeled this instruction as nop, so the
entire `tail × 512` multiplication was missed.
**How to avoid**: for R5900 multiplication/MMI instructions, rely on the authoritative ISA semantics
or the emulator's source code, and do not merely trust the disassembler's label.

---

**Symptom**: a memory read returns what looks like normal data, but the result is clearly missing
a chunk.
**Root cause**: reading too much at once, silently truncated.
**How to avoid**: scan in 64 KB (0x10000) chunks; do not read 256 KB (0x40000)-scale blocks in one go.

---

**Symptom**: the breakpoints were cleared, but they are still there on the next run.
**Root cause**: the field names of the breakpoint list interface differ from what was expected, so the
cleanup logic did not line up.
**How to avoid**: remove breakpoints one by one, and before the next round begins, query again to
confirm the list is empty.

---

**Symptom**: following the drawing functions with breakpoints is extremely slow; following them
statically layer by layer never ends.
**Root cause**: drawing goes through a large number of indirect calls via virtual function tables,
and the tables live in the BSS region, populated only at runtime.
**How to avoid**: do not follow them statically layer by layer; use breakpoints to capture the
"current pointer/register actual value" to locate the function in use.

---

**Symptom**: the breakpoint is set on a load function, but it never hits once the game is running.
**Root cause**: the load already finished at an earlier startup/enter-screen stage, so it had already
been missed when the breakpoint was set.
**How to avoid**: set the breakpoint first, then restart or exit and re-enter the screen to trigger
the load; or confirm the load timing with static/file analysis first.

---

**Symptom**: the preview and real hardware differ enormously, and no amount of adjustment fixes it.
**Root cause**: the CLUT is out of order — the white-core alpha may be 128 rather than 255, and
brightness is not monotonic with the number.
**How to avoid**: reverse-engineer the real CLUT from a game texture dump, then quantize according to
its RGB brightness.

---

**Symptom**: the characters are right, the glyphs are right, the ranges are right, the CLUT is right,
yet the entire font library is garbled/melted.
**Root cause**: the bitmap/CLUT is not **16-byte aligned** (a hard requirement of DMA upload);
the range count n and the glyph count g have different parity → the bitmap offset is misaligned.
**How to avoid**: when changing a binary layout, check alignment/boundaries/parity first, and only
then suspect the content.

---

**Symptom**: it looks like a combination trigger of "A is fine, B is fine, A+B is broken", misleading
you into thinking it is a character-combination problem.
**Root cause**: it is actually a hidden continuous quantity (such as a change in character count
flipping the parity of the range count) varying along with it.
**How to avoid**: lay n / g / bitmap offset mod16 out into one alignment table, and the pattern is
visible at a glance.

---

**Symptom**: individual characters are broken, and **the broken characters change when you switch
scenes**; the data is all correct, the alignment is correct, and the upload code is not wrong either.
**Root cause**: it is not an alignment problem but a **capacity** problem — the font library exceeds
the RAM buffer the game reserved for that font library, the out-of-bounds part is overwritten by the
engine's own data, and on upload it is copied into VRAM as-is.
**How to avoid**: for "the data is all correct yet it is broken", do not only check alignment, check
capacity too: decompress the savestate into EE RAM, take the font library's runtime copy and
**compare it byte by byte** against the ISO, and see whether the difference **begins with a clean cut at one
fixed file offset** (for the criterion, the fix and the subsequent CRC side effects, see
[08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md)).

---

**Symptom**: the disassembler outputs garbage at MMI/128-bit instructions.
**Root cause**: a general-purpose disassembler mislabels them as MIPS32.
**How to avoid**: draw conclusions only in regions that can be reliably disassembled as standard MIPS
instructions; for critical jumps/multiplies and divides, use the emulator's own disassembler or check
by hand.

All of these pitfalls share one thing: **errors in the debugging "tool layer" (silent truncation,
leftover breakpoints, mislabeled instructions) tend to disguise themselves as "wrong conclusions"**.
The order of investigation should be to rule out the tool layer first, and only then doubt the
conclusion.

## Related documents

- [01 · Unpacking: ISO → AC.BIN → BND → fsliblzs](01-unpacking.md)
- [02 · Text and Encoding](02-text-and-encoding.md)
- [03 · Fonts and Rendering](03-fonts-and-rendering.md)
- [04 · Write-back and Compression](04-write-back-and-compression.md)
- [05 · Packaging and ISO: Assembling a Bootable Image](05-packaging-and-iso.md)
- [06 · PSS Video](06-pss-video.md)
- [08 · Font Capacity and ELF Patching](08-font-capacity-and-elf-patching.md) — using "savestate
  byte-by-byte comparison" to locate a font library overwritten by engine memory, plus ELF patching and the
  game CRC side effects.
