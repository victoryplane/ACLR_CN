#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AC.BIN (BND) 容器解析工具 —— AC LR 侦察用
用法:
  python bnd.py list <AC.BIN>                 # 列出全部子文件
  python bnd.py extract <AC.BIN> <id(hex)> <out>   # 提取某个子文件
只读操作。
"""
# 用途：解析 AC.BIN 等外层 BND 容器目录（16 字节槽），列出 / 提取子文件，仅依赖标准库。
import sys, os

MAGIC = b'BND\0'
HDR = 0x20

def load_entries(data, data_start=None):
    """扫描 BND 目录表（0x20 起 16 字节槽），解析有效条目。
    data_start: 数据区起始（表到此为止）。缺省自动检测（第一个有效条目的偏移）。"""
    entries = {}
    # 自动检测数据区起点：第一个偏移有效且大小合理的条目
    if data_start is None:
        pos = HDR
        while pos + 16 <= len(data):
            e = data[pos:pos+16]
            eid = int.from_bytes(e[0:4], 'little')
            off = int.from_bytes(e[4:8], 'little')
            size = int.from_bytes(e[8:12], 'little')
            if off >= 0x1000 and off + size <= len(data) and size > 0 and eid not in entries:
                data_start = off
                break
            pos += 16
        if data_start is None:
            return entries
    pos = HDR
    while pos + 16 <= data_start:
        e = data[pos:pos+16]
        eid = int.from_bytes(e[0:4], 'little')
        off = int.from_bytes(e[4:8], 'little')
        size = int.from_bytes(e[8:12], 'little')
        flags = int.from_bytes(e[12:16], 'little')
        if eid not in entries and off >= data_start and off + size <= len(data) and size > 0:
            entries[eid] = (off, size, flags)
        pos += 16
    return entries

def main():
    cmd = sys.argv[1]
    fn = sys.argv[2]
    with open(fn, 'rb') as f:
        data = f.read()
    assert data[0:4] == MAGIC, '不是 BND 文件'
    entries = load_entries(data)
    print(f'解析到 {len(entries)} 个子文件条目')
    if cmd == 'list':
        items = sorted(entries.items(), key=lambda kv: kv[1][0])
        for eid, (off, size, flags) in items:
            print(f'  ID={eid:04X}  offset=0x{off:X}  size=0x{size:X} ({size})')
        # 汇总：按大小排前 20
        print('\n--- 按大小排序 前 25 大子文件 ---')
        big = sorted(entries.items(), key=lambda kv: -kv[1][1])[:25]
        for eid, (off, size, flags) in big:
            print(f'  ID={eid:04X}  offset=0x{off:X}  size=0x{size:X} ({size})')
    elif cmd == 'extract':
        eid = int(sys.argv[3], 16)
        out = sys.argv[4]
        if eid not in entries:
            print(f'未找到 ID={eid:04X}'); return
        off, size, flags = entries[eid]
        with open(out, 'wb') as o:
            o.write(data[off:off+size])
        print(f'提取 ID={eid:04X}: {out} ({size} bytes)')

if __name__ == '__main__':
    main()
