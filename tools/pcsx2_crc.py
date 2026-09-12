#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCSX2 game CRC tool — essential when a localization patch edits the main executable.

The emulator derives a 32-bit CRC from the main ELF at boot and uses it as the file-name
suffix of per-game settings and built-in patches:

    gamesettings\\<serial>_<CRC>.ini     per-game settings
    patches\\<serial>_<CRC>.pnach        built-in patches (the patch database lives in
                                         <emulator>/resources/patches.zip)

**Change one byte of the ELF and the CRC changes** — so both kinds of file stop matching, and
the user reports "the patches I could tick before are gone from the list".
(GameDB is keyed by serial and is unaffected.)

Algorithm (verified against the values the emulator itself displays; emulator side:
`pcsx2/Elfheader.cpp`, `GetCRC()`):

    CRC = every 32-bit little-endian word of the whole ELF, XOR-ed together

If your ELF length is not a multiple of 4 the tail handling may differ: trust the value the
emulator shows, and use this tool to PREDICT what it will become after a patch.

Usage:
  python pcsx2_crc.py <ISO or ELF> [more...]
        Print the CRC plus ELF size / md5. For an ISO, the main ELF is located through the
        ISO9660 directory tree automatically.
  python pcsx2_crc.py <ISO> --extract-elf <output path>
        Extract the main ELF from the image (keep a copy of the original before patching it).
  python pcsx2_crc.py <ISO> --install --data <PCSX2 data dir> --old-crc <old CRC>
        [--prog <emulator install dir>] [--serial SLPS-25462]
        Compute the new CRC and copy the old CRC's per-game settings / built-in patch to the
        new name. The pnach source is, in order of preference, the old-CRC file already present
        in the data directory, then the matching entry of <emulator>/resources/patches.zip.

Examples:
  python pcsx2_crc.py ACLR.iso
  python pcsx2_crc.py ACLR.iso --extract-elf SLPS_254.62.orig
  python pcsx2_crc.py ACLR.iso --install --data "%USERPROFILE%\\Documents\\PCSX2" \\
         --prog "C:\\Program Files\\PCSX2" --old-crc FEBE1992

------------------------------------------------------------------------------
中文说明

PCSX2 game CRC 工具 —— 改过主程序 ELF 的汉化镜像必备

模拟器启动时会为主程序 ELF 算一个 32 位 CRC，并把它作为 per-game 配置与内建补丁的
文件名后缀：

    gamesettings\\<序列号>_<CRC>.ini        per-game 设置
    patches\\<序列号>_<CRC>.pnach           内建补丁（补丁库在模拟器安装目录的 resources\\patches.zip）

**只要 ELF 的字节变了，CRC 就变** ⇒ 上面两类文件全部对不上，用户侧看到的现象是
「以前能勾选的补丁，现在列表是空的」。（GameDB 按序列号索引，不受影响。）

算法（本项目实测与模拟器显示值逐一对齐；模拟器侧见 pcsx2/Elfheader.cpp 的 GetCRC()）:
    CRC = 整个 ELF 文件的 32 位小端字，逐字 XOR

用法:
  python pcsx2_crc.py <ISO 或 ELF> [更多...]
        算 CRC，并打印 ELF 大小 / md5。ISO 会自动在 ISO9660 目录树里定位主程序 ELF。
  python pcsx2_crc.py <ISO> --extract-elf <输出路径>
        把镜像里的主程序 ELF 提取出来（改 ELF 之前先留一份原件）。
  python pcsx2_crc.py <ISO> --install --data <PCSX2 数据目录> --old-crc <旧CRC>
        [--prog <模拟器安装目录>] [--serial SLPS-25462]
        算出新 CRC，并把旧 CRC 的 per-game 设置 / 内建补丁复制成新 CRC 的名字。
        pnach 的来源优先取数据目录里已有的旧 CRC 文件，其次取
        <模拟器安装目录>/resources/patches.zip 里属于该序列号的条目。

例:
  python pcsx2_crc.py ACLR.iso
  python pcsx2_crc.py ACLR.iso --extract-elf SLPS_254.62.orig
  python pcsx2_crc.py ACLR.iso --install --data "%USERPROFILE%\\Documents\\PCSX2" \
         --prog "C:\\Program Files\\PCSX2" --old-crc FEBE1992
"""
# 用途：算/预测 PCSX2 的 game CRC，并在改过 ELF 后修复 per-game 设置与补丁的命名。
import hashlib
import io
import os
import re
import shutil
import struct
import sys
import zipfile

SECTOR = 2048
SERIAL_RE = re.compile(r'^([A-Z]{4})_(\d{3})\.(\d{2})$')


# ---------------------------------------------------------------- ISO9660 ----

def iso_list_files(fp):
    """遍历 ISO9660 目录树，返回 [(名字(去 ;1), lba, size), ...]。"""
    def rd(lba, n=1):
        fp.seek(lba * SECTOR)
        return fp.read(SECTOR * n)

    pvd = rd(16)
    if pvd[1:6] != b'CD001':
        raise SystemExit('not an ISO9660 image: no CD001 magic at LBA 16 (if this is a bare ELF, pass the ELF path directly)')
    root = pvd[156:156 + 34]
    root_lba = struct.unpack_from('<I', root, 2)[0]
    root_size = struct.unpack_from('<I', root, 10)[0]

    out = []

    def walk(lba, size, depth=0):
        data = rd(lba, (size + SECTOR - 1) // SECTOR)
        off = 0
        while off < size:
            ln = data[off]
            if ln == 0:                      # 扇区剩余部分全是 0：跳到下一扇区
                off = ((off // SECTOR) + 1) * SECTOR
                continue
            rec = data[off:off + ln]
            elba = struct.unpack_from('<I', rec, 2)[0]
            esize = struct.unpack_from('<I', rec, 10)[0]
            flags = rec[25]
            nlen = rec[32]
            nm = rec[33:33 + nlen].decode('latin1')
            if nm in ('\x00', '\x01'):       # '.' / '..'
                pass
            elif flags & 0x02:
                if depth < 4:
                    walk(elba, esize, depth + 1)
            else:
                out.append((nm.split(';')[0], elba, esize))
            off += ln

    walk(root_lba, root_size)
    return out


def find_main_elf(fp):
    """在镜像里找主程序 ELF（文件名形如 SLPS_254.62），返回 (名字, lba, size)。"""
    cands = [x for x in iso_list_files(fp) if SERIAL_RE.match(x[0].upper())]
    if not cands:
        raise SystemExit('no main ELF named like XXXX_NNN.NN found in the image;'
                         ' specify it with --elf, or pass the ELF file path directly')
    cands.sort(key=lambda x: x[2], reverse=True)      # 主程序一般最大
    return cands[0]


def serial_of(elf_name):
    """SLPS_254.62 → SLPS-25462"""
    m = SERIAL_RE.match(elf_name.upper())
    return '%s-%s%s' % (m.group(1), m.group(2), m.group(3)) if m else None


# -------------------------------------------------------------------- CRC ----

def elf_crc(data):
    """PCSX2 GetCRC()：对整个 ELF 的 32 位小端字逐字 XOR（尾部不足 4 字节忽略）。"""
    n = len(data) // 4
    crc = 0
    for i in range(n):
        crc ^= struct.unpack_from('<I', data, i * 4)[0]
    return crc & 0xFFFFFFFF


# ---------------------------------------------------------------- install ----

def install_configs(data_dir, prog_dir, serial, old_crc, new_crc):
    """把旧 CRC 的 per-game 设置 / 内建补丁复制成新 CRC 的名字。"""
    new_crc = new_crc.upper()
    old_crc = old_crc.upper()
    gs_dir = os.path.join(data_dir, 'gamesettings')
    pa_dir = os.path.join(data_dir, 'patches')
    os.makedirs(pa_dir, exist_ok=True)

    done = []

    # 1) per-game 设置
    src_ini = os.path.join(gs_dir, '%s_%s.ini' % (serial, old_crc))
    dst_ini = os.path.join(gs_dir, '%s_%s.ini' % (serial, new_crc))
    if os.path.exists(src_ini):
        if os.path.exists(dst_ini):
            print('  already exists, skipping: %s' % os.path.basename(dst_ini))
        else:
            shutil.copyfile(src_ini, dst_ini)
            print('  installed per-game settings: %s' % os.path.basename(dst_ini))
        done.append(dst_ini)
    else:
        print('  ⚠ old settings not found: %s (ignore this if you do not use per-game settings)' % src_ini)

    # 2) 内建补丁：优先数据目录里已安装的旧 CRC 文件，其次模拟器自带 patches.zip
    dst_pnach = os.path.join(pa_dir, '%s_%s.pnach' % (serial, new_crc))
    src_pnach = os.path.join(pa_dir, '%s_%s.pnach' % (serial, old_crc))
    blob, where = None, None
    if os.path.exists(src_pnach):
        with open(src_pnach, 'rb') as f:
            blob, where = f.read(), src_pnach
    elif prog_dir:
        pz = os.path.join(prog_dir, 'resources', 'patches.zip')
        if os.path.exists(pz):
            with open(pz, 'rb') as f:
                zf = zipfile.ZipFile(io.BytesIO(f.read()))
            names = [n for n in zf.namelist() if serial in n]
            if names:
                blob, where = zf.read(names[0]), '%s :: %s' % (pz, names[0])
    if blob is not None:
        with open(dst_pnach, 'wb') as g:
            g.write(blob)
        print('  installed built-in patch: %s  (%d B, source %s)' % (os.path.basename(dst_pnach), len(blob), where))
        done.append(dst_pnach)
    else:
        print('  ⚠ no pnach to copy was found (the patch database path can be given with --prog;'
              ' ignore this if this game never had patches)')

    if done:
        print('\nhint: when shipping to testers, package the files above (named after the CRC of their'
              ' own image) together with the image.')
        print('      the CRC depends only on the ELF: if you later rebuild only AC.BIN/the font and never'
              ' touch the ELF again, the CRC stays the same and these settings remain valid.')


# ------------------------------------------------------------------- main ----

USAGE = (__doc__ or '').strip()

# 需要跟一个值的选项（其余按布尔开关处理）
VALUE_OPTS = ('--extract-elf', '--data', '--prog', '--old-crc', '--serial')


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
                opts[key] = argv[i + 1]
                i += 2
                continue
            opts[key] = True
            i += 1
            continue
        pos.append(a)
        i += 1
    return pos, opts


def main(argv):
    if len(argv) < 2 or '--help' in argv or '-h' in argv:
        print(USAGE)
        return 0
    args, opts = split_args(argv[1:])
    if not args:
        print(USAGE)
        return 0

    extract = opts.get('extract_elf')
    install = bool(opts.get('install'))
    data_dir = opts.get('data')
    prog_dir = opts.get('prog')
    old_crc = opts.get('old_crc')
    serial_override = opts.get('serial')

    results = []
    for path in args:
        base = os.path.basename(path)
        with open(path, 'rb') as f:
            head = f.read(4)
            f.seek(0)
            if head == b'\x7fELF':
                elf, elf_name, src = f.read(), base, '(ELF given directly)'
            else:
                elf_name, lba, size = find_main_elf(f)
                f.seek(lba * SECTOR)
                elf = f.read(size)
                src = 'LBA %d' % lba
        if len(elf) < 0x34 or elf[:4] != b'\x7fELF':
            raise SystemExit('the main executable in %s is not an ELF?' % base)
        crc = elf_crc(elf)
        print('%-44s ELF %-14s %s  %d B  md5 %s  CRC=%08X'
              % (base, elf_name, src, len(elf), hashlib.md5(elf).hexdigest(), crc))
        if len(elf) % 4:
            print('   note: the ELF length is not a multiple of 4; this tool ignores the tail bytes --'
                  ' trust the value the emulator displays')
        serial = serial_override or serial_of(elf_name)
        if serial:
            print('   serial %s ⇒ config file names %s_%08X.ini / %s_%08X.pnach'
                  % (serial, serial, crc, serial, crc))
        results.append((path, elf, elf_name, crc, serial))
        if extract:
            with open(extract, 'wb') as g:
                g.write(elf)
            print('   extracted ELF → %s' % extract)

    if install:
        if not data_dir:
            raise SystemExit('--install requires --data <PCSX2 data dir>')
        if not old_crc:
            raise SystemExit('--install requires --old-crc <old CRC> (e.g. FEBE1992)')
        for path, elf, elf_name, crc, serial in results:
            if not serial:
                raise SystemExit('cannot infer the serial from %s, specify it with --serial' % elf_name)
            print('\ninstalling configs for CRC %08X:' % crc)
            install_configs(data_dir, prog_dir, serial, old_crc, '%08X' % crc)
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main(sys.argv))
