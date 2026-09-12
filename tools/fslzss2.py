#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fslzss2.py — fsliblzs decompressor for Armored Core: Last Raven (PS2).

This tool unpacks the game's `fsliblzs` compressed containers (LZSS streams, PS2
little-endian) and can verify itself byte for byte against a reference dump.
The algorithm below was validated against a disassembly of the decompressor inside
the game executable; the window / length / distance / end-marker semantics are
documented in the repository's docs/en/01-unpacking.md (Chinese: docs/zh/01-unpacking.md).

Container layout:
  offset 0x00 : "fsliblzs" magic (8 bytes)
  offset 0x10 : u32 LE total file size (including the 0x2c-byte header)
  offset 0x14 : u32 LE = 1 (compressed flag)
  offset 0x24 : u32 BE decompressed size
  offset 0x2c : start of the LZSS compressed stream

LZSS stream (flag-byte scheme, LSB first):
  The stream is a sequence of 8-operation groups; each group starts with one flag
  byte, followed by 8 operations. flag bit0 (0x01) belongs to operation 1, bit1
  (0x02) to operation 2, ... bit7 (0x80) to operation 8.
  - flag bit = 0 : literal byte, copied through as-is (1 byte).
  - flag bit = 1 : LZSS back-reference token, 2 bytes [b1, b2]
        distance      = (b1 << 4) | (b2 >> 4)        # 12 bits
        length_nibble = b2 & 0xF
        bytes to copy = length_nibble + 1            # 1..16
        source        = max(0, current output length - 0x1000) + distance
        # note: distance is an offset from the start of the 0x1000-byte sliding
        # window, NOT a relative offset from the current output position
  - end marker: the game only tests `length_nibble == 0` to stop (it does not check
        distance). A legal stream never contains a token with length_nibble == 0 and
        distance != 0, so this implementation simply uses token 00 00 (distance == 0
        and length_nibble == 0) as the end marker; the two are equivalent on real data.
        (distance == 0 with length_nibble != 0 is a legal match: copy from the start
        of the window.)

One special case: if header byte 0x2b == 1 the payload is stored raw and uncompressed
("rawdata") — data starts at offset 0x30 and its length is the BE size at 0x24.

Usage:
  python fslzss2.py selftest <compressed> <reference>
        Decompress <compressed> and compare it byte for byte with <reference>;
        prints the common-prefix length on mismatch. Exit code 0 if identical, 1 otherwise.
  python fslzss2.py decompress <compressed> <output>
        Decompress <compressed> and write the result to <output>.

Examples:
  python fslzss2.py selftest 0A93.bin 0A93_dec.bin
  python fslzss2.py decompress 0A93.bin 0A93_dec.bin

Exit code: 0 on success, 1 on a failed self-test or a failed decompression.
Nonexistent subcommands print this help text. Read-only: nothing is modified in place
(only <output> is written).

------------------------------------------------------------------------------
中文说明

fsliblzs 解压器 —— AC Last Raven (PS2) 验证版

算法（与游戏本体解压器反汇编结论逐字节比对一致；窗口/长度/dist/结束标记语义详见本仓 docs/zh/01-unpacking.md）:

文件布局:
  offset 0x00 : "fsliblzs" 魔数 (8 字节)
  offset 0x10 : u32 LE 文件总大小 (含 0x2c 字节头)
  offset 0x14 : u32 LE = 1 (已压缩标志)
  offset 0x24 : u32 BE 解压后大小
  offset 0x2c : LZSS 压缩流开始

LZSS 流 (flag 字节制, 位序 LSB 优先):
  流由若干个 8 操作组组成, 每组先一个 flag 字节, 然后 8 个操作。
  flag 的 bit0(0x01) 对应第 1 个操作, bit1(0x02) 对应第 2 个, ... bit7(0x80) 对应第 8 个。
  - flag 位 = 0 : 字面字节, 直接透传 1 字节。
  - flag 位 = 1 : LZSS 回引 token, 2 字节: [b1, b2]
        distance      = (b1 << 4) | (b2 >> 4)        # 12 位
        length_nibble = b2 & 0xF
        复制字节数     = length_nibble + 1            # 1..16
        源位置         = max(0, 当前输出长度 - 0x1000) + distance
        # 注: distance 是相对 0x1000 滑动窗口起点的偏移, 不是相对当前输出位置
  - 结束标记: 游戏侧判定为 length_nibble == 0 即结束（不检查 distance）。
        合法流中不存在 length_nibble==0 且 distance!=0 的 token，因此本实现直接以
        token 00 00（distance == 0 且 length_nibble == 0）作为结束标记，二者在真实数据上等价。
        (distance==0 但 length_nibble!=0 是合法匹配: 从窗口起点复制)

用法:
  python fslzss2.py selftest <压缩文件> <解压对照>   # 逐字节比对
  python fslzss2.py decompress <压缩文件> <输出>
"""
# 用途：解压 fsliblzs 容器（LZSS 流，PS2 小端），提供 selftest / decompress 两个子命令，仅依赖标准库。
import sys

USAGE = (__doc__ or '').strip()

MAGIC = b'fsliblzs'
HEADER_SIZE = 0x2C   # 压缩流从文件偏移 0x2c 开始
WINDOW = 0x1000


def fslzss_decompress(data, start=HEADER_SIZE):
    """解压 fsliblzs 数据, 返回解压后的 bytes。

    data   : 完整压缩文件内容
    start  : 压缩流起始偏移 (默认 0x2c, 即 0x2c 字节文件头之后)
    返回解压结果 bytes。若流非法返回 None。
    若文件头 0x2b 字节 == 1, 表示该文件是"未压缩原样存储"(rawdata):
      数据从偏移 0x30 开始, 长度 = 0x24 处(BE) 解压大小, 直接原样返回。
    """
    if not data.startswith(MAGIC):
        return None
    if data[0x2B] == 1:
        # rawdata: 未压缩, 数据在偏移 0x30, 长度 = 0x24 (BE)
        dec = int.from_bytes(data[0x24:0x28], 'big')
        return data[0x30:0x30 + dec]
    out = bytearray()
    i = start
    n = len(data)
    flag = 0
    bit = 0
    steps = 0
    while i < n:
        if bit == 0:
            flag = data[i]
            i += 1
            bit = 0x01  # LSB 优先
        if (flag & bit):
            # 回引 token: 2 字节
            if i + 1 >= n:
                return None  # 数据截断
            b1 = data[i]
            b2 = data[i + 1]
            i += 2
            dist = (b1 << 4) | (b2 >> 4)
            ln = b2 & 0xF
            if dist == 0 and ln == 0:
                # 结束标记: 游戏侧只看 length_nibble==0；合法流中 dist 必为 0，二者等价。
                return bytes(out)
            length = ln + 1
            base = len(out) - WINDOW
            if base < 0:
                base = 0
            src = base + dist
            if src >= len(out):
                return None  # 非法距离
            for _ in range(length):
                out.append(out[src])
                src += 1
        else:
            # 字面字节透传
            out.append(data[i])
            i += 1
        bit = (bit << 1)
        if bit == 0x100:
            bit = 0
        steps += 1
        if steps > (n - start) * 16 + 16:
            return None  # 防止死循环
    return bytes(out)


def selftest(cfile, dfile):
    comp = open(cfile, 'rb').read()
    expect = open(dfile, 'rb').read()
    print(f'compressed {len(comp)} B, reference {len(expect)} B')
    out = fslzss_decompress(comp)
    if out is None:
        print('decompression failed (returned None)')
        return False
    if out == expect:
        print(f'✅ byte-for-byte identical ({len(out)} B)')
        return True
    else:
        print(f'❌ length {len(out)} vs expected {len(expect)}')
        k = 0
        while k < min(len(out), len(expect)) and out[k] == expect[k]:
            k += 1
        print(f'   longest common prefix {k}')
        return False


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ('-h', '--help'):
        print(USAGE)
        return
    cmd = argv[0]
    if cmd == 'selftest':
        ok = selftest(sys.argv[2], sys.argv[3])
        sys.exit(0 if ok else 1)
    elif cmd == 'decompress':
        cfile = sys.argv[2]
        outfile = sys.argv[3]
        comp = open(cfile, 'rb').read()
        out = fslzss_decompress(comp)
        if out is None:
            print('decompression failed')
            sys.exit(1)
        open(outfile, 'wb').write(out)
        print(f'decompressed {len(comp)} -> {len(out)} B: {outfile}')
    else:
        print(USAGE)


if __name__ == '__main__':
    main()
