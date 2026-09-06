# -*- coding: utf-8 -*-
"""PSS 重封装 v3：严格复刻原版结构 —— 固定 16KB pack + BE padding 填充 + seq_end 塞入最后视频 PES。

与原版结构一致的关键点：
1. 每个 pack 固定 16384 字节（14B pack 头 + PES + 0xBE padding 流填满）。
2. pack 内 PES 不跨 pack 边界。
3. sequence_end(00 00 01 B7) 追加在最后一个视频 PES 的 payload 内（非独立 PES）。
4. 收尾顺序（重要，见 docs/06-PSS视频.md 坑2）：最后一个内容 pack 之后**立即**写
   00 00 01 B9（游戏 demuxer 的结束信号）；若调用方要求等长（SIZE 大于内容），
   剩余空间用「纯 BE padding pack」补在 **B9 之后**，绝不把大段 padding 放在 B9 前面
   （否则播完还要读整段 padding 才碰到 B9，表现为黑屏十几秒）。
   真缩短用法：SIZE = ceil(内容/16384)*16384 + 4，输出即「内容 pack + B9」，无尾部 padding。
"""
# 用途：PSS 重封装最终版（固定 16KB pack + BE padding + seq_end），严格复刻原版结构；可输出 .pss 或写回 ISO。
import os, sys, shutil, struct
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pss_remux import parse_ps, enc_ts, make_pack, extract_system_header, extract_first_pack

PACK_SIZE = 16384
MIN_BE = 6  # 00 00 01 be + 2B plen 的最小长度


def make_be_pes(total_len):
    """生成总长为 total_len 的 0xBE padding 流 PES（plen = total_len - 6，内容 0xFF）。"""
    assert total_len >= MIN_BE, f'BE 至少 {MIN_BE} 字节'
    plen = total_len - MIN_BE
    return b'\x00\x00\x01\xbe' + struct.pack('>H', plen) + b'\xff' * plen


def remux(video_pes_list, audio_pes_list, pack_tpl, syshdr, size):
    """把 (key, pes_bytes) 列表按 16KB pack 打包，返回定长 size 的字节串（末尾 b9）。"""
    merged = []
    vi = ai = 0
    while vi < len(video_pes_list) or ai < len(audio_pes_list):
        if ai >= len(audio_pes_list) or (vi < len(video_pes_list) and video_pes_list[vi][0] <= audio_pes_list[ai][0]):
            merged.append(video_pes_list[vi]); vi += 1
        else:
            merged.append(audio_pes_list[ai]); ai += 1

    out = bytearray()
    syshdr_done = False
    buf = None
    last_scr = 0

    def flush():
        nonlocal buf, out, last_scr
        if buf is None:
            return
        r = PACK_SIZE - len(buf)
        if r > 0:
            assert r >= MIN_BE, f'剩余 {r} 字节不足 BE'
            buf += make_be_pes(r)
        assert len(buf) == PACK_SIZE, len(buf)
        out += buf
        buf = None

    for key, pes in merged:
        if buf is not None and len(buf) + len(pes) > PACK_SIZE - MIN_BE:
            flush()
        if buf is None:
            scr = max(0, key - 1000)
            last_scr = scr
            buf = bytearray(make_pack(pack_tpl, scr))
            if not syshdr_done:
                buf += syshdr
                syshdr_done = True
        buf += pes
    flush()

    # 收尾：B9 紧跟最后一个内容 pack（结束信号不被 padding 推后），之后按需补齐到 SIZE
    if len(out) > size - 4:
        raise SystemExit(f'内容超限 {len(out)} > {size-4}')
    pad_after = size - 4 - len(out)
    if pad_after > PACK_SIZE:   # 等长模式且内容明显短于原文件：提示改用真缩短
        print(f'⚠️ 等长模式将在 B9 之后追加 {pad_after} B padding（约 {pad_after/1048576:.1f} MiB）；'
              f'内容只占 {len(out)/(size)/100:.1f}%。建议改用「真缩短 + 后续文件前移」（docs/06-PSS视频.md 方案B）。')
    out += b'\x00\x00\x01\xb9'          # 结束信号：B9 在内容之后立即出现
    while len(out) + PACK_SIZE <= size:  # 等长补齐一律放在 B9 之后
        out += make_pack(pack_tpl, last_scr) + make_be_pes(PACK_SIZE - 14)
    remain = size - len(out)
    if remain > 0:
        out += make_pack(pack_tpl, last_scr)
        r = remain - 14
        assert r >= MIN_BE, f'末尾剩余 {remain}'
        out += make_be_pes(r)
    assert len(out) == size, (len(out), size)
    return bytes(out)


def load_video_seq(vob_path, offset, seq_end=True):
    """解析 FFmpeg vob 视频 PES，回减 offset，重写 PTS/DTS，并把 seq_end 塞进最后视频 PES。"""
    data = open(vob_path, 'rb').read()
    vpkts = parse_ps(data, {0xE0})
    seq = []
    last_vkey = 0
    for p in vpkts:
        has_pts = (p[5] & 0x80) != 0
        has_dts = (p[5] & 0x40) != 0
        if has_dts:
            last_vkey = p[2]
        elif has_pts:
            last_vkey = p[1]
        key = last_vkey - offset
        pes = bytearray(p[3])
        if has_pts:
            pes[9:14] = enc_ts(max(0, p[1] - offset), 0x21)
            if has_dts:
                pes[14:19] = enc_ts(max(0, p[2] - offset), 0x11)
        seq.append((key, bytes(pes)))
    if seq_end and seq:
        # 把 00 00 01 b7 追加到最后一个视频 PES 的 payload 内（真正的 ES 末尾，含续包）
        key, pes = seq[-1]
        pes = bytearray(pes)
        plen = (pes[4] << 8) | pes[5]
        pes[4:6] = struct.pack('>H', plen + 4)
        pes += b'\x00\x00\x01\xb7'
        seq[-1] = (key, bytes(pes))
    return seq


def main():
    if len(sys.argv) < 4:
        print('用法: python pss_remux_v3.py <原版音频.PSS> <新视频.vob> <目标SIZE字节> [LBA] [ISO_IN] [ISO_OUT] [输出.pss]')
        sys.exit(1)
    PSS = sys.argv[1]
    VOB = sys.argv[2]
    SIZE = int(sys.argv[3], 0)
    LBA = int(sys.argv[4], 0) if len(sys.argv) > 4 else None
    ISO_IN = sys.argv[5] if len(sys.argv) > 5 else None
    ISO_OUT = sys.argv[6] if len(sys.argv) > 6 else None
    OUT_PSS = sys.argv[7] if len(sys.argv) > 7 else None

    audio = open(PSS, 'rb').read()
    apkts = parse_ps(audio, {0xBD})
    a0 = min(p[1] for p in apkts if p[1] > 0)
    # vob 视频起始 PTS（用于 offset）
    vdata = open(VOB, 'rb').read()
    vpkts = parse_ps(vdata, {0xE0})
    v0 = min(p[1] for p in vpkts if p[1] > 0)
    offset = v0 - a0
    print(f'音频PES {len(apkts)} 视频PES {len(vpkts)} a0={a0} v0={v0} offset={offset}')

    aseq = [(p[1], bytes(p[3])) for p in apkts]
    vseq = load_video_seq(VOB, offset)
    pack_tpl = extract_first_pack(audio)
    syshdr = extract_system_header(audio)
    print('pack 模板:', pack_tpl.hex(' ').upper(), 'syshdr', len(syshdr), 'B')

    out = remux(vseq, aseq, pack_tpl, syshdr, SIZE)
    print(f'输出 {len(out)} B（应 = {SIZE}）')

    if OUT_PSS:
        with open(OUT_PSS, 'wb') as f:
            f.write(out)
        print(f'写出 .pss: {OUT_PSS}')
    if ISO_IN and ISO_OUT:
        if LBA is None:
            print('写回 ISO 需要 LBA 参数'); sys.exit(1)
        if os.path.exists(ISO_OUT):
            os.remove(ISO_OUT)
        shutil.copyfile(ISO_IN, ISO_OUT)
        with open(ISO_OUT, 'r+b') as f:
            f.seek(LBA * 2048)
            f.write(out)
        print(f'写回 @ LBA 0x{LBA:X} OK')
        print(f'输出 ISO: {ISO_OUT}')
    elif not OUT_PSS:
        print('未指定输出：请提供 ISO_IN/ISO_OUT 或第 7 个参数输出 .pss')
        sys.exit(1)


if __name__ == '__main__':
    main()
