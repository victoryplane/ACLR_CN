#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
savestate_ram.py — forensics for "the data is correct but something still breaks".

A PCSX2 savestate (`.p2s`) is a ZIP container whose members are memory/state snapshots
(usually zstd-compressed, ZIP method 93). This tool compares *the copy of some data that exists
in running memory* against *the original data in the file*, byte by byte. The central criterion:

    Does the first difference start at a fixed FILE offset and run on from there?

If so, everything after that offset was overwritten in memory by something else — e.g. a font
library that grew past the RAM buffer the game reserved for it — and the upload/rendering path
merely copies the polluted RAM. This needs no debugger and no breakpoints, which makes it the
cheapest dynamic evidence there is (see docs/en/08-font-capacity-and-elf-patching.md).

Dependencies: standard library; decompressing zstd members needs the `zstandard` package.

Usage:
  python savestate_ram.py list <p2s>
        List the members of a savestate (name / compression method / compressed and raw size).
  python savestate_ram.py extract <p2s> <member> <output file>
        Extract and decompress one member (e.g. eeMemory.bin = the 32 MiB EE main RAM).
  python savestate_ram.py locate <p2s> <file> [--member eeMemory.bin] [--at 0x40] [--len 64] [--max 8]
        Search memory for that slice of the file and report the BASE ADDRESS it was loaded to
        (hit address minus --at).
  python savestate_ram.py diff <p2s> <file> --addr 0x1C03150 [--member eeMemory.bin] [--max-runs 16]
        [--from 0x8F80] [--to 0x2E9C0]
        Compare the file against the memory copy at --addr, count differing bytes and
        **contiguous diff runs**, and point out where the first run starts (the key criterion).
        --from/--to restrict the comparison to a region (for example the bitmap region only,
        skipping the header pointers that get rewritten to absolute addresses at load time).

Examples:
  python savestate_ram.py list "SLPS-25462 (FEBEC38B).01.p2s"
  python savestate_ram.py extract "SLPS-25462 (FEBEC38B).01.p2s" eeMemory.bin ee_ram.bin
  python savestate_ram.py locate "SLPS-25462 (FEBEC38B).01.p2s" 0A93.bin --at 0x40 --len 32
  python savestate_ram.py diff   "SLPS-25462 (FEBEC38B).01.p2s" 0A93.bin --addr 0x1C03150

------------------------------------------------------------------------------
中文说明

PCSX2 即时存档（.p2s）内存比对工具 —— 「数据全对却坏」类问题的取证利器

.p2s 是 ZIP 容器，成员是各块内存/状态的快照（多为 zstd 压缩，ZIP method = 93）。
本工具把「运行时内存里的某份数据」与「文件里的原始数据」逐字节比对。核心判据是：

    差异是否从一个固定的**文件内偏移**一刀切开始？

若是，则说明该偏移之后的数据在内存里被别的东西覆盖了（例如字库超出了游戏为它
预留的 RAM 缓冲区），而上传/渲染只是把被污染的 RAM 原样抄走。这个判据不需要
调试器、不需要断点，是成本最低的动态取证（详见 docs/zh/08-font-capacity-and-elf-patching.md）。

依赖: 标准库；解 zstd 成员需要第三方包 zstandard（pip install zstandard）。

用法:
  python savestate_ram.py list <p2s>
        列出存档内的成员（名称 / 压缩方式 / 压缩后大小 / 原始大小）。
  python savestate_ram.py extract <p2s> <成员名> <输出文件>
        导出并解压某个成员（如 eeMemory.bin = 32 MiB 的 EE 主存）。
  python savestate_ram.py locate <p2s> <文件> [--member eeMemory.bin] [--at 0x40] [--len 64] [--max 8]
        在内存里搜索该文件的这一段字节，报告它被加载到的**基址**（= 命中地址 − --at），
        可用来确认「这份数据被加载到哪个地址」。
  python savestate_ram.py diff <p2s> <文件> --addr 0x1C03150 [--member eeMemory.bin] [--max-runs 16]
        [--from 0x8F80] [--to 0x2E9C0]
        把该文件与内存 --addr 处的副本逐字节比对，统计差异字节数与**连续差异段**，
        并指出第一段起点（关键判据）。--from/--to 可只比某个区间（例如只比位图区，
        跳过运行时会被改写成绝对地址的头部指针区）。

例:
  python savestate_ram.py list "SLPS-25462 (FEBEC38B).01.p2s"
  python savestate_ram.py extract "SLPS-25462 (FEBEC38B).01.p2s" eeMemory.bin ee_ram.bin
  python savestate_ram.py locate "SLPS-25462 (FEBEC38B).01.p2s" 0A93.bin --at 0x40 --len 32
  python savestate_ram.py diff   "SLPS-25462 (FEBEC38B).01.p2s" 0A93.bin --addr 0x1C03150
"""
# 用途：从 .p2s 即时存档里取内存快照，并与文件数据做逐字节比对（连续差异段 = 覆盖判据）。
import io
import struct
import sys
import zipfile

DEFAULT_MEMBER = 'eeMemory.bin'
ZSTD_METHOD = 93


# ------------------------------------------------------------------ 读取 ----

def member_bytes(p2s, name):
    """取出并解压 .p2s 里的某个成员。"""
    with zipfile.ZipFile(p2s) as z:
        try:
            info = z.getinfo(name)
        except KeyError:
            have = ', '.join(i.filename for i in z.infolist())
            raise SystemExit('no member %s in the savestate; available members: %s' % (name, have))
        if info.compress_type != ZSTD_METHOD:
            return z.read(info)                       # 未压缩 / 常规压缩
        header_offset, comp_size = info.header_offset, info.compress_size
    try:
        import zstandard
    except ImportError:
        raise SystemExit('member %s is zstd-compressed (ZIP method 93): run pip install zstandard first'
                         % name)
    # 自己按本地文件头算出数据起点，把压缩数据交给 zstandard（不依赖 zipfile 是否支持 zstd）
    with open(p2s, 'rb') as f:
        f.seek(header_offset)
        nlen, elen = struct.unpack_from('<HH', f.read(30), 26)
        f.seek(header_offset + 30 + nlen + elen)
        raw = f.read(comp_size)
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as r:
        return r.read()


def load_ram(p2s, member):
    ram = member_bytes(p2s, member)
    if len(ram) < 0x100:
        raise SystemExit('member %s is only %d bytes, not a memory snapshot' % (member, len(ram)))
    return ram


def parse_int(s):
    """宽容解析：允许直接给数字（默认值），也允许 '0x...' 字符串。"""
    return s if isinstance(s, int) else int(s, 0)


# 需要跟一个值的选项；ALIASES 把用户口语化的选项名映射到函数参数名
VALUE_OPTS = ('--member', '--at', '--len', '--max', '--max-runs', '--addr', '--from', '--to')
ALIASES = {'len': 'length', 'max': 'max_hits', 'from': 'start', 'to': 'end'}


def split_args(argv, value_opts=VALUE_OPTS):
    """把 argv 拆成 (位置参数, 选项字典)；选项的值不会被误当成位置参数。"""
    pos, opts = [], {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith('--'):
            key = a[2:].replace('-', '_')
            if a in value_opts:
                if i + 1 >= len(argv):
                    raise SystemExit('%s requires a value' % a)
                opts[ALIASES.get(key, key)] = argv[i + 1]
                i += 2
                continue
            opts[ALIASES.get(key, key)] = True
            i += 1
            continue
        pos.append(a)
        i += 1
    return pos, opts


# ------------------------------------------------------------------ 命令 ----

def cmd_list(p2s, *_, **__):
    with zipfile.ZipFile(p2s) as z:
        print('%-28s %-8s %14s %14s' % ('member', 'method', 'compressed', 'original size'))
        for i in z.infolist():
            meth = 'zstd' if i.compress_type == ZSTD_METHOD else ('store' if i.compress_type == 0 else
                                                                  'method%d' % i.compress_type)
            print('%-28s %-8s %14d %14d' % (i.filename, meth, i.compress_size, i.file_size))
    return 0


def cmd_extract(p2s, member, out, *_):
    data = member_bytes(p2s, member)
    with open(out, 'wb') as f:
        f.write(data)
    print('extracted %s → %s  (%d B)' % (member, out, len(data)))
    return 0


def cmd_locate(p2s, path, member=DEFAULT_MEMBER, at=0x40, length=64, max_hits=8, **_):
    at, length, max_hits = parse_int(at), parse_int(length), parse_int(max_hits)
    with open(path, 'rb') as f:
        f.seek(at)
        needle = f.read(length)
    if not needle:
        raise SystemExit('reference file %s has no data at offset 0x%X' % (path, at))
    ram = load_ram(p2s, member)
    hits, pos = [], ram.find(needle)
    while pos >= 0 and len(hits) < max_hits:
        hits.append(pos)
        pos = ram.find(needle, pos + 1)
    print('reference: %s [0x%X, 0x%X), %d bytes; %s (%d B) contains %d hit(s)'
          % (path, at, at + length, length, member, len(ram), len(hits)))
    for i, h in enumerate(hits, 1):
        print('  [%d] hit 0x%08X  ⇒ file base address = 0x%08X  (= hit − 0x%X)'
              % (i, h, h - at, at))
    if not hits:
        print('  (not found: confirm that this data really is loaded, or use a more distinctive reference slice)')
    elif len(hits) == 1:
        print('\nNext: pass that base address to the diff subcommand to see whether this memory copy was rewritten:')
        print('  python %s diff "%s" "%s" --addr 0x%08X'
              % (sys.argv[0], p2s, path, hits[0] - at))
    return 0


def cmd_diff(p2s, path, addr, member=DEFAULT_MEMBER, max_runs=16, start=0, end=None, **_):
    addr, max_runs = parse_int(addr), parse_int(max_runs)
    start = parse_int(start)
    with open(path, 'rb') as f:
        ref = f.read()
    ram = load_ram(p2s, member)
    n = len(ref)
    end = n if end is None else min(parse_int(end), n)
    start = max(0, min(start, end))
    if addr + n > len(ram):
        print('note: memory %s ends at 0x%X, the reference file would be truncated at 0x%X' % (member, len(ram), addr))
    cpy = ram[addr:addr + n]

    runs, cur, ndiff = [], None, 0
    for i in range(start, end):
        if cpy[i] != ref[i]:
            ndiff += 1
            if cur is None:
                cur = i
        elif cur is not None:
            runs.append((cur, i))
            cur = None
    if cur is not None:
        runs.append((cur, end))

    span = max(1, end - start)
    print('reference file: %s  (%d B)' % (path, n))
    print('memory copy: %s @ 0x%08X' % (member, addr))
    if start or end != n:
        print('compared range: file offset [0x%X, 0x%X)  %d B total' % (start, end, end - start))
    print('differing bytes: %d  (%.2f%%)' % (ndiff, 100.0 * ndiff / span))
    print('contiguous diff runs: %d' % len(runs))
    for i, (a, b) in enumerate(runs[:max_runs], 1):
        print('  run %-2d  file offset 0x%06X .. 0x%06X   (%d B)%s'
              % (i, a, b, b - a, '   <- first run starts here' if i == 1 else ''))
    if len(runs) > max_runs:
        print('  ...(%d run(s) total, showing the first %d)' % (len(runs), max_runs))

    if not runs:
        print('\n[IDENTICAL] this range matches completely: nothing has overwritten it.')
        return 0

    first = runs[0][0]
    if start == 0 and first < 0x40:
        print('\nnote: the first run falls in the pointer area at the start of the file (0x%X): once the'
              ' container is loaded, the game usually rewrites the "in-file offset" pointers in the'
              ' header into **runtime absolute addresses**, so a short diff here is normal.\n'
              '      Judge "was it overwritten?" by the **data area** (e.g. the bitmap region);'
              ' --from skips the header:\n'
              '        ... diff "<p2s>" "<file>" --addr 0x%08X --from 0x<data area start>'
              % (first, addr))
        data_runs = [r for r in runs if r[0] >= 0x40]
        if data_runs:
            print('      the first diff run inside the data area of this range starts at 0x%X (%d B).'
                  % (data_runs[0][0], data_runs[0][1] - data_runs[0][0]))
        else:
            print('      [OK] no diff runs in the data area within this range.')
    else:
        print('\ncriterion: the first diff run starts at file offset 0x%X (%d).' % (first, first))
        print('      if that offset is "clean" (e.g. it lands exactly on a slot/block boundary and then runs to the end),')
        print('      the data after it was most likely overwritten by something else -- see docs/en/08-font-capacity-and-elf-patching.md.')
        if len(runs) == 1 and runs[0][1] == end:
            print('      this case is "one run to the end": differences from 0x%X all the way to the file end.' % first)
    return 0


COMMANDS = {
    'list': cmd_list,
    'extract': cmd_extract,
    'locate': cmd_locate,
    'diff': cmd_diff,
}

USAGE = (__doc__ or '').strip()


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(USAGE)
        return 0
    cmd = argv[1]
    if cmd not in COMMANDS:
        raise SystemExit('unknown subcommand %s\n\n%s' % (cmd, USAGE))
    pos, opts = split_args(argv[2:])
    if not pos:
        raise SystemExit('missing required arguments\n\n%s' % USAGE)
    return COMMANDS[cmd](*pos, **opts)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main(sys.argv))
