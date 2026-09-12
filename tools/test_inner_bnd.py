#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_inner_bnd.py — structural self-check of an inner (named) BND container.

The outer containers hold their sub-files by numeric ID; the *inner* BND files (for
example the task/mission containers) additionally carry a path table, so this script
decompresses such a container and walks its own directory instead of guessing offsets:

  1. Build the compressed container with the sibling fslzss2.py decompressor.
  2. Parse the inner BND: file count at 0x10, then a 16-byte entry table from 0x20,
     each entry being id / offset / size / path_offset (all little-endian).
  3. Take the path table as starting at the first entry's path_offset and read
     NUL-separated ASCII names until the first terminator.
  4. Print, for every entry, its id, offset, size, path offset, resolved name and the
     first 8 raw bytes of the sub-file (a quick sanity check of the payload header).

This is a diagnostic/verification tool, not a converter: it prints what it parsed and
writes nothing.

Usage:
  python test_inner_bnd.py <compressed container>

Examples:
  python test_inner_bnd.py 0A93.bin

Exit code: 0 on success. No arguments prints this help text (exit 0); an unparsable
container raises an assertion error (exit 1).
Dependencies: the standard library plus fslzss2.py from this same directory.

------------------------------------------------------------------------------
中文说明

验证内层 BND 解析：从任务容器解压 -> 按文件表提取 7 个子文件

用法:
  python test_inner_bnd.py <压缩容器文件>
"""
# 用途：解析内层 BND（带路径表，如任务容器），列出文件与路径，依赖同目录的 fslzss2.py。
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fslzss2 import fslzss_decompress

USAGE = (__doc__ or '').strip()

def parse_inner_bnd(dec):
    """解析内层 BND, 返回 (paths, files)
    paths: [path_str, ...]
    files: [(id, offset, size, path_idx), ...]
    """
    assert dec[:4] == b'BND\0', f'not a BND file: {dec[:8]!r}'
    num_files = int.from_bytes(dec[0x10:0x14], 'little')
    # 文件表从 0x20 起, 每条 16 字节: id, offset, size, path_offset
    entries = []
    for i in range(num_files):
        base = 0x20 + i * 16
        eid = int.from_bytes(dec[base:base+4], 'little')
        off = int.from_bytes(dec[base+4:base+8], 'little')
        size = int.from_bytes(dec[base+8:base+12], 'little')
        poff = int.from_bytes(dec[base+12:base+16], 'little')
        entries.append((eid, off, size, poff))
    # 路径表: 第一个条目的 path_offset 就是路径表起点
    paths = []
    p = entries[0][3]
    while p < len(dec) and dec[p] != 0:
        end = dec.index(0, p)
        paths.append(dec[p:end].decode('ascii', errors='replace'))
        p = end + 1
    return paths, entries

def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ('-h', '--help'):
        print(USAGE)
        return
    fn = argv[0]
    comp = open(fn, 'rb').read()
    dec = fslzss_decompress(comp)
    paths, entries = parse_inner_bnd(dec)
    print(f'decompressed {len(dec)} B, {len(entries)} files:')
    for eid, off, size, poff in entries:
        name = paths[eid] if eid < len(paths) else f'?{poff:X}'
        print(f'  id={eid} off=0x{off:X} size=0x{size:X} ({size}) path_off=0x{poff:X} -> {name}')
        # 打印文件头
        hdr = dec[off:off+8]
        print(f'      head: {hdr!r}')

if __name__ == '__main__':
    main()
