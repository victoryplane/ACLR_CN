# -*- coding: utf-8 -*-
"""把 0A93 字库渲染成 PNG 贴图集，供目检字形形状与值分布。

用法:
  python render_atlas.py <fnt路径> <输出png> [--scale N]
每个字形 16×16 放大 scale 倍平铺；深色底，墨迹按值亮度着色。
"""
# 用途：把 0A93 字库 .fnt 渲染为 PNG 贴图集（目检字形形状与 CLUT 值分布）。依赖 Pillow。
import io, sys
from PIL import Image


# CLUT 亮度：v -> 灰阶（游戏真实渲染 = 值查这个表）
CLUT_GRAY = [0x00, 0x00, 0x46, 0x52, 0x17, 0xBB, 0x79, 0x5D,
             0x23, 0xA4, 0x98, 0x8C, 0xAF, 0x0C, 0x69, 0x2F]


def render_atlas(fnt_path, out_path, scale=8, cols=32, mode='clut', count=877):
    data = io.open(fnt_path, 'rb').read()
    n = count
    rows = (n + cols - 1) // cols
    W, H = cols * 16 * scale, rows * 16 * scale
    img = Image.new('RGB', (W, H), (30, 30, 30))
    d = img.load()
    for g in range(n):
        blk = data[0x67E0 + g * 128:0x67E0 + g * 128 + 128]
        ox = (g % cols) * 16 * scale
        oy = (g // cols) * 16 * scale
        for y in range(16):
            for x in range(16):
                b = blk[y * 8 + x // 2]
                v = (b >> 4) & 0xF if x % 2 == 0 else b & 0xF
                if v == 0:
                    col = (30, 30, 30)
                elif mode == 'ink':
                    col = (255, 255, 255)
                elif mode == 'bright':
                    # 只看亮不亮（CLUT 亮度排序）
                    col = (255, 255, 255) if CLUT_GRAY[v] >= 0x79 else (60, 60, 60)
                else:  # clut：模拟游戏实际渲染
                    gv = CLUT_GRAY[v]
                    col = (gv, gv, gv)
                for sy in range(scale):
                    for sx in range(scale):
                        d[ox + x * scale + sx, oy + y * scale + sy] = col
    img.save(out_path)
    print(f'保存 {out_path}  {img.size}')


if __name__ == '__main__':
    fnt = sys.argv[1]
    out = sys.argv[2]
    scale = 8
    if len(sys.argv) > 3 and sys.argv[3].isdigit():
        scale = int(sys.argv[3])
    count = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].isdigit() else 877
    render_atlas(fnt, out, scale=scale, count=count)