# -*- coding: utf-8 -*-
"""
extract_pss.py — extract .PSS movie files from a PS2 ISO using an LBA/size manifest.

Every file in an ISO9660 image has an LBA (logical block address, 1 block = 2048 bytes) and a
byte size, so extracting a movie is one seek plus one read: seek to `LBA * 2048` and read
`size` bytes (see docs/en/06-pss-video.md, section 2). The list of `LBA=0x... <path>.PSS` entries comes from
your own ISO9660 directory parser or from an unpacking tool's file manifest.

The manifest is a text file, one entry per line, each line containing something like
`LBA=0x... 目录/文件名.PSS`; the byte size is read from the preceding size column when the line
has the form `<letter> <size> LBA=`. The `MOVIE` directory component is stripped from the
stored path, the result is written under the output directory, and every line printed reports
the file name, its size in bytes and the relative output path. Stdlib only; the output
directory (and subdirectories) is created if needed.

Usage:
  python extract_pss.py <ISO path> <LBA/size list> <output directory>
        Read every listed .PSS out of the ISO into the output directory.

Example:
  python extract_pss.py game.iso movie_lba.txt out/movies

------------------------------------------------------------------------------
中文说明

按 LBA/size 清单从 PS2 ISO 提取 .PSS 视频文件。
清单为文本文件，每行含类似 "LBA=0x... 目录/文件名.PSS" 的字段（可由 ISO9660 解析自行生成）。
"""
# 用途：从 PS2 ISO 按清单中的 LBA/size 抽取 .PSS 文件，仅依赖标准库。
# 清单为文本文件，每行含类似 "LBA=0x... 目录/文件名.PSS" 的字段（可由 ISO9660 解析自行生成）。
import io, os, re, sys

sys.stdout.reconfigure(encoding='utf-8')
if len(sys.argv) < 4:
    print('Usage: python extract_pss.py <ISO path> <LBA/size list> <output directory>')
    sys.exit(1)
ISO = sys.argv[1]
LIST = sys.argv[2]
OUT = sys.argv[3]
os.makedirs(OUT, exist_ok=True)

entries = []
with io.open(LIST, encoding='utf-8', errors='replace') as f:
    for line in f:
        m = re.search(r'LBA=0x([0-9A-Fa-f]+)\s+(\S+\.PSS)', line)
        if m:
            lba = int(m.group(1), 16)
            path = m.group(2)
            m2 = re.search(r'^\s*\w\s+(\d+)\s+LBA=', line)
            size = int(m2.group(1)) if m2 else 0
            entries.append((path, lba, size))

with open(ISO, 'rb') as iso:
    for path, lba, size in entries:
        sub = os.path.dirname(path).replace('MOVIE', '').strip('/')
        out_dir = os.path.join(OUT, sub)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, os.path.basename(path))
        iso.seek(lba * 2048)
        with open(out_path, 'wb') as f:
            f.write(iso.read(size))
        print(f'{path}: {size} B -> {os.path.relpath(out_path, OUT)}')
print(f'extracted {len(entries)} file(s)  (共提取 {len(entries)} 个)')
