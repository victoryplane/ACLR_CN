# -*- coding: utf-8 -*-
"""
render_atlas.py — render a 0A93 font library (.fnt) to a PNG atlas for visual inspection.

The script paints the glyph bitmap region of a 0A93 font library into one PNG sheet so that glyph
shapes and the distribution of the 4bpp CLUT values can be checked by eye (a single glance reveals
missing glyphs, clipped strokes, stray dark dots and wrong quantization). Each glyph is 16x16 at
4bpp = 128 bytes, tiled left to right, top to bottom, 32 glyphs per row, and every pixel is drawn
as a grey level taken from the CLUT of the value stored in it.

Usage:
  python render_atlas.py <fnt path> <output png> [scale] [count]
        <fnt path>    the 0A93 font library file (your own copy; it is only read)
        <output png>  atlas to write — an existing file of that name is overwritten
        [scale]       integer magnification per glyph pixel (default 8); a non-integer argument
                      is ignored and the default is used
        [count]       number of glyphs to draw (default 877); a non-integer argument is ignored
                      and the default is used
        The sheet is `32 * 16 * scale` wide and `ceil(count / 32) * 16 * scale` tall.

Examples:
  python render_atlas.py 0A93.fnt 0A93_atlas.png
  python render_atlas.py 0A93.fnt 0A93_atlas.png 4 64

------------------------------------------------------------------------------
中文说明

把 0A93 字库渲染成 PNG 贴图集，供目检字形形状与值分布。

用法:
  python render_atlas.py <fnt路径> <输出png> [scale] [count]
每个字形 16×16 放大 scale 倍平铺；深色底，墨迹按值亮度着色。
"""
# 用途：把 0A93 字库 .fnt 渲染为 PNG 贴图集（目检字形形状与 CLUT 值分布）。依赖 Pillow。
import io, sys
from PIL import Image


# CLUT brightness: v -> grey level (this is the table the game itself renders through)
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
                    # bright or not only (CLUT brightness order)
                    col = (255, 255, 255) if CLUT_GRAY[v] >= 0x79 else (60, 60, 60)
                else:  # clut: mimic what the game actually renders
                    gv = CLUT_GRAY[v]
                    col = (gv, gv, gv)
                for sy in range(scale):
                    for sx in range(scale):
                        d[ox + x * scale + sx, oy + y * scale + sy] = col
    img.save(out_path)
    print(f'saved {out_path}  {img.size}')


# 无参数 / --help：打印用法（缺参数时退出码仍为 1）
if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] in ('-h', '--help'):
        print((__doc__ or '').strip())
        sys.exit(0 if len(sys.argv) > 1 else 1)
    fnt = sys.argv[1]
    out = sys.argv[2]
    scale = 8
    if len(sys.argv) > 3 and sys.argv[3].isdigit():
        scale = int(sys.argv[3])
    count = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].isdigit() else 877
    render_atlas(fnt, out, scale=scale, count=count)