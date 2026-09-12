# -*- coding: utf-8 -*-
"""
pss_remux.py — shared helper library for PSS (MPEG-PS) handling, used by pss_remux_v3.py.

This module holds the low-level MPEG program-stream primitives; the actual remuxer with a
command line is pss_remux_v3.py. Exported helpers:

  parse_ps(data, stream_ids)
        Walk a program stream and collect the PES packets whose stream id is in `stream_ids`
        (`0xE0` video, `0xBD` audio). Recognises the pack start code `00 00 01 BA` (skipped)
        and PES start codes `00 00 01 xx`; decodes PTS and DTS when the PES flags announce
        them, and returns one record per packet:
        [stream id, PTS (0 when absent), DTS or None, raw PES bytes, file offset,
          PES flags byte 2, header start offset].
  enc_ts(v, prefix=0x21)
        Encode a 33-bit timestamp into the 5 packed bytes a PES header expects
        (prefix 0x21 for PTS, 0x11 for DTS).
  make_pack(tpl, scr)
        Reuse the original file's first pack header as a template and rewrite only the 5 SCR
        bytes for the new timestamp, keeping mux_rate (`0x012663`) and stuffing untouched.
        Always generate pack headers from a real template — a hand-built SCR is where this
        project went wrong before (see docs/en/06-pss-video.md).
  extract_system_header(data)
        Copy the whole `00 00 01 BB` system header section verbatim, so it can be placed in
        the first pack (an empty bytes object when the file has none).
  extract_first_pack(data)
        Return the original first pack header (from `00 00 01 BA` up to the next start code),
        for use as the template described above.

⚠️ The early standalone remuxer with "variable-length packs, one PES per pack" made the game
show a black screen and hang after playback (docs/en/06-pss-video.md, pitfall 1); it is retired. Use
pss_remux_v3.py (fixed 16 KB packs, strictly replicating the original structure) instead.

Usage:
  This is a library: it has no command line of its own and importing it does nothing.
  Running it directly just prints this explanation and exits.
  The remuxing CLI lives in the module that imports it:
  python pss_remux_v3.py <original-audio.PSS> <new-video.vob> <target-SIZE> [LBA] [ISO_IN] [ISO_OUT] [out.pss]

Example:
  python pss_remux_v3.py movie01.pss video.vob 77119492 32200 game.iso game_patched.iso
  python pss_remux_v3.py movie01.pss video.vob 77119492 "" "" "" movie01_new.pss
        (77119492 B is the shortened size of the ACLR opening CG, see docs/en/06-pss-video.md.)

------------------------------------------------------------------------------
中文说明

PSS(MPEG-PS) 处理的公共函数库（供 pss_remux_v3.py 使用）。

提供 parse_ps / enc_ts / make_pack / extract_system_header / extract_first_pack。
⚠️ 早期「变长 pack、一包一 PES」的独立重封装实现会让游戏播完黑屏卡死（见 docs/zh/06-pss-video.md 坑 1），
已弃用；请用 pss_remux_v3.py（固定 16KB pack 严格复刻原版结构）。
"""
import sys

sys.stdout.reconfigure(encoding='utf-8')


def parse_ps(data, stream_ids):
    out = []
    i = 0
    n = len(data)
    while i < n - 3:
        if data[i:i+4] == b'\x00\x00\x01\xba':
            j = data.find(b'\x00\x00\x01', i + 4)
            if j < 0:
                break
            i = j
            continue
        if data[i:i+3] == b'\x00\x00\x01' and data[i+3] in stream_ids:
            sid = data[i+3]
            plen = (data[i+4] << 8) | data[i+5]
            pkt_end = i + 6 + plen
            if pkt_end > n:
                break
            pes = bytearray(data[i:pkt_end])
            flags2 = data[i+7]
            pts = None
            dts = None
            hdr_start = i + 9
            if flags2 & 0x80:
                b = data[hdr_start:hdr_start+5]
                pts = ((b[0] >> 1) & 0x07) << 30 | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)
                if flags2 & 0x40:  # DTS present
                    b = data[hdr_start+5:hdr_start+10]
                    dts = ((b[0] >> 1) & 0x07) << 30 | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)
            out.append([sid, pts if pts is not None else 0, dts, pes, i, flags2, hdr_start])
            i = pkt_end
            continue
        i += 1
    return out


def enc_ts(v, prefix=0x21):
    """把 33bit ts 编码成 5 字节（prefix: 0x21=PTS, 0x31=DTS 高位时用）。"""
    v &= 0x1FFFFFFFF
    return bytes([
        prefix | (((v >> 30) & 0x07) << 1),
        (v >> 22) & 0xFF,
        (((v >> 15) & 0x7F) << 1) | 0x01,
        (v >> 7) & 0xFF,
        ((v & 0x7F) << 1) | 0x01,
    ])


def pack_header(scr):
    scr &= 0x1FFFFFFFF
    b = bytearray(b'\x00\x00\x01\xba')
    b.append(0x44 | (((scr >> 30) & 0x07) << 3) | ((scr >> 28) & 0x03))
    b.append((scr >> 20) & 0xFF)
    b.append((((scr >> 15) & 0x7F) << 1) | 0x01)
    b.append((scr >> 7) & 0xFF)
    b.append(((scr & 0x7F) << 1) | 0x01)
    mux_rate = 0x012663
    b.append((mux_rate >> 16) & 0xFF)
    b.append((mux_rate >> 8) & 0xFF)
    b.append(mux_rate & 0xFF)
    b.append(0xF8)
    return bytes(b)


def extract_system_header(data):
    i = data.find(b'\x00\x00\x01\xbb')
    if i < 0:
        return b''
    plen = (data[i+4] << 8) | data[i+5]
    return data[i:i+6+plen]


def extract_first_pack(data):
    """取原 PSS 第一个 pack header 的原始字节（保证结构合法，避免自己生成 SCR 出错）。"""
    i = data.find(b'\x00\x00\x01\xba')
    if i < 0:
        return b''
    j = data.find(b'\x00\x00\x01', i + 4)
    if j < 0:
        return data[i:i+14]
    return data[i:j]


def make_pack(tpl, scr):
    """用原版 pack 头作模板，只改 SCR 5 字节（保留 mux_rate 与 stuffing）。"""
    scr &= 0x1FFFFFFFF
    b = bytearray(tpl)
    b[4] = 0x44 | (((scr >> 30) & 0x07) << 3) | ((scr >> 28) & 0x03)
    b[5] = (scr >> 20) & 0xFF
    b[6] = (((scr >> 15) & 0x1F) << 3) | 0x04 | ((scr >> 13) & 0x03)
    b[7] = (scr >> 5) & 0xFF
    b[8] = ((scr & 0x1F) << 3) | 0x04 | (b[8] & 0x03)
    return bytes(b)


def main():
    raise SystemExit(
        'Usage: this module is the shared helper library for pss_remux_v3.py and does not remux on its own. (用法)\n'
        'The early "variable-length pack, one PES per pack" muxing made the game show a black screen and then hang after playback (docs/en/06-pss-video.md, pitfall 1); it is retired. (已弃用)\n'
        'Use pss_remux_v3.py instead: python pss_remux_v3.py <original-audio.PSS> <new-video.vob> <target-SIZE> [LBA] [ISO_IN] [ISO_OUT] [out.pss]')


if __name__ == '__main__':
    main()
