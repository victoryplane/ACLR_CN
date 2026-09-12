# 06 · PSS Video: Extraction, Re-encoding and Remuxing

> This article covers how to extract the PSS videos in ACLR (Armored Core: Last Raven), change the picture, then package them back in the original structure and write
> them to the ISO. PSS is not a proprietary container but essentially an MPEG-2 Program Stream; the real difficulty is making the remux recognized by the game
> demuxer, since the position of the stream end code `00 00 01 B9` decides whether playback transitions normally, hangs, or blacks out for ten-odd seconds.

## Background and goal

ACLR's CG (opening, ending staff roll, button demonstrations, etc.) are stored as `.PSS` files in the ISO's
movie directory. Byte-level disassembly confirms:

- PSS = MPEG-2 Program Stream (MPEG-PS / PS); the file starts directly at the pack start code `00 00 01 BA`,
  with no extra custom header.
- Video track: MPEG-2 video elementary stream (m2v), stream id `0xE0`; ACLR's videos are 640×448 @ 30fps at
  approximately 6~7.5 Mbps.
- Audio track: PS2 ADPCM, carried on private stream id `0xBD`; FFmpeg does not recognize it automatically,
  so do not hand the audio to FFmpeg for re-decoding.

What the Chinese localization has to deal with is the Japanese subtitles "burned into the picture", so the
video pixels must be touched: extract → re-encode the picture (or replace the picture) → remux following the
original structure → write back to the ISO.
For the audio, keeping it as-is and not re-encoding it is recommended.

## Prerequisites

- Python 3.x (only the standard library is used for reading/writing and byte parsing).
- FFmpeg (must include the `mpeg2video` encoder and `-f vob` muxing; install it yourself).
- Your own legally obtained game ISO; your own emulator capable of running PS2 titles (such as PCSX2) for
  final testing in practice.
- A tool that can search for hexadecimal strings (or just use Python) for byte-level self-checks.

## 1. PSS structure: fixed-length packs are a hard constraint

Byte-level disassembly of the original file yields the following key facts (ACLR, measured in practice):

| Item | Value / structure |
|---|---|
| Container | MPEG-2 Program Stream, start code `00 00 01 BA` |
| pack header | 14 bytes: start code 4B + SCR 6B + mux_rate 3B + stuffing 1B |
| mux_rate | `0x012663` (carried over from the original pack header template) |
| stuffing_length | 0 (last byte of the pack header `0xF8`) |
| pack length | fixed 16384 bytes |
| pack contents | multiple PES packets laid back-to-back to fill it; PES packets never cross pack boundaries (the original video packs typically hold 4 video PES packets of about 4090 B each) |
| when it does not fill up | padded with the `0xBE` padding stream: `00 00 01 BE + 2B length + 0xFF×length` |
| SCR | advances roughly by `3000 × ((pack index+1)//2)`, with occasional VBV corrections near the tail, never going backwards |
| video end | `00 00 01 B7` (sequence_end) pushed inside the payload of the last video PES packet, not a standalone PES packet |
| file end | the last 4 bytes `00 00 01 B9` (program_end) |

Audio-side details: the first packet of the `0xBD` private stream carries an SShd header (recording 48 kHz, two
channels, interleave 0x200 and so on), and the SSbd holds the total byte count for the whole audio segment.
Do not touch the audio when remuxing — just fetch the original audio PES packets back verbatim.

Two "end" semantics that must be kept distinct:

- `00 00 01 B7` (sequence_end) is the end marker of the **video elementary stream**;
- `00 00 01 B9` (program_end) is the end marker of the **entire PS stream**, and the in-game demuxer relies on
  it to decide that "playback is finished, a transition can happen".

## 2. Extraction

ISO9660 directories give every file an LBA (logical block address, 1 block = 2048 bytes) and a byte size.
A PSS file starts at `LBA × 2048` and is `size` bytes long. Extraction is a single seek + read:

```python
with open("game.iso", "rb") as f:
    f.seek(lba * 2048)      # lba comes from your own ISO's file table
    data = f.read(size)     # size in bytes
    open("movie.pss", "wb").write(data)
```

`lba` and `size` can be parsed from the ISO9660 directory, or taken from the file manifest that an unpacking tool
generates; the source does not affect the result, as long as the values are accurate.
After extraction, first check that the file begins with `00 00 01 BA`.

## 3. Re-encoding the picture (changing the subtitles)

Picture changes fall into two categories, both of which require decoding the video frames first:

1. **Adding subtitles (hardsub)**: use FFmpeg's subtitle filters (`subtitles`/`drawtext`) to render the Chinese
   subtitles into the picture, then encode back to MPEG-2.
2. **Erasing the original subtitles**: run inpainting on the frames that contain subtitles to remove the Japanese
   text and fill the original positions with Chinese. There is no universal single command for per-frame
   masking; you have to test it in practice with your own toolchain.

Re-encoding constraints (PS2 decoder compatibility):

- Keep the resolution and frame rate identical to the original (ACLR is 640×448 @ 30fps);
- Keep the bitrate conservative (the original is approximately 6~7.5 Mbps — do not blindly raise it);
- Do not re-encode the audio: reuse the original ADPCM audio PES packets directly.

Encode the new video directly to vob so that it carries PTS/DTS:

```
ffmpeg -y -i edited_video.mkv -map 0:v:0 -c:v mpeg2video -b:v 6000k \
  -s 640x448 -r 30 -f vob video.vob
```

(Change the parameters to match the original's resolution/frame rate for your actual source.)

Two FFmpeg traps, stated up front:

- The `mpeg2video` encoder does **not** emit `00 00 01 B7` (sequence_end) at the end of the stream; you have to
  insert it into the last video PES packet yourself.
- If you wrap a bare m2v with `-c:v copy -f vob`, the resulting vob has **no DTS** and cannot be used for
  audio/video interleaving;
  you must re-encode and emit directly with `-c:v mpeg2video ... -f vob` (PTS+DTS are generated during encoding).

## 4. Remuxing: replicating the original structure

The goal of remuxing is not "it plays" but "the game's demuxer accepts it". Proceed in this order:

1. **Keep the system header**: find the `00 00 01 BB` section in the original PSS, copy that whole section
   verbatim, and put it in the first pack.
   Prefer copying the original; do not rebuild it from intuition unless the original file genuinely lacks one.
2. **Keep the pack header template**: take the original PSS's first pack header (the 14 bytes from `00 00 01 BA`
   to the next start code) as a template,
   and when remuxing only rewrite the SCR field in it, keeping mux_rate and stuffing_length.
3. **Parse the original audio**: take the PES packets of the `0xBD` stream and their PTS, and keep them verbatim.
4. **Parse the new video**: take the PES packets of the `0xE0` stream in the vob, and read PTS/DTS.
5. **Align the timeline**: FFmpeg's vob muxing adds a start delay to the video PTS. Compute
   `offset = video start PTS − audio start PTS`, and subtract that offset from both the PTS and DTS in the video
   PES headers so that audio and video land on the same timeline.
6. **Interleave by DTS**: use DTS as the sort key for video (when a continuation packet has no DTS, reuse the
   previous packet's), PTS for audio, and merge the two tracks by time.
7. **Fixed-length packaging**: one pack per 16384 bytes. Write the pack header (template + a new SCR computed
   from that pack's first PES timestamp),
   then push the PES packets in back-to-back; if they do not fit, fill the current pack with `0xBE` padding and
   start another pack.
   **PES packets never cross pack boundaries**. The system header appears only once, in the first pack.
8. **Insert sequence_end**: append `00 00 01 B7` into the payload of the last video PES packet (not a standalone
   PES packet),
   and add +4 to that PES packet's length field.
9. **Finish up**: write `00 00 01 B9` **immediately** after the last content pack. Do not pad with a long run of
   padding before it (see "Pitfalls and lessons").

> In one sentence: the pack header, the system header and the audio are all inherited from the original; only the
> video PES packets are swapped for new ones, and the whole thing is laid out again following the original's
> "fixed-length packs + DTS interleaving + end-code placement".

## 5. Writing back to the ISO

The file size may change on write-back, giving two cases:

**A. In-place equal-length write-back (size unchanged)**

Only usable when the new content ≤ the original file size. The approach: lay out the content in the original
structure, and fill the remaining space with `0xBE` padding up to the original size,
but the **padding must be placed after `00 00 01 B9`** (that is, "content + B9 + padding"), with the LBA and extent
entirely unchanged.
This approach is simple and does not disturb other files, but it retains useless padding space.

**B. Genuine shortening + shifting subsequent files forward (size shrinks)**

When the new content is markedly smaller, the cleaner approach:

1. Truncate the file to the end of the last content pack (align the content to 2048-byte sectors), then append
   4 bytes of `00 00 01 B9`;
2. Compute the number of freed sectors = sectors occupied by the old file − sectors occupied by the new file
   (sectors occupied by a file are counted as `ceil(size/2048)`);
3. Shift **all** files after it forward by the same number of sectors;
4. Update the ISO9660 extents: the shortened file's new size, and the new LBA of every shifted file — **both the
   LE and BE byte orders must be changed**;
5. Truncate the ISO to its new length.

A measured example (ACLR opening CG): the old file was 143,065,092 B (`ceil(143,065,092/2048)` = 69,857 sectors);
of that, the real content (video + audio) occupies only 53.9% (77,108,839 B) and the remaining 62.9 MiB is padding.
After shortening with approach B the file is 77,119,492 B (77,119,488 B of 2048-aligned content + the 4-byte `00 00 01 B9`, i.e. 37,657 sectors), and the **29** following files shift forward by **32,200** sectors (= 69,857 − 37,657, i.e. 65,945,600 B = 62.9 MiB); the ISO shrinks by approximately 62.9 MiB.
For the details of editing extents, see [05 · Packaging and ISO](05-packaging-and-iso.md).

> Before you start, confirm first: does the game read videos **by directory file name** or by **hard-coded LBA**?
> If the LBA is hard-coded, shifting forward breaks the references, so you need another approach. This point must
> be tested in practice for the target game.

## 6. Self-check list

1. **Rough player check**: play it once in a player that supports MPEG-PS (mpv/VLC) and watch the picture,
   the audio/video sync and whether the ending behaves normally.
   Note that players are usually more forgiving than the game's demuxer — passing this step ≠ passing in the game.
2. **Emulator testing in practice**: let the CG play from beginning to end in the emulator, and confirm that it
   enters the next stage **immediately** after the last frame ends,
   with no hang and no long black screen. This is the final criterion.
3. **Byte-level tail check**:
   - Find `00 00 01 B7` and confirm it lies inside the payload of the last video PES packet;
   - Find `00 00 01 B9`:
     · genuine shortening mode: it should be the last 4 bytes of the file;
     · equal-length mode (this repository's `tools/pss_remux_v3.py` already implements the B9-before-padding layout): it follows the last
       content pack immediately, with nothing but padding **after B9**;
   - Look at the B7→B9 distance: in the original the content fills the file, with B7 and B9 both at approximately
     99% and only about 18 KB apart;
     if tens of MB of `0xBE/0xFF` padding (62.9 MiB in this example) sit in front of B9, that is the symptom of "pitfall 2".
4. **Write-back verification**: if you went the shift-forward route, re-check the extent (size/LBA, both byte
   orders) of every shifted file, and confirm the ISO boots and the other files are readable.

## Pitfalls and lessons

### Pitfall 1: variable-length packs / one PES per pack → black screen and hang after playback

- **Symptom**: after re-encoding, the video picture is normal, but at the end it goes to a black screen and hangs
  instead of transitioning; the original video transitions normally.
- **Root cause**: some remuxing method packages the PS as "variable-length packs (about 2KB per pack, one PES per
  pack)", whereas the original uses fixed 16384-byte packs with
  multiple PES packets laid back-to-back per pack. The game's demuxer can still decode the picture from the
  variable-length structure, but it does not consume the end signal `00 00 01 B9` correctly, so playback never ends.
- **How to avoid**: replicate the original's fixed-length pack structure; do not remux PSS with
  "variable-length, one PES per pack".

### Pitfall 2 (the important one): a long run of padding before B9 → black screen for ten-odd seconds before the transition

- **Symptom**: after the last frame plays, a black screen for about ten-odd seconds (the PS2 4x DVD read time) before
  entering the next stage.
- **Root cause**: for the sake of "in-place equal-length write-back", the space saved by re-encoding is filled up to
  the original file size with pure `0xBE` padding (content 0xFF),
  and `00 00 01 B9` is placed at the very end of the file. With a low re-encode bitrate, the real content occupies
  only a bit over half, and the 62.9 MiB (about 46%) after it are all padding,
  with the **padding before B9**. The game's demuxer takes `00 00 01 B9` as the end signal, so after the last frame
  it still has to read/demux all 62.9 MiB of that padding
  before it reaches B9 → black screen. You can observe that the SCR in that region never advances, confirming that
  the delay comes from disc reading/demuxing, not from waiting on timestamps.
- **How to avoid** (choose one):
  1. **Stay equal-length**: `00 00 01 B9` immediately after the last content pack, with the padding after B9
     (`content + B9 + padding`),
     LBA/extent unchanged — safe but wasteful of space;
  2. **Genuine shortening**: truncate to the last content pack (sector-aligned) + B9, shift the subsequent files
     forward as a whole, update the extents, and truncate the ISO (see "Writing back", approach B).
- **Number comparison**: in the original, B7 and B9 are both at approximately 99% and only about 18 KB apart; in the
  pathological version, 62.9 MiB of dead padding sits in front of B9.

### Pitfall 3: FFmpeg does not output sequence_end

- **Symptom**: the `mpeg2video` encoder does not write `00 00 01 B7` at the end of the stream.
- **How to avoid**: append `00 00 01 B7` yourself into the payload of the last video PES packet, and add +4 to that
  PES packet's length.

### Pitfall 4: `-c:v copy -f vob` has no DTS

- **Symptom**: a vob wrapped from bare m2v with `-c:v copy -f vob` has no DTS, and interleaving goes wrong.
- **How to avoid**: re-encode and emit directly with `-c:v mpeg2video ... -f vob`, generating PTS+DTS during
  encoding.

### Pitfall 5: handing the audio to FFmpeg loses it

- **Symptom**: FFmpeg does not automatically recognize PS2 ADPCM (`0xBD` private stream).
- **How to avoid**: fetch the audio PES packets back verbatim from the original PSS — no re-decoding, no
  re-encoding.

## Related documents

- [05 · Packaging and ISO](05-packaging-and-iso.md) — the complete procedure for LBA/extent editing, shifting files
  forward and truncating the ISO.
- [01 · Unpacking](01-unpacking.md) — the basics of getting the LBA/size file table out of the ISO.
