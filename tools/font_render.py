# -*- coding: utf-8 -*-
"""
font_render.py — glyph rasterizer for the 0A93 dialogue font library (Armored Core: Last Raven).

Turns text glyphs rasterized from a TTF/TTC font of your choice into the 16x16 4bpp glyph blocks
(128 bytes each) that the 0A93 font library stores, so the library can be rebuilt with your own
translation glyphs. This is a **library module**: it exposes functions and has no command-line
interface, so importing it prints nothing and does nothing.

Rendering pipeline (per glyph):
  TTF glyph -> high-resolution grayscale -> bicubic/Lanczos downscale to fit 16x16 -> contrast
  thresholds -> 4bpp CLUT index block.

0A93.fnt bitmap area layout (locked down byte for byte):
  The bitmap area starts at file offset 0x67E0 and each glyph is 128 bytes = 16 rows x 8 bytes,
  every byte holding 2 pixels. The 4bpp value stored in a pixel is a CLUT index (0 = transparent
  background, 5 = brightest core, the rest are antialiasing grey levels).
  Inside a byte the **low nibble is the LEFT pixel** and the high nibble the right one (getting
  this the wrong way round injects mirrored glyphs).

CLUT brightness order (dark -> bright) -> index:
  0x0C->13, 0x17->4, 0x23->8, 0x2F->15, 0x46->2, 0x52->3, 0x5D->7,
  0x69->14, 0x79->6, 0x8C->11, 0x98->10, 0xA4->9, 0xAF->12, 0xBB->5

Value -> on-screen alpha (measured from emulator texture dumps):
  v -> RGBA(128,128,128, ALPHA[v]) with ALPHA = [0,0,51,59,16,128,85,59,24,111,103,93,119,8,69,34],
  i.e. the white core v5 is alpha 128 (semi-transparent, not opaque), the edge index v12 is 119 and
  the dark index v15 is 34. Only the bright part of the CLUT is used for strokes, to avoid dirty
  dots from the dim indices.

Functions (every `*_glyph_block` helper returns a 128-byte block, or None when the glyph is empty):
  resolve_font(name, font_path=None)
        Resolve a font file: an explicitly passed `font_path` wins, otherwise FONT_DIR + file name.
  render_gray(ch, font_path, render_px=128, target=15.0, weight=None)
        Render one character into a 16x16 grayscale array (0.0-1.0, 0 = transparent):
        render at render_px, crop to the ink bounding box, scale proportionally to `target`,
        centre it in 16x16.
  gray_to_clut(gray_rows, cutoff=0.25, core_at=0.60, shadow=0)
        Grayscale array -> 4bpp value block with a hard threshold (core -> v5, edge -> v12) and
        isolated-pixel cleanup; `shadow=1` lays one row of v15 directly under every stroke.
  aa_to_block(aa, core_th=0.60, edge_th=0.30, shadow=True, core=5, edge=12)
        Same idea on an antialiased 16x16 array: core -> v5, edge -> v12, shadow row v15.
  aa_to_block_soft(aa, shadow=True, blur_passes=1, gamma=1.0, core_boost=1.0, shadow_val=None)
        Soft version: 3x3 gaussian blur, then map each pixel through the alpha ramp
        (`target = round(min(1.0, a ** gamma) * 128)`, nearest ALPHA_RAMP entry) to get a smooth
        antialiased gradient instead of two levels; default shadow value 13 (alpha 8, the value
        settled on by measurement).
  simsun_ink_grid(ch, size=16, font_path=None) / simsun_glyph_block(ch, shadow=True, ...)
        Use the 16px embedded bitmap (EBDT/EBLC strike) built into SimSun as the glyph source;
        the ink grid is centred in 16x16 and packed as core v5 plus an optional v15 shadow row.
  render16_aa(ch, font_path, size=16)
        16px FreeType-hinted rendering with a bounding box + ink-centroid alignment, clamped so
        that nothing is ever clipped.
  simhei_glyph_block(ch, shadow=True, blur_passes=1, gamma=1.0, shadow_val=None, font_path=None)
        SimHei 16px rendering with blurred soft edges -> value block.
  render16_ascii_baseline(ch, font_path, size=16, baseline_row=13)
        ASCII rendering aligned on one shared baseline (the descenders of g/j/p/q stay below it).
  simhei_ascii_glyph_block(ch, shadow=True, baseline_row=13, font_path=None)
        The same for ASCII in SimHei, packed to a 128-byte block.
  blur16(grid, passes=1) / block_ascii(block, bright=5) / nonzero_pixels(block)
        Helpers: 16x16 3x3 gaussian blur; ASCII art of a block ('.' transparent, '#' core,
        'o' grey); count of nonzero pixels in a block.

Usage (library — no CLI, import it from your own script):
  from font_render import simhei_glyph_block
  block = simhei_glyph_block('汉', font_path='C:/fonts/simhei.ttf')   # -> 128 bytes, or None

Dependencies:
  Pillow is required for every rendering function; `fontTools` is needed only to instantiate a
  variable font (e.g. NotoSansSC-VF.ttf) at a fixed weight.
Fonts are supplied by the user: set the environment variable FONT_DIR=<font directory>, or pass
`font_path` explicitly to the `*_glyph_block` family. FONT_FILES only maps a friendly name to a
file name and assumes no absolute system path.

------------------------------------------------------------------------------
中文说明

0A93 对话字库字形光栅器——AC Last Raven 汉化用。

渲染管线：TTF 字形 → 高分辨率灰度 → 双三次缩小到 16×16 → 强对比 → 4bpp CLUT 索引。

0A93.fnt 位图区格式（已锁定）：
  位图区起点 0x67E0，每个字形 128 字节 = 16 行 × 8 字节，每字节 2 像素（低半字节=左，高=右）。
  4bpp 值是 CLUT 索引（0=背景透明，5=最亮核心，其余为抗锯齿灰阶）。

CLUT 亮度排序（暗→亮）→ 索引：
  0x0C→13, 0x17→4, 0x23→8, 0x2F→15, 0x46→2, 0x52→3, 0x5D→7,
  0x69→14, 0x79→6, 0x8C→11, 0x98→10, 0xA4→9, 0xAF→12, 0xBB→5
"""
# 用途：Rasterize TTF/TTC glyphs into 16×16 4bpp glyph blocks (128 bytes) for the 0A93 font library. Requires Pillow; fontTools is needed only to instantiate a variable font.
import io

# CLUT brightness values (v -> 0xRGB brightness), used to tell how light an index is
CLUT_GRAY = [0x00, 0x00, 0x46, 0x52, 0x17, 0xBB, 0x79, 0x5D,
             0x23, 0xA4, 0x98, 0x8C, 0xAF, 0x0C, 0x69, 0x2F]

# Only the bright CLUT indices (0x79~0xBB) are used, dark -> bright. Avoid the dim indices to prevent dirty dots.
CLUT_BRIGHT_RAMP = [6, 11, 10, 9, 12, 5]   # 0x79,0x8C,0x98,0xA4,0xAF,0xBB
CLUT_CORE_IDX = 5                          # 0xBB brightest, the core strokes
# Dark (outline/shadow) uses the darkest index
DARK_IDX = 15

# The font file is provided by the user: set the environment variable FONT_DIR=<font directory>, or pass font_path explicitly to the *_glyph_block functions.
# FONT_FILES only maps "common font name -> file name" and assumes no absolute system path.
import os
FONT_DIR = os.environ.get('FONT_DIR', '').strip()
FONT_FILES = {
    'noto_sc': 'NotoSansSC-VF.ttf',   # open-source Noto family (variable font)
    'simhei':  'simhei.ttf',          # SimHei
    'msyh':    'msyh.ttc',            # Microsoft YaHei
    'simsun':  'simsun.ttc',          # SimSun (contains a 16px bitmap EBDT/EBLC 1bpp strike, usable as a glyph source)
}

def resolve_font(name, font_path=None):
    """Return the actual font file path: an explicit font_path wins, otherwise FONT_DIR + file name."""
    if font_path:
        return font_path
    if not FONT_DIR:
        raise SystemExit('No font specified: set the environment variable FONT_DIR=<font directory>, '
                         'or pass the font_path argument explicitly. '
                         '(未指定字体：请设置环境变量 FONT_DIR=<字体目录>，或显式传入 font_path 参数)')
    return os.path.join(FONT_DIR, FONT_FILES[name])


_WT_CACHE = {}


def _instantiate_weight(font_path, weight):
    """Freeze a variable font at the given weight (cached) and return a usable font path."""
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
    """Render a single character into a 16x16 grayscale array (0.0-1.0, 0 = transparent).

    Pipeline: render the TTF at render_px -> crop to the ink bounding box -> scale proportionally
    to target -> centre it in 16x16.
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
    # crop the ink
    crop = img.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
    # scale proportionally to target (leaving 1px of breathing room)
    scale = target / max(w, h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    crop = crop.resize((nw, nh), Image.LANCZOS)
    # centre it inside 16x16
    out = [[0.0] * 16 for _ in range(16)]
    ox = (16 - nw) // 2
    oy = (16 - nh) // 2
    px = crop.load()
    for y in range(nh):
        for x in range(nw):
            out[oy + y][ox + x] = px[x, y] / 255.0
    return out


# The single bright edge index (0xAF, second brightest)
CLUT_EDGE_IDX = 12


def gray_to_clut(gray_rows, cutoff=0.25, core_at=0.60, shadow=0):
    """16x16 grayscale array -> 4bpp value byte block (128 bytes).

    What the game renders (confirmed pixel by pixel through emulator texture dumps):
      v -> RGBA(128,128,128, ALPHA[v]), ALPHA=[0,0,51,59,16,128,85,59,24,111,103,93,119,8,69,34]
      core v5 -> alpha128 (the maximum, i.e. the most opaque value), edge v12 -> 119, shadow v15 -> 34.
    Bitmap decoding: **low nibble = LEFT pixel** (not the high nibble! getting it the other way
    round produced mirrored injected glyphs).

    shadow=1 : lay 1px of v15 shadow directly under every stroke (mimicking the original's dy+1
    dark edge, measured).
    """
    block = bytearray(128)

    def setpx(x, y, v):
        if not (0 <= x < 16 and 0 <= y < 16) or v <= 0:
            return
        bi = y * 8 + x // 2
        if x % 2 == 0:
            block[bi] = (block[bi] & 0xF0) | v           # left pixel -> low nibble
        else:
            block[bi] = (block[bi] & 0x0F) | (v << 4)   # right pixel -> high nibble

    grid = [[0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            a = gray_rows[y][x]
            if a < cutoff:
                continue
            grid[y][x] = CLUT_CORE_IDX if a >= core_at else CLUT_EDGE_IDX

    # isolated-pixel cleanup: a pixel with no ink in its 8-neighbourhood is cleared
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
        # lay a shadow 1px directly under every stroke (where that pixel is not a stroke itself)
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
    """128-byte 4bpp block -> ASCII lines (. = transparent, # = core, o = grey level)."""
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
    """Render one character from SimSun's built-in 16px bitmap and return a 16x16 ink grid (1 = ink).

    Relies on FreeType automatically picking SimSun's (e.g. simsun's) EBDT/EBLC 16px 1bpp strike.
    The ink is centred in 16x16 by its bounding box (matching the original's "ink centred on
    (7.5,7.5)").
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
        # oversized glyphs are scaled down proportionally (very rare)
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
    """Render one character at 16px with the given font (FreeType hinting) -> 16x16 grayscale (0-1).

    Hybrid alignment: bounding-box centring (which guarantees no clipping) corrected towards the
    ink centroid, but clamped to the "no overflow, no clipping" range — as visually centred as
    possible without losing strokes.
    """
    from PIL import Image, ImageFont, ImageDraw
    font = ImageFont.truetype(font_path, size)
    canvas = 96
    img = Image.new('L', (canvas, canvas), 0)
    d = ImageDraw.Draw(img)
    d.text((canvas // 2 - size // 2, canvas // 2 - size // 2), ch, font=font, fill=255)
    px = img.load()
    # bounding box + weighted centroid
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
    # top-left corner of the window: line the centroid up with (7.5,7.5)
    ox_t = cx - 7.5
    oy_t = cy - 7.5
    # clamping: the window [ox,ox+16) must contain the bounding box [x0,x1]x[y0,y1]
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
    """16x16 grayscale -> 0A93 value block (low nibble = left).

    core (>=core_th) -> v5, edge (<core_th and >=edge_th) -> v12, shadow = v15 laid at dy+1 below
    the stroke.
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


# value -> render alpha (measured): [v0..v15]
VALUE_ALPHA = [0, 0, 51, 59, 16, 128, 85, 59, 24, 111, 103, 93, 119, 8, 69, 34]
# (alpha, value) ordered from brightest alpha to dimmest
ALPHA_RAMP = [(128, 5), (119, 12), (111, 9), (103, 10), (93, 11), (85, 6),
              (69, 14), (59, 3), (51, 2), (34, 15), (24, 8), (16, 4), (8, 13), (0, 0)]


def blur16(grid, passes=1):
    """3x3 gaussian blur of a 16x16 grid. passes=1 does a single pass."""
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
    """Grayscale -> 0A93 value block (blurred + smooth alpha gradient, low nibble = left).

    blur_passes : number of gaussian blur passes (more = softer edges)
    gamma       : contrast curve (<1 brightens the edges, >1 tightens them)
    shadow_val  : shadow value (default 13 = alpha8, extremely faint; the value settled on by
                  measurement)
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
            # map the curve into 0..1
            c = min(1.0, a ** gamma)
            alpha_t = round(c * 128)
            # find the nearest alpha on the ramp
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
    """SimHei 16px rendering with blurred soft edges -> 0A93 value block."""
    aa = render16_aa(ch, resolve_font('simhei', font_path))
    if aa is None:
        return None
    return aa_to_block_soft(aa, shadow=shadow, blur_passes=blur_passes,
                            gamma=gamma, shadow_val=shadow_val)


def render16_ascii_baseline(ch, font_path, size=16, baseline_row=13):
    """Render an ASCII character aligned on the baseline (the descenders of g/j/p/q sit below it).

    Every ASCII character lands on the same baseline_row, which is what typesetting requires.
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
    """SimHei ASCII baseline-aligned -> 0A93 value block (measured; the final version)."""
    aa = render16_ascii_baseline(ch, resolve_font('simhei', font_path), baseline_row=baseline_row)
    if aa is None:
        return None
    return aa_to_block_soft(aa, shadow=shadow, blur_passes=0, shadow_val=13)


def simsun_glyph_block(ch, shadow=True, core=CLUT_CORE_IDX, edge=CLUT_EDGE_IDX):
    """SimSun bitmap -> 0A93 128-byte glyph block (low nibble = left).

    shadow=1: lay 1px of v15 shadow directly under every stroke (mimicking the original's dy+1
    dark edge).
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
