# -*- coding: utf-8 -*-
"""0A93 对话字库字形光栅器——AC Last Raven 汉化用。

渲染管线：TTF 字形 → 高分辨率灰度 → 双三次缩小到 16×16 → 强对比 → 4bpp CLUT 索引。

0A93.fnt 位图区格式（已锁定）：
  位图区起点 0x67E0，每个字形 128 字节 = 16 行 × 8 字节，每字节 2 像素（高半字节=左，低=右）。
  4bpp 值是 CLUT 索引（0=背景透明，5=最亮核心，其余为抗锯齿灰阶）。

CLUT 亮度排序（暗→亮）→ 索引：
  0x0C→13, 0x17→4, 0x23→8, 0x2F→15, 0x46→2, 0x52→3, 0x5D→7,
  0x69→14, 0x79→6, 0x8C→11, 0x98→10, 0xA4→9, 0xAF→12, 0xBB→5
"""
# 用途：把 TTF/TTC 字形光栅化为 0A93 字库的 16×16 4bpp 字形块（128 字节）。依赖 Pillow；fontTools 仅在实例化可变字体时需要。
import io

# CLUT 亮度值（v -> 0xRGB 亮度），用于判断索引的明暗
CLUT_GRAY = [0x00, 0x00, 0x46, 0x52, 0x17, 0xBB, 0x79, 0x5D,
             0x23, 0xA4, 0x98, 0x8C, 0xAF, 0x0C, 0x69, 0x2F]

# 只用 CLUT 亮索引（0x79~0xBB），暗→亮。避开暗索引避免脏点。
CLUT_BRIGHT_RAMP = [6, 11, 10, 9, 12, 5]   # 0x79,0x8C,0x98,0xA4,0xAF,0xBB
CLUT_CORE_IDX = 5                          # 0xBB 最亮，核心笔画
# 暗（描边/阴影）用最暗索引
DARK_IDX = 15

# 字体文件由使用者自备：设置环境变量 FONT_DIR=<字体目录>，或调用 *_glyph_block 系列时显式传 font_path。
# FONT_FILES 只记录「常见字体名 -> 文件名」，不预设任何系统绝对路径。
import os
FONT_DIR = os.environ.get('FONT_DIR', '').strip()
FONT_FILES = {
    'noto_sc': 'NotoSansSC-VF.ttf',   # 开源 Noto 系列（可变字体）
    'simhei':  'simhei.ttf',          # 黑体
    'msyh':    'msyh.ttc',            # 雅黑
    'simsun':  'simsun.ttc',          # 宋体（内含 16px 点阵 EBDT/EBLC 1bpp，可作字源）
}

def resolve_font(name, font_path=None):
    """返回实际字体文件路径：优先用显式传入的 font_path，否则取 FONT_DIR + 文件名。"""
    if font_path:
        return font_path
    if not FONT_DIR:
        raise SystemExit('未指定字体：请设置环境变量 FONT_DIR=<字体目录>，或显式传入 font_path 参数')
    return os.path.join(FONT_DIR, FONT_FILES[name])


_WT_CACHE = {}


def _instantiate_weight(font_path, weight):
    """把可变字体固化为指定字重（带缓存），返回可用字体路径。"""
    if weight is None or 'VF' not in font_path:
        return font_path
    key = (font_path, weight)
    if key in _WT_CACHE:
        return _WT_CACHE[key]
    import tempfile, os
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    fvar = TTFont(font_path, lazy=True)['fvar']
    tags = [a.axisTag for a in fvar.axes]
    if 'wght' not in tags:
        _WT_CACHE[key] = font_path
        return font_path
    with TTFont(font_path) as f:
        inst = instantiateVariableFont(f, {'wght': weight})
        tmp = os.path.join(tempfile.gettempdir(),
                           f'notosc_{weight}.ttf')
        inst.save(tmp)
    _WT_CACHE[key] = tmp
    return tmp


def render_gray(ch, font_path, render_px=128, target=15.0, weight=None):
    """把单字渲染为 16×16 灰度数组（0.0-1.0，0=透明）。

    管线：TTF 渲染 render_px → 裁剪墨迹包围盒 → 等比缩放到 target → 居中放入 16×16。
    """
    from PIL import Image, ImageFont, ImageDraw

    fp = _instantiate_weight(font_path, weight)
    font = ImageFont.truetype(fp, render_px)

    img = Image.new('L', (render_px * 2, render_px * 2), 0)
    d = ImageDraw.Draw(img)
    d.text((render_px // 2, render_px // 2), ch, font=font, fill=255)
    try:
        bbox = d.textbbox((render_px // 2, render_px // 2), ch, font=font)
    except Exception:
        bbox = (0, 0, render_px, render_px)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if w <= 0 or h <= 0:
        return None
    # 裁剪墨迹
    crop = img.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
    # 等比缩放到 target（留 1px 呼吸）
    scale = target / max(w, h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    crop = crop.resize((nw, nh), Image.LANCZOS)
    # 居中放入 16×16
    out = [[0.0] * 16 for _ in range(16)]
    ox = (16 - nw) // 2
    oy = (16 - nh) // 2
    px = crop.load()
    for y in range(nh):
        for x in range(nw):
            out[oy + y][ox + x] = px[x, y] / 255.0
    return out


# 单一边缘亮索引（0xAF，次亮）
CLUT_EDGE_IDX = 12


def gray_to_clut(gray_rows, cutoff=0.25, core_at=0.60, shadow=0):
    """16×16 灰度数组 → 4bpp 值字节块（128 字节）。

    游戏渲染（经模拟器纹理转储逐像素确认）：
      v → RGBA(128,128,128, ALPHA[v])，ALPHA=[0,0,51,59,16,128,85,59,24,111,103,93,119,8,69,34]
      核心 v5→alpha128 全不透明、边缘 v12→119、阴影 v15→34。
    位图解码：**低半字节 = 左像素**（不是高半字节！之前写反导致注入字形镜像）。

    shadow=1 : 每笔画正下方 1px 垫 v15 阴影（仿原版 dy+1 暗边，实测）。
    """
    block = bytearray(128)

    def setpx(x, y, v):
        if not (0 <= x < 16 and 0 <= y < 16) or v <= 0:
            return
        bi = y * 8 + x // 2
        if x % 2 == 0:
            block[bi] = (block[bi] & 0xF0) | v           # 左像素 → 低半字节
        else:
            block[bi] = (block[bi] & 0x0F) | (v << 4)   # 右像素 → 高半字节

    grid = [[0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            a = gray_rows[y][x]
            if a < cutoff:
                continue
            grid[y][x] = CLUT_CORE_IDX if a >= core_at else CLUT_EDGE_IDX

    # 孤立像素清理：8 邻域无墨迹的像素置 0
    for y in range(16):
        for x in range(16):
            if grid[y][x] == 0:
                continue
            has_nbr = False
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < 16 and 0 <= nx < 16 and grid[ny][nx] != 0:
                        has_nbr = True
                        break
                if has_nbr:
                    break
            if not has_nbr:
                grid[y][x] = 0

    if shadow:
        # 每笔画正下方 1px 垫阴影（若该处非笔画）
        for y in range(15, -1, -1):
            for x in range(16):
                if grid[y][x] and y + 1 < 16 and grid[y + 1][x] == 0:
                    grid[y + 1][x] = DARK_IDX

    for y in range(16):
        for x in range(16):
            v = grid[y][x]
            if v:
                setpx(x, y, v)
    return bytes(block)


def block_ascii(block, bright=5):
    """128 字节 4bpp 块 → ASCII 行（. = 透明, # = 核心, o = 灰阶）。"""
    lines = []
    for r in range(16):
        line = []
        for b in block[r * 8:r * 8 + 8]:
            hi, lo = (b >> 4) & 0xF, b & 0xF
            for v in (hi, lo):
                if v == 0:
                    line.append('.')
                elif v == bright:
                    line.append('#')
                else:
                    line.append('o')
        lines.append(''.join(line))
    return lines


def nonzero_pixels(block):
    n = 0
    for b in block:
        n += ((b >> 4) & 0xF) != 0
        n += (b & 0xF) != 0
    return n


def simsun_ink_grid(ch, size=16, font_path=None):
    """用宋体内置 16px 点阵位图渲染单字，返回 16×16 墨迹网格（1=墨）。

    依赖 FreeType 自动选择宋体（如 simsun）的 EBDT/EBLC 16px 1bpp strike。
    按墨迹包围盒居中放入 16×16（对齐原版「墨迹居中 (7.5,7.5)」）。
    """
    from PIL import Image, ImageFont, ImageDraw
    font = ImageFont.truetype(resolve_font('simsun', font_path), size)
    img = Image.new('L', (64, 64), 0)
    d = ImageDraw.Draw(img)
    d.text((4, 4), ch, font=font, fill=255)
    px = img.load()
    xs, ys = [], []
    for y in range(64):
        for x in range(64):
            if px[x, y] > 0:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    if w > 16 or h > 16:
        # 特大字按比例缩小（极少见）
        s = min(15 / w, 15 / h)
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        crop = img.crop((x0, y0, x1 + 1, y1 + 1)).resize((nw, nh), Image.LANCZOS)
        cpx = crop.load()
        ox = (16 - nw) // 2
        oy = (16 - nh) // 2
        grid = [[0] * 16 for _ in range(16)]
        for yy in range(nh):
            for xx in range(nw):
                grid[oy + yy][ox + xx] = 1 if cpx[xx, yy] > 128 else 0
        return grid
    grid = [[0] * 16 for _ in range(16)]
    ox = (16 - w) // 2
    oy = (16 - h) // 2
    for yy in range(h):
        for xx in range(w):
            grid[oy + yy][ox + xx] = 1 if px[x0 + xx, y0 + yy] > 0 else 0
    return grid


def render16_aa(ch, font_path, size=16):
    """用指定字体按 16px 渲染单字（FreeType hinting），返回 16×16 灰度数组(0-1)。

    混合对齐：包围盒居中（保证不裁）基础上，向墨迹质心校正，
    但钳制在「不越界不裁切」的范围内——最大化视觉居中又不丢笔画。
    """
    from PIL import Image, ImageFont, ImageDraw
    font = ImageFont.truetype(font_path, size)
    canvas = 96
    img = Image.new('L', (canvas, canvas), 0)
    d = ImageDraw.Draw(img)
    d.text((canvas // 2 - size // 2, canvas // 2 - size // 2), ch, font=font, fill=255)
    px = img.load()
    # 包围盒 + 加权质心
    xs, ys = [], []
    total = 0.0
    cx = cy = 0.0
    for y in range(canvas):
        for x in range(canvas):
            v = px[x, y]
            if v > 0:
                w = v / 255.0
                xs.append(x)
                ys.append(y)
                total += w
                cx += x * w
                cy += y * w
    if not xs:
        return None
    cx /= total
    cy /= total
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    # 窗口左上角：让质心对准 (7.5,7.5)
    ox_t = cx - 7.5
    oy_t = cy - 7.5
    # 钳制：窗口 [ox,ox+16) 必须包含包围盒 [x0,x1]×[y0,y1]
    ox = round(ox_t)
    oy = round(oy_t)
    ox = max(ox, x1 - 15)   # x1-ox <= 15
    ox = min(ox, x0)        # x0-ox >= 0
    oy = max(oy, y1 - 15)
    oy = min(oy, y0)
    ox = max(0, min(canvas - 16, ox))
    oy = max(0, min(canvas - 16, oy))
    aa = [[0.0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            aa[y][x] = px[ox + x, oy + y] / 255.0
    return aa


def aa_to_block(aa, core_th=0.60, edge_th=0.30, shadow=True,
                core=CLUT_CORE_IDX, edge=CLUT_EDGE_IDX):
    """16×16 灰度 → 0A93 值块（低半字节=左）。

    核心(≥core_th)→v5，边缘(<core_th且≥edge_th)→v12，阴影=笔画下方 dy+1 垫 v15。
    """
    block = bytearray(128)

    def setpx(x, y, v):
        if not (0 <= x < 16 and 0 <= y < 16) or v <= 0:
            return
        bi = y * 8 + x // 2
        if x % 2 == 0:
            block[bi] = (block[bi] & 0xF0) | v
        else:
            block[bi] = (block[bi] & 0x0F) | (v << 4)

    for y in range(16):
        for x in range(16):
            a = aa[y][x]
            if a < edge_th:
                continue
            if a >= core_th:
                setpx(x, y, core)
                if shadow and y + 1 < 16 and aa[y + 1][x] < edge_th:
                    setpx(x, y + 1, DARK_IDX)
            else:
                setpx(x, y, edge)
    return bytes(block)


# 值 → 渲染 alpha（实测确认）：[v0..v15]
VALUE_ALPHA = [0, 0, 51, 59, 16, 128, 85, 59, 24, 111, 103, 93, 119, 8, 69, 34]
# 按 alpha 从亮到暗排列的 (alpha, value)
ALPHA_RAMP = [(128, 5), (119, 12), (111, 9), (103, 10), (93, 11), (85, 6),
              (69, 14), (59, 3), (51, 2), (34, 15), (24, 8), (16, 4), (8, 13), (0, 0)]


def blur16(grid, passes=1):
    """16×16 网格 3×3 高斯模糊。passes=1 只做 1 遍。"""
    g = [row[:] for row in grid]
    kernel = {(-1, -1): 1, (-1, 0): 2, (-1, 1): 1,
              (0, -1): 2, (0, 0): 4, (0, 1): 2,
              (1, -1): 1, (1, 0): 2, (1, 1): 1}
    for _ in range(passes):
        ng = [[0.0] * 16 for _ in range(16)]
        for y in range(16):
            for x in range(16):
                s = 0.0
                for (dy, dx), w in kernel.items():
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < 16 and 0 <= nx < 16:
                        s += g[ny][nx] * w
                ng[y][x] = s / 16.0
        g = ng
    return g


def aa_to_block_soft(aa, shadow=True, blur_passes=1, gamma=1.0, core_boost=1.0,
                     shadow_val=None):
    """灰度 → 0A93 值块（模糊化 + 平滑 alpha 渐变，低半字节=左）。

    blur_passes : 高斯模糊遍数（越大边缘越柔）
    gamma       : 对比度曲线（<1 提亮边缘，>1 收紧）
    shadow_val  : 阴影值（默认 13=alpha8 极淡，实测为定稿值）
    """
    if shadow_val is None:
        shadow_val = 13
    grid = blur16(aa, blur_passes)
    block = bytearray(128)

    def setpx(x, y, v):
        if not (0 <= x < 16 and 0 <= y < 16) or v <= 0:
            return
        bi = y * 8 + x // 2
        if x % 2 == 0:
            block[bi] = (block[bi] & 0xF0) | v
        else:
            block[bi] = (block[bi] & 0x0F) | (v << 4)

    for y in range(16):
        for x in range(16):
            a = grid[y][x]
            if a <= 0.01:
                continue
            # 曲线映射到 0..1
            c = min(1.0, a ** gamma)
            alpha_t = round(c * 128)
            # 找最近的 ramp alpha
            best = 0
            best_d = 999
            for ra, rv in ALPHA_RAMP:
                d = abs(ra - alpha_t)
                if d < best_d:
                    best_d = d
                    best = rv
            if best == 0:
                continue
            setpx(x, y, best)
            if shadow and y + 1 < 16 and grid[y + 1][x] <= 0.01:
                setpx(x, y + 1, shadow_val)
    return bytes(block)


def simhei_glyph_block(ch, shadow=True, blur_passes=1, gamma=1.0, shadow_val=None, font_path=None):
    """黑体 16px 渲染 + 模糊柔边 → 0A93 值块。"""
    aa = render16_aa(ch, resolve_font('simhei', font_path))
    if aa is None:
        return None
    return aa_to_block_soft(aa, shadow=shadow, blur_passes=blur_passes,
                            gamma=gamma, shadow_val=shadow_val)


def render16_ascii_baseline(ch, font_path, size=16, baseline_row=13):
    """ASCII 字符按基线对齐渲染（g/j/p/q 下伸部在基线下方）。

    所有 ASCII 坐落在同一 baseline_row，符合排版规则。
    """
    from PIL import Image, ImageFont, ImageDraw
    font = ImageFont.truetype(font_path, size)
    ascent, _descent = font.getmetrics()
    canvas = 64
    img = Image.new('L', (canvas, canvas), 0)
    d = ImageDraw.Draw(img)
    draw_y = 20
    d.text((8, draw_y), ch, font=font, fill=255)
    px = img.load()
    xs, ys = [], []
    for y in range(canvas):
        for x in range(canvas):
            if px[x, y] > 0:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    baseline_y = draw_y + ascent
    x0, x1 = min(xs), max(xs)
    w = x1 - x0 + 1
    ox = x0 - (16 - w) // 2
    oy = baseline_y - baseline_row
    ox = max(0, min(canvas - 16, ox))
    oy = max(0, min(canvas - 16, oy))
    aa = [[0.0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            aa[y][x] = px[ox + x, oy + y] / 255.0
    return aa


def simhei_ascii_glyph_block(ch, shadow=True, baseline_row=13, font_path=None):
    """黑体 ASCII 基线对齐 → 0A93 值块（实测定稿）。"""
    aa = render16_ascii_baseline(ch, resolve_font('simhei', font_path), baseline_row=baseline_row)
    if aa is None:
        return None
    return aa_to_block_soft(aa, shadow=shadow, blur_passes=0, shadow_val=13)


def simsun_glyph_block(ch, shadow=True, core=CLUT_CORE_IDX, edge=CLUT_EDGE_IDX):
    """simsun 点阵 → 0A93 128 字节字形块（低半字节=左）。

    shadow=1：每笔画正下方 1px 垫 v15 阴影（仿原版 dy+1 暗边）。
    """
    grid = simsun_ink_grid(ch)
    if grid is None:
        return None
    block = bytearray(128)

    def setpx(x, y, v):
        if not (0 <= x < 16 and 0 <= y < 16) or v <= 0:
            return
        bi = y * 8 + x // 2
        if x % 2 == 0:
            block[bi] = (block[bi] & 0xF0) | v
        else:
            block[bi] = (block[bi] & 0x0F) | (v << 4)

    for y in range(16):
        for x in range(16):
            if grid[y][x]:
                setpx(x, y, core)
                if shadow and y + 1 < 16 and not grid[y + 1][x]:
                    setpx(x, y + 1, DARK_IDX)
    return bytes(block)
