# -*- coding: utf-8 -*-
"""fslzss_compress.py — fsliblzs LZSS compressor for Armored Core: Last Raven (PS2) write-back.

Compresses a byte stream into an `fsliblzs` container: a 0x2c-byte header followed by
a greedy LZSS stream, plus a final end marker and 16-byte alignment padding.

⚠️ IMPORTANT WARNING: a lossless decompress round-trip does NOT mean the decompressor
inside the game will accept the file. Before putting compressed data back into the game,
read the repository's docs/en/04-write-back-and-compression.md (Chinese: docs/zh/04-write-back-and-compression.md):
which data may be recompressed and which must keep its original compression.
Rule of thumb: large blocks containing binary data (e.g. part 5xxxx 3D models +
textures) must **not** be recompressed with this tool — keep the original compression.
Plain text (dialogue .mes, briefings, part 6xxxx descriptions) may be recompressed.

Header field 0x20: every original sample is 0x00000100 (256) and this compressor writes
the same value. The game's decompressor does not actually read that field (see
docs/en/01-unpacking.md), but matching the original reduces the risk of other tools or
loaders misjudging the file.

Format (see fslzss2.py, the decompressor whose algorithm matches the game's own
decompressor; see docs/en/01-unpacking.md):
  0x00 'fsliblzs'
  0x10 u32 LE total file size
  0x14 u32 = 1
  0x24 u32 BE decompressed size
  0x2B 0 = compressed / 1 = rawdata
  0x2C start of the LZSS stream

LZSS stream:
  Each group holds 8 operations and starts with one flag byte, LSB first.
  flag bit = 0: one literal byte; = 1: a 2-byte token [b1,b2]
    dist = (b1<<4)|(b2>>4); len = (b2&0xF)+1
    src = max(0, current output length - 0x1000) + dist
  End marker: the game stops as soon as length_nibble == 0; in a legal stream dist is
    always 0, and this implementation emits token 00 00 as the end marker — the two are
    equivalent on real data.

Usage:
  python fslzss_compress.py <input> <output>
        Compress <input> (any bytes) into <output> as an fsliblzs container and print
        the size ratio.

Examples:
  python fslzss_compress.py 0A93_dec.bin 0A93.bin
  python fslzss_compress.py dialogue.mes dialogue.mes.lzs

Exit code: 0 on success. Invalid usage prints this help text and exits non-zero.
Read-only with respect to <input>; only <output> is written.

------------------------------------------------------------------------------
中文说明

fsliblzs LZSS 压缩器 —— AC Last Raven (PS2) 回写用。

⚠️ 重要警告：往返解压无损 ≠ 游戏内解压器一定兼容。压缩后的数据要装回游戏时，
请先读本仓 docs/zh/04-write-back-and-compression.md：哪些数据能重压、哪些必须保持原版压缩。
经验规则：含二进制的大块数据（如部件 5xxxx 的 3D 模型+贴图）**不得**用本压缩器重压，
必须保持原版压缩；纯文本（对话 .mes / 简报 / 部件 6xxxx 描述）可重压。

头部 0x20 字段：原版样本恒为 0x00000100(256)，本压缩器照原版填写；游戏解压器实际不读该字段
（见 docs/zh/01-unpacking.md），但保持与原版一致可降低其它工具/装载器误判的风险。

格式见 fslzss2.py（解压器，算法与游戏本体解压器一致，见 docs/zh/01-unpacking.md）:
  0x00 'fsliblzs'
  0x10 u32 LE 文件总大小
  0x14 u32 = 1
  0x24 u32 BE 解压后大小
  0x2B 0 = 压缩 / 1 = rawdata
  0x2C LZSS 流开始

LZSS 流:
  每组 8 个操作, 先 1 个 flag 字节, LSB 优先。
  flag 位=0: 字面 1 字节; =1: token 2 字节 [b1,b2]
    dist = (b1<<4)|(b2>>4); len = (b2&0xF)+1
    src = max(0, 当前输出长 - 0x1000) + dist
  结束标记: 游戏侧判定 length_nibble == 0 即结束；合法流中 dist 必为 0，
    本实现直接输出 token 00 00 作为结束标记，二者在真实数据上等价。

用法:
  python fslzss_compress.py <输入文件> <输出文件>
"""
# 用途：把任意字节流压缩为 fsliblzs 容器（LZSS，PS2 小端），仅依赖标准库。
# 注意：往返解压无损 ≠ 游戏内解压器一定兼容，对含二进制的大块数据请谨慎使用。
import io, struct, sys
from collections import defaultdict

USAGE = (__doc__ or '').strip()

MAGIC = b'fsliblzs'
HEADER_SIZE = 0x2C
WINDOW = 0x1000
MIN_MATCH = 3
MAX_LEN = 16


def fslzss_compress(data):
    """LZSS 贪心压缩，返回完整 fsliblzs 文件字节。"""
    n = len(data)
    ops = []  # (0, byte) 字面 | (1, dist, length)
    pos_by_key = defaultdict(list)  # 3 字节前缀 -> 位置列表

    i = 0
    while i < n:
        best_len = 0
        best_dist = 0
        maxlen = min(MAX_LEN, n - i)
        if maxlen >= MIN_MATCH and i >= 1 and i + 3 <= n:
            key = (data[i], data[i + 1], data[i + 2])
            base = i - WINDOW
            if base < 0:
                base = 0
            cands = pos_by_key.get(key)
            if cands:
                for j in reversed(cands):
                    if j < base:
                        break
                    dist = j - base
                    if dist < 1 or dist > 0xFFF:
                        continue
                    l = MIN_MATCH
                    while l < maxlen and data[i + l] == data[j + l]:
                        l += 1
                    if l > best_len:
                        best_len = l
                        best_dist = dist
                        if l == maxlen:
                            break
        if i + 3 <= n:
            pos_by_key[(data[i], data[i + 1], data[i + 2])].append(i)
        if best_len >= MIN_MATCH:
            ops.append((1, best_dist, best_len))
            i += best_len
        else:
            ops.append((0, data[i]))
            i += 1

    # 组装流：每组 8 操作；结束标记 00 00 作为部分组的下一个 token 或独立组
    stream = bytearray()
    k = 0
    while k < len(ops):
        grp = ops[k:k + 8]
        n_grp = len(grp)
        is_last = (k + 8 >= len(ops))
        flag = 0
        body = bytearray()
        for idx, op in enumerate(grp):
            if op[0] == 0:
                body.append(op[1])
            else:
                flag |= (1 << idx)
                dist, length = op[1], op[2]
                body.append((dist >> 4) & 0xFF)
                body.append(((dist & 0xF) << 4) | (length - 1))
        if is_last and n_grp < 8:
            # 结束标记作为本组下一个 token（bit 位置 = n_grp）
            flag |= (1 << n_grp)
            body += b'\x00\x00'
        stream.append(flag)
        stream += body
        k += 8
        if is_last and n_grp == 8:
            # 独立组承载结束标记
            stream += b'\x01\x00\x00'

    # 16 字节对齐：原版全部 2469 个 fsliblzs 容器的 total size(0x10) 都是 16 的倍数，
    # 旧版不补齐 → 游戏 DMA/装载器读不满整 quadword → 尾部数据错 → 任务无限加载。
    total = HEADER_SIZE + len(stream)
    pad = (16 - total % 16) % 16
    if pad:
        stream += b'\x00' * pad
        total += pad

    hdr = bytearray(HEADER_SIZE)
    hdr[0:8] = MAGIC
    struct.pack_into('<I', hdr, 0x10, total)
    struct.pack_into('<I', hdr, 0x14, 1)
    # 0x20 字段：原版全部 fsliblzs 容器此处都是 0x00000100(256)，疑似窗口/块大小参数。
    # 早期版本漏写（=0），是「部件贴图损坏」和「任务无限加载」的头号嫌疑根因。
    struct.pack_into('<I', hdr, 0x20, 0x00000100)
    struct.pack_into('>I', hdr, 0x24, n)
    hdr[0x2B] = 0
    return bytes(hdr) + bytes(stream)


def main():
    argv = sys.argv[1:]
    if '-h' in argv or '--help' in argv:
        print(USAGE)
        return
    if len(argv) < 2:
        print(USAGE)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    data = io.open(src, 'rb').read()
    out = fslzss_compress(data)
    io.open(dst, 'wb').write(out)
    print(f'compressed {len(data)} -> {len(out)} B ({len(out) * 100 / max(1, len(data)):.1f}%) -> {dst}')


if __name__ == '__main__':
    main()
