#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_mes.py — parse a .mes dialogue script container and dump its dialogue entries.

In-mission radio/dialogue scripts (`sXXX.mes`) are UTF-16LE text inside the inner BND of
each mission container (see docs/en/02-text-and-encoding.md). This script reads the container's tables and prints
the entry table, the pointer ranges and the first text blobs, so you can verify the layout
before editing translations. Stdlib only — it writes nothing.

Layout (inferred from mission 001; different missions may differ slightly, so measure in
practice on your own file):
  0x00: u32 count (number of entries)
  0x04: header configuration area (variable length)
  0x10: 50 x 16-byte entries:
        [01][XX][00 00] [64 00 00 00] [00 00 00 00] [ptr]
        where +0x0C (the last 4 bytes) is a pointer into the secondary pointer table
  0x330: secondary pointer table: 8 bytes per item, [ptr][00 00 00 00], ptr -> text data
  text data: dialogue strings, 2 bytes per character in a custom encoding, plus control
        codes, terminated by 00 00

What it prints: the file name with entry count and file size, the first 8 table entries
(idx / typ / sub / val / pad / ptr), the minimum and maximum entry pointer, the position of
the secondary pointer table with its item count, and the raw bytes of the first 10 text
blobs as hex.

Usage:
  python parse_mes.py <file.mes>
        Parse one .mes container and dump the structure described above.

Example:
  python parse_mes.py s001.mes
        (s001.mes is an inner-BND subfile of mission container 001 — inner id=3, see docs/en/02-text-and-encoding.md.)

------------------------------------------------------------------------------
中文说明

解析 .mes (对话脚本) 文件，提取对话行。
结构 (任务 001 推断):
  0x00: u32 count (条目数)
  0x04: 头部配置区 (变长)
  0x10: 50 条 × 16 字节条目: [01][XX][00 00] [64 00 00 00] [00 00 00 00] [ptr]
        ptr -> 二级指针表
  0x330: 二级指针表: 每条 8 字节 [ptr][00 00 00 00] -> 文本数据
  文本数据: 对话串, 2 字节/字符自定义编码 + 控制码, 00 00 结尾
"""
# 用途：解析 .mes 文本容器（条目表 + 二级指针表 + 文本区），打印结构与文本指针，仅依赖标准库。
import sys, os

def parse_mes(data):
    count = int.from_bytes(data[0:4], 'little')
    # 找第一条 16 字节条目起始: 在 0x04..0x10 之间试探
    # 条目特征: [01][XX][00 00][64 00 00 00][00 00 00 00][ptr], ptr 指向数据区
    lines = []
    # 直接从 0x10 开始读 count 条
    entries = []
    for i in range(count):
        base = 0x10 + i * 16
        if base + 16 > len(data):
            break
        rec = data[base:base+16]
        typ = rec[0]
        sub = rec[1]
        val = int.from_bytes(rec[4:8], 'little')
        pad = int.from_bytes(rec[8:12], 'little')
        ptr = int.from_bytes(rec[12:16], 'little')
        entries.append((i, typ, sub, val, pad, ptr))
        if ptr < len(data):
            # 检查 ptr 处是否是指针表 (8 字节槽) 或文本
            pass
    return count, entries

def read_text_at(data, ptr):
    """从 ptr 读对话串直到 00 00 结尾"""
    raw = bytearray()
    i = ptr
    while i + 1 < len(data):
        if data[i] == 0 and data[i+1] == 0:
            break
        raw.append(data[i])
        i += 1
    return bytes(raw), i - ptr + 2

def main():
    fn = sys.argv[1]
    data = open(fn, 'rb').read()
    count, entries = parse_mes(data)
    print(f'{fn}  count={count}  size={len(data)}')
    # 收集二级指针表起点: 所有条目 ptr 的最小值
    ptrs = sorted(set(e[5] for e in entries if e[5] < len(data)))
    # 打印前几条条目
    for e in entries[:8]:
        print(f'  idx={e[0]} typ={e[1]:02X} sub={e[2]:02X} val={e[3]} pad={e[4]} ptr=0x{e[5]:X}')
    print(f'  min ptr: 0x{min(ptrs):X}, max ptr: 0x{max(ptrs):X}  (ptr 最小值/最大值)')
    # 二级指针表
    t2 = ptrs[0]
    # 读二级指针
    sub_ptrs = []
    p = t2
    while p + 8 <= len(data):
        v = int.from_bytes(data[p:p+4], 'little')
        if v < 0x300 or v >= len(data):
            break
        sub_ptrs.append(v)
        p += 8
    print(f'  secondary pointer table @0x{t2:X}, {len(sub_ptrs)} entries  (二级指针表)')
    # 读每个子指针的文本
    for sp in sub_ptrs[:10]:
        raw, consumed = read_text_at(data, sp)
        print(f'    0x{sp:X}: {raw.hex(" ")}  ({consumed} B)')

# 无参数 / --help：打印用法（缺参数时退出码仍为 1）
if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print((__doc__ or '').strip())
        sys.exit(0 if len(sys.argv) > 1 else 1)
    main()
