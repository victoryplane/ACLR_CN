#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
elf_addr.py — solid ground for the job of "editing constants inside a game executable".

Localization work often has to change **compile-time constants inside the main ELF** — the
classic case being "move a data block elsewhere, so both its base address and its end address
constant have to change" (see docs/en/08-font-capacity-and-elf-patching.md). This tool does three
things:

  1. VA <-> file offset mapping: `file offset = VA - (p_vaddr - p_offset)` for the LOAD segment
     containing that VA. Do not use a hand-rolled approximation — this project once shipped a
     script that was uniformly off by 0x100 and concluded nonsense from the garbage it read.
  2. Find every reference to a 32-bit constant. On MIPS such a constant is built from
     `lui` + `addiu`/`ori`; the tool pairs the two instructions (checking that the register
     matches) and prints the file offset and encoded bytes of each.
  3. Generate a patch that turns constant A into constant B, computing exactly which bytes must
     change. It **only ever writes a copy** (--out is mandatory) and automatically also patches
     the paired `addiu`/`ori` when the new constant's low 16 bits differ.

Usage:
  python elf_addr.py info <ELF>
        Print the ELF header, the program headers (each LOAD segment's offset/vaddr/size)
        and the VA<->offset delta per segment.
  python elf_addr.py map <ELF> <address|0x...> [--rev]
        VA -> file offset; --rev maps a file offset back to a VA.
  python elf_addr.py find-const <ELF> <constant> [--window 12]
        List every lui (+addiu/ori) site that references the constant.
  python elf_addr.py patch <ELF> <old constant> <new constant> --out <output ELF> [--window 12]
        Write a patched copy (never in place) and print the byte-level change list.

Examples:
  python elf_addr.py info SLPS_254.62
  python elf_addr.py find-const SLPS_254.62 0x1C03150
  python elf_addr.py patch SLPS_254.62 0x1C03150 0x1D73150 --out SLPS_254.62.patched

------------------------------------------------------------------------------
中文说明

ELF32 / MIPS 常量引用定位与补丁工具 —— 给「改游戏常量」这件事提供可靠的地基

汉化时常需要改主程序 ELF 里的**编译期常量**（典型：把某个数据块搬到别处，
于是「数据基址」和「数据末尾」两个常量都要改，见 docs/zh/08-font-capacity-and-elf-patching.md）。
本工具做三件事：

  1. VA ↔ 文件偏移的映射：`文件偏移 = VA − (p_vaddr − p_offset)`（对包含该 VA 的 LOAD 段）。
     注意别用「按程序头自己拼」的近似写法 —— 本项目踩过整体差 0x100 的坑。
  2. 找全某个 32 位常量的**所有引用点**：MIPS 里 32 位常量由 `lui` + `addiu`/`ori` 拼出，
     工具会成对匹配（含寄存器一致性检查），输出每条指令的文件偏移与编码字节。
  3. 生成补丁：把常量 A 改成常量 B，逐点算出该改哪几个字节；
     **默认只写副本**（必须给 --out），并在新旧常量的低 16 位不同时自动连 `addiu`/`ori` 一起改。

用法:
  python elf_addr.py info <ELF>
        打印 ELF 头、程序头（各 LOAD 段的 offset/vaddr/size）与每段的 VA↔偏移增量。
  python elf_addr.py map <ELF> <地址|0x...> [--rev]
        VA → 文件偏移；--rev 则反向（文件偏移 → VA）。
  python elf_addr.py find-const <ELF> <常量> [--window 12]
        找出引用该常量的所有 lui(+addiu/ori) 位置。
  python elf_addr.py patch <ELF> <旧常量> <新常量> --out <输出ELF> [--window 12]
        生成补丁后的副本（绝不原地修改），并逐字节打印改动清单。

例:
  python elf_addr.py info SLPS_254.62
  python elf_addr.py find-const SLPS_254.62 0x1C03150
  python elf_addr.py patch SLPS_254.62 0x1C03150 0x1D73150 --out SLPS_254.62.patched
"""
# 用途：ELF32/MIPS 的 VA↔偏移映射、lui/addiu 常量引用点定位、常量搬迁补丁生成（只写副本）。
import struct
import sys

PT_LOAD = 1
OP_LUI, OP_ADDIU, OP_ORI = 0x0F, 0x09, 0x0D
REG_NAMES = ['zero', 'at', 'v0', 'v1', 'a0', 'a1', 'a2', 'a3',
             't0', 't1', 't2', 't3', 't4', 't5', 't6', 't7',
             's0', 's1', 's2', 's3', 's4', 's5', 's6', 's7',
             't8', 't9', 'k0', 'k1', 'gp', 'sp', 'fp', 'ra']


def reg(i):
    return '$' + REG_NAMES[i & 0x1F]


def sext16(v):
    return v - 0x10000 if v & 0x8000 else v


def parse_int(s):
    """宽容解析：允许直接给数字（默认值），也允许 '0x...' 字符串。"""
    return s if isinstance(s, int) else int(s, 0)


# 需要跟一个值的选项（其余按布尔开关处理）
VALUE_OPTS = ('--window', '--out')


def split_args(argv, value_opts=VALUE_OPTS):
    """把 argv 拆成 (位置参数, 选项字典)。

    关键：选项的值不会被误当成位置参数（这个坑本项目在批量脚本里踩过）。
    """
    pos, opts = [], {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith('--'):
            key = a[2:].replace('-', '_')
            if a in value_opts:
                if i + 1 >= len(argv):
                    raise SystemExit('%s requires a value' % a)
                opts[key] = argv[i + 1]
                i += 2
                continue
            opts[key] = True
            i += 1
            continue
        pos.append(a)
        i += 1
    return pos, opts


# ------------------------------------------------------------------- ELF ----

def parse_elf(data):
    if data[:4] != b'\x7fELF':
        raise SystemExit('not an ELF file')
    if data[4] != 1 or data[5] != 1:
        raise SystemExit('only 32-bit little-endian ELF is supported (ELFCLASS32 + ELFDATA2LSB)')
    e_machine, = struct.unpack_from('<H', data, 0x12)
    e_phoff, = struct.unpack_from('<I', data, 0x1C)
    e_phentsize, e_phnum = struct.unpack_from('<HH', data, 0x2A)
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
            struct.unpack_from('<8I', data, off)
        segs.append(dict(type=p_type, offset=p_offset, vaddr=p_vaddr, paddr=p_paddr,
                         filesz=p_filesz, memsz=p_memsz, flags=p_flags, align=p_align))
    return dict(machine=e_machine, entry=struct.unpack_from('<I', data, 0x18)[0],
                segs=segs, size=len(data))


def load_segments(elf):
    return [s for s in elf['segs'] if s['type'] == PT_LOAD]


def va_to_off(elf, va):
    for s in load_segments(elf):
        if s['vaddr'] <= va < s['vaddr'] + s['filesz']:
            return va - s['vaddr'] + s['offset'], s
    return None, None


def off_to_va(elf, off):
    for s in load_segments(elf):
        if s['offset'] <= off < s['offset'] + s['filesz']:
            return off - s['offset'] + s['vaddr'], s
    return None, None


# ------------------------------------------------------ 常量引用点定位 ----

def find_const(data, target, window=12):
    """找出引用 32 位常量 target 的所有位置。

    返回 [dict(hi_off, lo_off, kind, rt, hi_imm, lo_imm, bytes...)]，
    kind = 'pair'（lui+addiu/ori）或 'lui'（只有 lui，低 16 位为 0）。
    """
    target &= 0xFFFFFFFF
    n = len(data) // 4
    hits = []
    for i in range(n):
        off = i * 4
        w = struct.unpack_from('<I', data, off)[0]
        if (w >> 26) != OP_LUI:
            continue
        rt = (w >> 16) & 0x1F
        hi = w & 0xFFFF
        if (hi << 16) == target:
            hits.append(dict(hi_off=off, lo_off=None, kind='lui', rt=rt,
                             hi_imm=hi, lo_imm=None, lo_word=None))
            continue
        for j in range(1, window + 1):
            if i + j >= n:
                break
            lo_off = (i + j) * 4
            lw = struct.unpack_from('<I', data, lo_off)[0]
            op = lw >> 26
            if op not in (OP_ADDIU, OP_ORI):
                continue
            rs = (lw >> 21) & 0x1F
            lrt = (lw >> 16) & 0x1F
            if rs != rt or lrt != rt:
                continue
            lo = lw & 0xFFFF
            value = ((hi << 16) + (sext16(lo) if op == OP_ADDIU else lo)) & 0xFFFFFFFF
            if value == target:
                hits.append(dict(hi_off=off, lo_off=lo_off,
                                 kind='addiu' if op == OP_ADDIU else 'ori',
                                 rt=rt, hi_imm=hi, lo_imm=lo, lo_word=lw,
                                 gap=j))
                break
    return hits


def encode_const_halves(target, kind):
    """按指令语义把常量拆成 lui 的 16 位 + addiu/ori 的 16 位。"""
    target &= 0xFFFFFFFF
    lo = target & 0xFFFF
    if kind == 'ori':
        hi = (target >> 16) & 0xFFFF
    else:                                   # addiu 的立即数是符号扩展的
        hi = ((target + 0x8000) & 0xFFFFFFFF) >> 16
        hi &= 0xFFFF
        lo = target & 0xFFFF
    return hi, lo


def describe_hi(off, w):
    rt = (w >> 16) & 0x1F
    return 'lui   %-4s 0x%X' % (reg(rt), w & 0xFFFF)


def describe_lo(off, w):
    op = w >> 26
    rs, rt, imm = (w >> 21) & 0x1F, (w >> 16) & 0x1F, w & 0xFFFF
    name = 'addiu' if op == OP_ADDIU else 'ori  '
    return '%s %-4s %-4s 0x%04X (= %d)' % (name, reg(rt), reg(rs), imm, sext16(imm))


def hexbytes(data, off, n=4):
    return ' '.join('%02X' % b for b in data[off:off + n])


# ------------------------------------------------------------------ 命令 ----

def cmd_info(path, *_):
    with open(path, 'rb') as f:
        data = f.read()
    elf = parse_elf(data)
    print('%s  %d B  e_machine=%d  entry=0x%08X' % (path, elf['size'], elf['machine'], elf['entry']))
    print('\n%-8s %-10s %-10s %-10s %-10s %-10s' %
          ('p_type', 'p_offset', 'p_vaddr', 'p_filesz', 'p_memsz', 'VA-off'))
    for s in elf['segs']:
        print('%-8d 0x%08X 0x%08X 0x%08X 0x%08X 0x%X%s'
              % (s['type'], s['offset'], s['vaddr'], s['filesz'], s['memsz'],
                 (s['vaddr'] - s['offset']) & 0xFFFFFFFF,
                 '   <- LOAD' if s['type'] == PT_LOAD else ''))

    withdata = [s for s in load_segments(elf) if s['filesz']]
    nodata = [s for s in load_segments(elf) if not s['filesz']]
    print('\nVA <-> file offset (only segments with p_filesz > 0 really have bytes in the file):')
    for s in withdata:
        print('  seg 0x%08X..0x%08X : file offset = VA − 0x%X'
              % (s['vaddr'], (s['vaddr'] + s['filesz']) & 0xFFFFFFFF,
                 (s['vaddr'] - s['offset']) & 0xFFFFFFFF))
    deltas = {(s['vaddr'] - s['offset']) & 0xFFFFFFFF for s in withdata}
    if len(deltas) == 1:
        print('  => uniform across all segments: **file offset = VA − 0x%X**' % deltas.pop())
    elif len(deltas) > 1:
        print('  note: the delta differs per segment -- pick the formula by "which segment this address falls in", do not use one approximation for the whole file')
    for s in nodata:
        print('  runtime-only mapping (p_filesz=0, no bytes in the file): 0x%08X..0x%08X  memsz 0x%X'
              % (s['vaddr'], (s['vaddr'] + s['memsz']) & 0xFFFFFFFF, s['memsz']))
    print('\nhint: RAM outside the data segments (e.g. the target address the game loads data to at runtime) has no bytes in the file;')
    print('      to tell whether a VA is "file data / runtime-only mapping / hole outside the segments", use the map subcommand.')
    return 0


def cmd_map(path, value, rev=False, **_):
    with open(path, 'rb') as f:
        data = f.read()
    elf = parse_elf(data)
    v = parse_int(value)
    if rev:
        va, s = off_to_va(elf, v)
        if va is None:
            raise SystemExit('file offset 0x%X is not inside any LOAD segment that carries data' % v)
        print('file offset 0x%X → VA 0x%08X  (segment 0x%08X..0x%08X)'
              % (v, va, s['vaddr'], s['vaddr'] + s['filesz']))
    else:
        off, s = va_to_off(elf, v)
        if off is not None:
            print('VA 0x%08X → file offset 0x%X  (segment 0x%08X..0x%08X)'
                  % (v, off, s['vaddr'], (s['vaddr'] + s['filesz']) & 0xFFFFFFFF))
            print('  instruction bytes at that offset: %s' % hexbytes(data, off))
        else:
            inbss = [s for s in load_segments(elf)
                     if s['vaddr'] <= v < s['vaddr'] + s['memsz']]
            if inbss:
                s2 = inbss[0]
                print('VA 0x%08X has no bytes in the file: it falls inside the'
                      ' **runtime-only mapping** (p_filesz=0) of segment 0x%08X..0x%08X.'
                      % (v, s2['vaddr'], (s2['vaddr'] + s2['memsz']) & 0xFFFFFFFF))
                print('  such addresses are RAM that exists only at runtime (BSS / static area used by the'
                      ' engine) -- to decide whether data can be moved here, see docs/en/08-font-capacity-and-elf-patching.md.')
            else:
                top = max([(s['vaddr'] + s['memsz']) & 0xFFFFFFFF for s in load_segments(elf)] or [0])
                if v >= top:
                    print('VA 0x%08X is **above** the top of the program image 0x%08X (outside every LOAD'
                          ' segment): the file has no bytes for it, this is a RAM hole outside the segments.' % (v, top))
                    print('  such addresses are often used as a "new home for moved data", but you **must'
                          ' verify empirically that nothing uses it** (all zero in a savestate + a full'
                          ' playthrough), do not just look at the zero bytes.')
                else:
                    print('VA 0x%08X is not inside any LOAD segment (including p_memsz ranges):'
                          ' this is a RAM hole between segments and the file has no bytes for it.' % v)
    return 0


def cmd_find_const(path, target, window=12, **_):
    window = parse_int(window)
    with open(path, 'rb') as f:
        data = f.read()
    t = parse_int(target)
    hits = find_const(data, t, window)
    print('found %d reference(s) to 0x%08X in %s:' % (len(hits), t, path))
    for k, h in enumerate(hits, 1):
        w = struct.unpack_from('<I', data, h['hi_off'])[0]
        print('  [%d] lui   file offset 0x%06X  %-18s bytes %s'
              % (k, h['hi_off'], describe_hi(h['hi_off'], w), hexbytes(data, h['hi_off'])))
        if h['lo_off'] is not None:
            print('      low half  file offset 0x%06X  %-18s bytes %s  (%d instruction(s) apart)'
                  % (h['lo_off'], describe_lo(h['lo_off'], h['lo_word']),
                     hexbytes(data, h['lo_off']), h['gap']))
    if not hits:
        print('  (nothing: check the constant value, check that this is the main ELF, or raise --window)')
    else:
        print('\nhint: if a lui merely yields the value (low 16 bits zero) it has no addiu/ori partner;'
              ' this tool lists it separately as kind=lui.')
    return 0


def cmd_patch(path, old, new, out=None, window=12, **_):
    if not out:
        raise SystemExit('for safety --out <output ELF> is required (this tool never patches in place and never touches the source file)')
    window = parse_int(window)
    with open(path, 'rb') as f:
        data = bytearray(f.read())
    oldv, newv = parse_int(old), parse_int(new)
    hits = find_const(bytes(data), oldv, window)
    if not hits:
        raise SystemExit('no reference to 0x%08X found, nothing was modified' % oldv)

    changes = []
    for h in hits:
        hi, lo = encode_const_halves(newv, h['kind'] if h['kind'] != 'lui' else 'addiu')
        w = struct.unpack_from('<I', data, h['hi_off'])[0]
        new_hi_imm = hi
        if (w & 0xFFFF) != new_hi_imm:
            nw = (w & 0xFFFF0000) | new_hi_imm
            changes.append((h['hi_off'], w, nw))
        if h['lo_off'] is not None:
            lw = struct.unpack_from('<I', data, h['lo_off'])[0]
            if (lw & 0xFFFF) != lo:
                nw = (lw & 0xFFFF0000) | lo
                changes.append((h['lo_off'], lw, nw))
        elif (oldv & 0xFFFF) != (newv & 0xFFFF):
            print('  ⚠ offset 0x%06X: lui only, but the low 16 bits of the old and new constants differ'
                  ' (0x%04X → 0x%04X), so it cannot be patched completely here -- please inspect this'
                  ' instruction context by hand' % (h['hi_off'], oldv & 0xFFFF, newv & 0xFFFF))

    for off, ow, nw in changes:
        data[off:off + 4] = struct.pack('<I', nw)

    print('constant 0x%08X → 0x%08X : %d reference(s), %d byte(s) changed\n'
          % (oldv, newv, len(hits), len(changes)))
    print('%-10s %-14s %-14s %s' % ('offset', 'old bytes', 'new bytes', 'new instruction'))
    for off, ow, nw in changes:
        print('0x%06X   %-14s %-14s %s'
              % (off, hexbytes(struct.pack('<I', ow), 0), hexbytes(struct.pack('<I', nw), 0),
                 describe_hi(off, nw) if (nw >> 26) == OP_LUI else describe_lo(off, nw)))

    with open(out, 'wb') as g:
        g.write(bytes(data))
    print('\nwrote the patched copy: %s  (source file untouched)' % out)
    print('next: after putting the copy back into the image, remember to compute the new game CRC and'
          ' sync the per-game settings/patches -- see tools/pcsx2_crc.py.')
    return 0


COMMANDS = {
    'info': cmd_info,
    'map': cmd_map,
    'find-const': cmd_find_const,
    'patch': cmd_patch,
}

USAGE = (__doc__ or '').strip()


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(USAGE)
        return 0
    cmd = argv[1].replace('_', '-')
    if cmd not in COMMANDS:
        raise SystemExit('unknown subcommand %s\n\n%s' % (argv[1], USAGE))
    pos, opts = split_args(argv[2:])
    return COMMANDS[cmd](*pos, **opts)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main(sys.argv))
