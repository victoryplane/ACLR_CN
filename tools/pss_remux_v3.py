# -*- coding: utf-8 -*-
"""
pss_remux_v3.py — PSS remuxer v3: strict replica of the original structure — fixed 16 KB
packs + 0xBE padding + sequence_end pushed inside the last video PES.

Goal: not merely "it plays", but "the game's demuxer accepts it". The pack header template,
the system header and the audio are all inherited from the original file; only the video PES
packets are replaced with newly encoded ones (see docs/en/06-pss-video.md).

Key points that keep the output identical in structure to the original:
1. Every pack is a fixed 16384 bytes (14-byte pack header + PES packets + a 0xBE padding
   stream filling the rest).
2. PES packets never cross a pack boundary.
3. sequence_end (00 00 01 B7) is appended inside the payload of the last video PES packet
   (not as a standalone PES packet).
4. The ending order matters (see docs/en/06-pss-video.md, pitfall 2): the last content pack is
   followed **immediately** by 00 00 01 B9 (the game demuxer's end signal); if the caller
   wants equal length (SIZE larger than the content), the remaining space is filled with
   "pure 0xBE padding packs" placed **after** the B9, never a long run of padding before the
   B9 (otherwise playback must read through all that padding before reaching B9, which shows
   up as a black screen for over ten seconds).
   Genuine shortening: SIZE = ceil(content/16384)*16384 + 4, which yields exactly
   "content pack + B9" with no trailing padding.

Notes on the inputs:
  - The original PSS is the audio source: its 0xBD audio PES packets are reused verbatim, and
    the pack header template and system header are copied from it.
  - The new video is an FFmpeg vob containing 0xE0 video PES packets with PTS/DTS (encode with
    `-c:v mpeg2video ... -f vob`; `-c:v copy` produces no DTS and cannot be interleaved).
  - FFmpeg's vob muxing adds a start delay to the video, so the video timeline is shifted by
    `offset = video start PTS - audio start PTS`, and the PTS/DTS in the video PES headers are
    rewritten accordingly.
  - The output is either a standalone .pss file (7th argument) or the remuxed data written
    back into a copy of the ISO at a given LBA (5th/6th arguments + 4th LBA).

Usage:
  python pss_remux_v3.py <original-audio.PSS> <new-video.vob> <target-SIZE> [LBA] [ISO_IN] [ISO_OUT] [out.pss]
        <target-SIZE> is a byte count, decimal or 0x-prefixed hex.
        Write a .pss file:            give only the 7th argument.
        Write back into an ISO:       give LBA, ISO_IN and ISO_OUT (no 7th argument).
        LBA and ISO_IN/ISO_OUT are optional; at least one output form is required.

Examples (SIZE is read with int(value, 0), i.e. plain decimal or a 0x prefix; 77119492 B =
0x498C004 is the shortened size of the ACLR opening CG from docs/en/06-pss-video.md):
  python pss_remux_v3.py movie01.pss video.vob 77119492 32200 game.iso game_patched.iso
        Remux the new video with the original audio and write the result into a copy of the
        ISO at LBA 0x7DC8 (32200), leaving the source ISO untouched.
  python pss_remux_v3.py movie01.pss video.vob 0x498C004 "" "" "" movie01_new.pss
        Only produce a standalone .pss (77119492 bytes); the empty arguments simply mean
        "no ISO write-back" and "no LBA".
  python pss_remux_v3.py movie01.pss video.vob 77135876 "" "" "" movie01_short.pss
        Same content, but SIZE = ceil(77119492/16384)*16384 + 4 = 77135876, i.e. the genuine
        shortening form: "content pack + B9" with no trailing padding.

------------------------------------------------------------------------------
中文说明

PSS 重封装 v3：严格复刻原版结构 —— 固定 16KB pack + BE padding 填充 + seq_end 塞入最后视频 PES。

与原版结构一致的关键点：
1. 每个 pack 固定 16384 字节（14B pack 头 + PES + 0xBE padding 流填满）。
2. pack 内 PES 不跨 pack 边界。
3. sequence_end(00 00 01 B7) 追加在最后一个视频 PES 的 payload 内（非独立 PES）。
4. 收尾顺序（重要，见 docs/zh/06-pss-video.md 坑 2）：最后一个内容 pack 之后**立即**写
   00 00 01 B9（游戏 demuxer 的结束信号）；若调用方要求等长（SIZE 大于内容），
   剩余空间用「纯 BE padding pack」补在 **B9 之后**，绝不把大段 padding 放在 B9 前面
   （否则播完还要读整段 padding 才碰到 B9，表现为黑屏十几秒）。
   真缩短用法：SIZE = ceil(内容/16384)*16384 + 4，输出即「内容 pack + B9」，无尾部 padding。
"""
# 用途：PSS 重封装最终版（固定 16KB pack + BE padding + seq_end），严格复刻原版结构；可输出 .pss 或写回 ISO。
import os, sys, shutil, struct
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pss_remux import parse_ps, enc_ts, make_pack, extract_system_header, extract_first_pack

PACK_SIZE = 16384
MIN_BE = 6  # 00 00 01 be + 2B plen 的最小长度


def make_be_pes(total_len):
    """Build a 0xBE padding-stream PES of exactly total_len bytes (plen = total_len - 6, body 0xFF)."""
    assert total_len >= MIN_BE, f'BE needs at least {MIN_BE} bytes  (BE 至少 {MIN_BE} 字节)'
    plen = total_len - MIN_BE
    return b'\x00\x00\x01\xbe' + struct.pack('>H', plen) + b'\xff' * plen


def remux(video_pes_list, audio_pes_list, pack_tpl, syshdr, size):
    """Pack the (key, pes_bytes) lists into 16 KB packs and return exactly `size` bytes (ending with b9)."""
    merged = []
    vi = ai = 0
    while vi < len(video_pes_list) or ai < len(audio_pes_list):
        if ai >= len(audio_pes_list) or (vi < len(video_pes_list) and video_pes_list[vi][0] <= audio_pes_list[ai][0]):
            merged.append(video_pes_list[vi]); vi += 1
        else:
            merged.append(audio_pes_list[ai]); ai += 1

    out = bytearray()
    syshdr_done = False
    buf = None
    last_scr = 0

    def flush():
        nonlocal buf, out, last_scr
        if buf is None:
            return
        r = PACK_SIZE - len(buf)
        if r > 0:
            assert r >= MIN_BE, f'BE needs at least {MIN_BE} bytes  (剩余 {r} 字节不足 BE)'
            buf += make_be_pes(r)
        assert len(buf) == PACK_SIZE, len(buf)
        out += buf
        buf = None

    for key, pes in merged:
        if buf is not None and len(buf) + len(pes) > PACK_SIZE - MIN_BE:
            flush()
        if buf is None:
            scr = max(0, key - 1000)
            last_scr = scr
            buf = bytearray(make_pack(pack_tpl, scr))
            if not syshdr_done:
                buf += syshdr
                syshdr_done = True
        buf += pes
    flush()

    # Ending: B9 follows the last content pack immediately (the end signal must not be pushed
    # back by padding); then pad up to SIZE if required.
    if len(out) > size - 4:
        raise SystemExit(f'content overflows the target: {len(out)} > {size-4}  (内容超限)')
    pad_after = size - 4 - len(out)
    if pad_after > PACK_SIZE:   # 等长模式且内容明显短于原文件：提示改用真缩短
        print(f'⚠️ equal-length mode will append {pad_after} B of padding after the B9 (about {pad_after/1048576:.1f} MiB); '  # 等长模式
              f'the content only occupies {len(out)/(size)/100:.1f}%. Consider "genuine shortening + shifting the following files forward" instead (docs/en/06-pss-video.md, approach B).')
    out += b'\x00\x00\x01\xb9'          # end signal: B9 appears immediately after the content
    while len(out) + PACK_SIZE <= size:  # equal-length padding always goes after the B9
        out += make_pack(pack_tpl, last_scr) + make_be_pes(PACK_SIZE - 14)
    remain = size - len(out)
    if remain > 0:
        out += make_pack(pack_tpl, last_scr)
        r = remain - 14
        assert r >= MIN_BE, f'only {remain} bytes left at the end  (末尾剩余 {remain})'
        out += make_be_pes(r)
    assert len(out) == size, (len(out), size)
    return bytes(out)


def load_video_seq(vob_path, offset, seq_end=True):
    """Parse the FFmpeg vob's video PES, subtract `offset`, rewrite PTS/DTS and push seq_end into the last video PES."""
    data = open(vob_path, 'rb').read()
    vpkts = parse_ps(data, {0xE0})
    seq = []
    last_vkey = 0
    for p in vpkts:
        has_pts = (p[5] & 0x80) != 0
        has_dts = (p[5] & 0x40) != 0
        if has_dts:
            last_vkey = p[2]
        elif has_pts:
            last_vkey = p[1]
        key = last_vkey - offset
        pes = bytearray(p[3])
        if has_pts:
            pes[9:14] = enc_ts(max(0, p[1] - offset), 0x21)
            if has_dts:
                pes[14:19] = enc_ts(max(0, p[2] - offset), 0x11)
        seq.append((key, bytes(pes)))
    if seq_end and seq:
        # append 00 00 01 b7 inside the payload of the last video PES (the true end of the ES,
        # continuation packets included)
        key, pes = seq[-1]
        pes = bytearray(pes)
        plen = (pes[4] << 8) | pes[5]
        pes[4:6] = struct.pack('>H', plen + 4)
        pes += b'\x00\x00\x01\xb7'
        seq[-1] = (key, bytes(pes))
    return seq


def main():
    if len(sys.argv) < 4:
        print('Usage: python pss_remux_v3.py <original-audio.PSS> <new-video.vob> <target-SIZE in bytes> [LBA] [ISO_IN] [ISO_OUT] [out.pss]  (用法)')
        sys.exit(1)
    PSS = sys.argv[1]
    VOB = sys.argv[2]
    SIZE = int(sys.argv[3], 0)
    LBA = int(sys.argv[4], 0) if len(sys.argv) > 4 else None
    ISO_IN = sys.argv[5] if len(sys.argv) > 5 else None
    ISO_OUT = sys.argv[6] if len(sys.argv) > 6 else None
    OUT_PSS = sys.argv[7] if len(sys.argv) > 7 else None

    audio = open(PSS, 'rb').read()
    apkts = parse_ps(audio, {0xBD})
    a0 = min(p[1] for p in apkts if p[1] > 0)
    # start PTS of the vob video (used for the offset)
    vdata = open(VOB, 'rb').read()
    vpkts = parse_ps(vdata, {0xE0})
    v0 = min(p[1] for p in vpkts if p[1] > 0)
    offset = v0 - a0
    print(f'audio PES {len(apkts)}  video PES {len(vpkts)}  a0={a0} v0={v0} offset={offset}  (音频/视频 PES 计数, offset = v0 - a0)')

    aseq = [(p[1], bytes(p[3])) for p in apkts]
    vseq = load_video_seq(VOB, offset)
    pack_tpl = extract_first_pack(audio)
    syshdr = extract_system_header(audio)
    print('pack template:', pack_tpl.hex(' ').upper(), 'syshdr', len(syshdr), 'B  (pack 模板与系统头长度)')

    out = remux(vseq, aseq, pack_tpl, syshdr, SIZE)
    print(f'output {len(out)} B (should equal {SIZE})  (输出字节数应等于目标 SIZE)')

    if OUT_PSS:
        with open(OUT_PSS, 'wb') as f:
            f.write(out)
        print(f'wrote .pss: {OUT_PSS}  (已写出 .pss)')
    if ISO_IN and ISO_OUT:
        if LBA is None:
            print('writing back into an ISO requires the LBA argument  (写回 ISO 需要 LBA 参数)'); sys.exit(1)
        if os.path.exists(ISO_OUT):
            os.remove(ISO_OUT)
        shutil.copyfile(ISO_IN, ISO_OUT)
        with open(ISO_OUT, 'r+b') as f:
            f.seek(LBA * 2048)
            f.write(out)
        print(f'wrote back @ LBA 0x{LBA:X} OK  (写回完成)')
        print(f'output ISO: {ISO_OUT}  (输出 ISO)')
    elif not OUT_PSS:
        print('no output specified: pass ISO_IN/ISO_OUT, or the 7th argument for a .pss file  (未指定输出)')
        sys.exit(1)


if __name__ == '__main__':
    main()
