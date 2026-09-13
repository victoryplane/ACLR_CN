# -*- coding: utf-8 -*-
"""fslzss_compress.py — fsliblzs LZSS compressor for Armored Core: Last Raven (PS2) write-back.

Compresses a byte stream into an `fsliblzs` container: a 0x2c-byte header, an LZSS stream,
an end marker and 16-byte alignment padding.

Two encoders, both writing the **same container format** (they only differ in how the
token sequence is chosen):

  mode='auto'  (default)  optimal parse (DP) — smallest output
  mode='greedy'           the historical greedy encoder, byte-for-byte compatible with
                          earlier versions of this tool

Why it matters — measured on this project's ISO over **all 2470** fsliblzs containers:

| encoder | total output | vs. the original file |
|---|---|---|
| greedy  | 389,463,280 B | 102.84 % (bigger than the original!) |
| optimal | 368,853,184 B | **97.39 %** |

The greedy encoder loses because the game's own compressor performs **optimal parsing**:
40–50 % of the matches in original streams have `len == 2`, which saves no bytes by itself
but merges two operations into one and shrinks the flag-byte envelope. Greedy matching
(`MIN_MATCH = 3`, longest match wins) cannot see that.

For the 523 model+texture records (ids 5xxxx) this is the difference between
"can be written back into its original slot" and "cannot": greedy output was 103.43 % of
the original (45/523 fitted), optimal output is 98.01 % (**523/523 fitted**).

**The optimal encoder is guaranteed never to be worse than greedy**: both are computed and
the smaller result is returned.

Measured with **this Python implementation** on 12 real containers extracted from the original
image (3,192,992 B of decompressed data): greedy 107.09% of the original files, optimal 94.54%,
round trips 12/12 byte-identical. The largest container (1.9 MB) goes from 108.9% (unusable —
does not fit its slot) to 92.7% (7.3% smaller than the game's own compression).

⚠️ IMPORTANT WARNING — read docs/en/04-write-back-and-compression.md (Chinese:
docs/zh/04-write-back-and-compression.md) before writing compressed data back into a game
image: a lossless round-trip does NOT by itself prove that the game accepts the stream.
The optimal encoder emits constructs the original decompressor must accept (`dist` in
1..0xFFF — never 0, `len` in 2..16, at least one literal byte before the end marker), and
all 2470 containers round-trip byte-for-byte; but **in-game verification is still the
reader's job** whenever the stream construction changes.

Header field 0x20: every original sample is 0x00000100 (256) and this compressor writes the
same value. The game's decompressor does not actually read that field (see
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
  python fslzss_compress.py <input> <output> [--mode auto|greedy|opt] [--chain-max N]
        Compress <input> (any bytes) into <output> as an fsliblzs container and print the
        size ratio. `--mode greedy` reproduces the historical encoder byte for byte.

Examples:
  python fslzss_compress.py 0A93_dec.bin 0A93.bin
  python fslzss_compress.py dialogue.mes dialogue.mes.lzs
  python fslzss_compress.py model.de model.lzs --mode greedy     # old behaviour

Performance: the optimal encoder is pure Python and trades time for size. Measured on real
containers from this game: 3.6–14.8 KB/s of *input* (decompressed) data — a 131 KB container takes
about 9 s, a 1.9 MB container about 9 minutes — while `--mode greedy` runs at roughly 730 KB/s, two
orders of magnitude faster. `--chain-max 128` is about 4× faster than the default 512 for roughly
+0.3% size. Records larger than 8 MB automatically fall back to greedy.

Exit code: 0 on success. Invalid usage prints this help text and exits non-zero.
Read-only with respect to <input>; only <output> is written.

------------------------------------------------------------------------------
中文说明

fsliblzs LZSS 压缩器 —— AC Last Raven (PS2) 回写用。

两种编码器，写出的**容器格式完全相同**（区别只在「怎么选 token」）：
`--mode auto`（默认，最优解析，体积最小）/ `--mode greedy`（历史贪心版，与旧版逐字节一致）。

为什么重要——本项目在 ISO 的**全部 2470 个** fsliblzs 容器上实测：

| 编码器 | 总输出 | 相对原文件 |
|---|---|---|
| 贪心 | 389,463,280 B | 102.84%（**比原文件还大**） |
| 最优解析 | 368,853,184 B | **97.39%** |

贪心之所以输，是因为游戏原厂压缩器用的是**最优解析**：原厂流里 40%~50% 的匹配
长度是 `len == 2`，这种 token 本身不省字节，但把两次操作并成一次、让 flag 分组包络变小；
贪心（`MIN_MATCH = 3` + 最长匹配优先）看不到这一点。

对 523 条「模型+贴图」（id 5xxxx）记录，这就是「能不能塞回原槽位」的分水岭：
贪心输出是原文件的 103.43%（只有 45/523 塞得下），最优解析是 98.01%（**523/523 全部塞得下**）。

**最优解析保证不会比贪心更差**：两者都算，取较小者返回。

用**本 Python 实现**从原版镜像抽出的 12 个真实容器（解压后合计 3,192,992 B）实测：
贪心 107.09%（比原文件还大）、最优解析 94.54%，往返 12/12 逐字节一致。
最大的 1.9 MB 容器最典型：从 108.9%（塞不回原槽位）变成 92.7%（**比原厂还小 7.3%**）。

⚠️ 重要警告：压缩后的数据要装回游戏时，请先读本仓 docs/zh/04-write-back-and-compression.md：
往返解压无损 ≠ 游戏内解压器一定兼容。最优解析只产生原版解压器**必然接受**的构造
（`dist` 恒在 1..0xFFF、绝不为 0；`len` 2..16；结束标记前至少留 1 个字面量字节），
且 2470 条容器全部往返逐字节一致；但**只要改变了流的构造方式，就仍需读者自己实机验证**。

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
  python fslzss_compress.py <输入文件> <输出文件> [--mode auto|greedy|opt] [--chain-max N]
  性能：最优解析是纯 Python，用时间换体积（实测 3.6~14.8 KB/s，按**解压后**数据计——
  131 KB 的容器约 9 秒、1.9 MB 的容器约 9 分钟；贪心档约 730 KB/s，快两个数量级）；
  `--chain-max 128` 比默认的 512 再快约 4 倍（体积约 +0.3%）；超过 8 MB 的记录自动回退贪心。
"""
# 用途：把任意字节流压缩为 fsliblzs 容器（LZSS，PS2 小端），仅依赖标准库。
# 两种编码器：最优解析（默认，最小体积）/ 贪心（历史行为，逐字节兼容旧版）。
import io
import struct
import sys
from array import array
from collections import defaultdict

USAGE = (__doc__ or '').strip()

MAGIC = b'fsliblzs'
HEADER_SIZE = 0x2C
WINDOW = 0x1000
MIN_MATCH = 3          # 贪心档的最小匹配长度（最优解析档允许 len=2）
MAX_LEN = 16
MAX_DIST = 0xFFF
FIELD_0x20 = 0x00000100

# 最优解析档：哈希链遍历上限与哈希表大小（纯 Python 下不做近端 256 位置线性扫描，
# 因为它的内层代价是 256 次/位置，Python 里慢到不可用；链遍历本身已经是「近 → 远」顺序，
# 每个长度首次命中即最短距离，效果等价）
#
# 默认 512 是实测定的：在一批真实原厂容器上，512 只比 4096 大 0.06%，却快约 1.8 倍；
# 128 再快约 4 倍，代价是大约 +0.30%。用 --chain-max 调。
DEFAULT_CHAIN_MAX = 512
HASH_BITS = 14
HASH_SIZE = 1 << HASH_BITS

# DP 代价单位 = 1/8 字节：字面量 1 字节 + flag 均摊 1/8；匹配 token 2 字节 + 1/8
LIT_COST = 9
MAT_COST = 17
INF = 0x3FFFFFFF

# distForLen 用 array('H')，每个 (位置, 长度) 占 2 字节；超过这个输入长度就回退贪心，
# 避免为大记录分配过大的表（n=8MB 时约 272 MB）
MAX_OPT_INPUT = 8 * 1024 * 1024


def _hash3(a, b, c):
    return (((a * 0x9E3779B1) ^ (b * 0x85EBCA77) ^ (c * 0xC2B2AE3D)) >> (32 - HASH_BITS)) & (HASH_SIZE - 1)


def _common_len(data, i, j, max_len):
    """data[i:] 与 data[j:] 的公共前缀长度（上限 max_len，调用方保证 ≥3 字节已相同）。

    用「切片相等 + 二分」在 C 层完成比较 —— 逐字节的 Python 循环在这里是瓶颈。
    """
    lo, hi = 3, max_len
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if data[i:i + mid] == data[j:j + mid]:
            lo = mid
        else:
            hi = mid - 1
    return lo


def greedy_ops(data):
    """贪心解析：3 字节前缀表 + 最长匹配（MIN_MATCH=3）。与历史版本逐字节等价。"""
    n = len(data)
    ops = []
    pos_by_key = defaultdict(list)
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
                    if dist < 1 or dist > MAX_DIST:
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
    return ops


def optimal_ops(data, chain_max=DEFAULT_CHAIN_MAX, scan_near=0):
    """最优解析（一维 DP）求出 token 序列。

    与贪心档的区别（格式不变，只改「怎么选 token」）：
      1) 匹配搜索用 3 字节哈希链，按「近 → 远」遍历，每个长度首次命中即最短距离；
      2) **允许 len == 2 的匹配**（原厂流里占 40%~50%，是最优解析的特征）；
      3) DP 在位置上松弛「字面量」与「len=2..maxLen 的全部匹配」，回溯全局最小代价。

    dist 语义与解压器严格一致：`src = max(0, outLen - 0x1000) + dist`，
    因此存 `dist = j - max(0, i - 0x1000)`（注意这不是常见的「往回退 dist」）。
    匹配绝不覆盖最后一个字节 —— 否则解压器读不到结束标记 00 00。
    """
    n = len(data)
    if n == 0:
        return []
    if n == 1:
        return [(0, data[0])]

    match_at = [0] * (n + 1)                              # (dist << 5) | maxLen；0 = 无匹配
    dist_for_len = array('H', bytes(2 * n * (MAX_LEN + 1)))
    head = [-1] * HASH_SIZE
    prev = [-1] * n

    for i in range(n):
        max_len = n - i - 1
        if max_len > MAX_LEN:
            max_len = MAX_LEN
        if max_len < 2:
            continue
        if n - i >= 3:
            h = _hash3(data[i], data[i + 1], data[i + 2])
            prev[i] = head[h]
            head[h] = i

        base = i - WINDOW if i > WINDOW else 0
        c0 = data[i]
        c1 = data[i + 1]
        maxl3 = max_len >= 3
        key3 = data[i:i + 3] if maxl3 else b''
        bd = [0] * (MAX_LEN + 1)
        filled = 0
        nm = 0

        if scan_near:                                     # 可选：近端线性扫描（默认关闭）
            j_stop = i - scan_near
            if j_stop < base:
                j_stop = base
            for j in range(i - 1, j_stop - 1, -1):
                if data[j] != c0 or data[j + 1] != c1:
                    continue
                d = j - base
                if maxl3 and data[j:j + 3] == key3:
                    l = _common_len(data, i, j, max_len)
                    need = ((1 << (l + 1)) - 1) & ~3
                    if filled & need != need:
                        for L in range(2, l + 1):
                            if bd[L] == 0:
                                bd[L] = d
                        filled |= need
                    if l > nm:
                        nm = l
                elif nm < 2 and bd[2] == 0:
                    bd[2] = d
                    nm = 2
                    filled |= 1 << 2

        j = prev[i]
        steps = 0
        while j >= 0 and j >= base:
            steps += 1
            if steps > chain_max:
                break
            if data[j] == c0 and data[j + 1] == c1 and data[j:j + 3] == key3:
                l = _common_len(data, i, j, max_len)
                d = j - base
                need = ((1 << (l + 1)) - 1) & ~3
                if filled & need != need:
                    for L in range(2, l + 1):
                        if bd[L] == 0:
                            bd[L] = d
                    filled |= need
                    full = False
                else:
                    full = True
                if l > nm:
                    nm = l
                    if nm >= max_len:
                        # 已经拿到该位置允许的最长匹配：链只会给出更远的距离，
                        # 而高度 2..max_len 全部已填，继续走没有收益。
                        break
                if full and nm >= max_len:
                    break
            j = prev[j]

        if nm >= 2 and bd[nm] > 0:
            match_at[i] = (bd[nm] << 5) | nm
            off = i * (MAX_LEN + 1)
            for L in range(2, nm + 1):
                dist_for_len[off + L] = bd[L]

    # DP：cost 单位 1/8 字节
    cost = [INF] * (n + 1)
    choice = [0] * (n + 1)
    cost[0] = 0
    for i in range(n):
        ci = cost[i]
        if ci >= INF:
            continue
        cf = ci + LIT_COST
        if cf < cost[i + 1]:
            cost[i + 1] = cf
            choice[i + 1] = 0
        mv = match_at[i]
        if mv:
            mvl = mv & 31
            if i + mvl >= n:
                mvl = n - i - 1
            if mvl >= 2:
                off = i * (MAX_LEN + 1)
                cm = ci + MAT_COST
                for L in range(2, mvl + 1):
                    dL = dist_for_len[off + L]
                    if dL == 0:
                        continue
                    t = i + L
                    if cm < cost[t]:
                        cost[t] = cm
                        choice[t] = (1 << 30) | (dL << 10) | L

    # 回溯（按 op 边界反转，不能按字节反转）
    back_vals = []
    back_lens = []
    p = n
    guard = 0
    while p > 0:
        guard += 1
        if guard > n + 4:
            raise RuntimeError('LZSS 回溯异常：死循环')
        c = choice[p]
        if c == 0:
            back_vals.append(data[p - 1])
            back_lens.append(1)
            p -= 1
        else:
            length = c & 0x3FF
            dist = (c >> 10) & 0xFFFFF
            if length < 2 or length > MAX_LEN or dist < 1 or dist > MAX_DIST:
                raise RuntimeError('LZSS 回溯异常：p=%d len=%d dist=%d' % (p, length, dist))
            back_vals.append((dist, length))
            back_lens.append(length)
            p -= length

    ops = []
    for k in range(len(back_lens) - 1, -1, -1):
        if back_lens[k] == 1:
            ops.append((0, back_vals[k]))
        else:
            dist, length = back_vals[k]
            ops.append((1, dist, length))
    return ops


def assemble(ops, raw_size):
    """把 ops 组装成完整容器：每 8 个操作一组 + flag 字节（LSB 优先）+ 结束标记 + 16 字节对齐。"""
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
            flag |= (1 << n_grp)          # 结束标记作为本组的下一个 token
            body += b'\x00\x00'
        stream.append(flag)
        stream += body
        k += 8
        if is_last and n_grp == 8:
            stream += b'\x01\x00\x00'     # 操作数正好 8 的倍数：结束标记单独一组

    # 16 字节对齐：原版全部 fsliblzs 容器的 total size(0x10) 都是 16 的倍数；
    # 不补齐会让游戏的 DMA/装载器读不满整 quadword → 尾部数据错 → 任务无限加载。
    total = HEADER_SIZE + len(stream)
    pad = (16 - total % 16) % 16
    if pad:
        stream += b'\x00' * pad
        total += pad

    hdr = bytearray(HEADER_SIZE)
    hdr[0:8] = MAGIC
    struct.pack_into('<I', hdr, 0x10, total)
    struct.pack_into('<I', hdr, 0x14, 1)
    struct.pack_into('<I', hdr, 0x20, FIELD_0x20)
    struct.pack_into('>I', hdr, 0x24, raw_size)
    hdr[0x2B] = 0
    return bytes(hdr) + bytes(stream)


def fslzss_compress(data, mode='auto', chain_max=DEFAULT_CHAIN_MAX, scan_near=0, max_size=None):
    """把 data 压缩成完整 fsliblzs 容器字节。

    mode='auto'（默认）：算贪心 + 最优解析两份，返回**较小**的那个（因此绝不会比旧版更大）；
                         给了 max_size 时先用贪心试，放得下就直接返回（省时间）。
    mode='greedy'       ：只算贪心（与历史版本逐字节一致）。
    mode='opt'          ：只算最优解析（仍与贪心取较小者，保证不退化）。
    """
    if mode not in ('auto', 'opt', 'greedy'):
        raise ValueError('mode 必须是 auto / opt / greedy')

    if mode == 'greedy':
        return assemble(greedy_ops(data), len(data))

    greedy_out = None
    if mode == 'auto' or len(data) > MAX_OPT_INPUT:
        greedy_out = assemble(greedy_ops(data), len(data))
        if max_size is not None and len(greedy_out) <= max_size:
            return greedy_out                    # 放得下就不付慢速代价
    if len(data) > MAX_OPT_INPUT:
        # 记录太大，distForLen 表会占几百 MB：退回贪心（并如实告知调用方）
        return greedy_out

    opt_out = assemble(optimal_ops(data, chain_max=chain_max, scan_near=scan_near), len(data))
    if greedy_out is None:
        greedy_out = assemble(greedy_ops(data), len(data))
    return opt_out if len(opt_out) < len(greedy_out) else greedy_out


def main():
    argv = sys.argv[1:]
    if '-h' in argv or '--help' in argv:
        print(USAGE)
        return

    opts = {'mode': 'auto', 'chain_max': DEFAULT_CHAIN_MAX}
    pos = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--mode' and i + 1 < len(argv):
            opts['mode'] = argv[i + 1]
            i += 2
            continue
        if a == '--chain-max' and i + 1 < len(argv):
            opts['chain_max'] = int(argv[i + 1], 0)
            i += 2
            continue
        if a.startswith('--'):
            print(USAGE)
            sys.exit(1)
        pos.append(a)
        i += 1

    if len(pos) < 2:
        print(USAGE)
        sys.exit(1)

    src, dst = pos[0], pos[1]
    data = io.open(src, 'rb').read()
    if opts['mode'] == 'opt':
        opts['mode'] = 'opt'
    out = fslzss_compress(data, mode=opts['mode'], chain_max=opts['chain_max'])
    io.open(dst, 'wb').write(out)
    print('compressed %d -> %d B (%.1f%%, mode=%s) -> %s'
          % (len(data), len(out), len(out) * 100 / max(1, len(data)), opts['mode'], dst))


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    main()
