#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 .mes (对话脚本) 文件，提取对话行。
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
    print(f'  ptr 最小值: 0x{min(ptrs):X}, 最大值: 0x{max(ptrs):X}')
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
    print(f'  二级指针表 @0x{t2:X}, {len(sub_ptrs)} 条')
    # 读每个子指针的文本
    for sp in sub_ptrs[:10]:
        raw, consumed = read_text_at(data, sp)
        print(f'    0x{sp:X}: {raw.hex(" ")}  ({consumed} B)')

if __name__ == '__main__':
    main()
