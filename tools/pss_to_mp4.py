# -*- coding: utf-8 -*-
"""
pss_to_mp4.py — batch PSS -> MP4 preview export (video track only).

Walks a whole directory tree, finds every `.PSS` file (case-insensitive extension) and remuxes
its **video track only** into MP4 with ffmpeg:

  - container/quality are fixed: `-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p` (crf18,
    visually near-lossless: this is a preview/inspection path, not a master);
  - `-map 0:v:0` picks the first video stream and nothing else. **The audio is not packaged**:
    in PSS it is PS2 ADPCM, and converting it would need a decoder the script deliberately does
    not depend on;
  - the directory layout relative to the input root is mirrored under `<root>/mp4/`, so
    `MOVIE/ES1.PSS` becomes `mp4/MOVIE/ES1.mp4`;
  - anything whose path contains `mp4` is skipped, so re-running the tool inside its own output
    directory is harmless;
  - a file is reported `OK` when the output exists and is non-empty, `FAIL` otherwise (ffmpeg's
    first line of stderr is appended to the FAIL line).

External dependency: `ffmpeg`, taken from `PATH` or from the `FFMPEG` environment variable.
ffmpeg is invoked with `-y`, so existing outputs are overwritten in place.

Usage:
  python pss_to_mp4.py [root]
        Convert every .PSS under [root] (default: the current directory) to <root>/mp4/**.mp4.
        The only argument is the input root; there are no options, and the run is a full batch —
        output cannot be limited to a single file.

Environment:
  FFMPEG=<path to ffmpeg>   use that executable instead of the one found on PATH.

Examples:
  python pss_to_mp4.py MOVIE
  FFMPEG=/opt/ffmpeg/bin/ffmpeg python pss_to_mp4.py extracted

------------------------------------------------------------------------------
中文说明

把目录下全部 PSS 转成 MP4（视频轨，H.264 crf18；音频是 PS2 ADPCM 暂不封装）。"""
# 用途：批量 PSS→MP4 预览（视频轨），外部依赖 ffmpeg（默认取 PATH，可用环境变量 FFMPEG 覆盖）。
import os, subprocess, sys

sys.stdout.reconfigure(encoding='utf-8')
FFMPEG = os.environ.get('FFMPEG', 'ffmpeg')
ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'
OUT = os.path.join(ROOT, 'mp4')
os.makedirs(OUT, exist_ok=True)

files = []
for dirpath, _, names in os.walk(ROOT):
    if 'mp4' in dirpath:
        continue
    for n in names:
        if n.upper().endswith('.PSS'):
            files.append(os.path.join(dirpath, n))
files.sort()
print('To export:', len(files), 'PSS file(s)')

for i, src in enumerate(files, 1):
    rel = os.path.relpath(src, ROOT).replace('\\', '/')
    dst = os.path.join(OUT, rel.replace('.PSS', '.mp4').replace('.pss', '.mp4'))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    r = subprocess.run(
        [FFMPEG, '-y', '-v', 'error', '-i', src, '-map', '0:v:0',
         '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-pix_fmt', 'yuv420p', dst],
        capture_output=True, text=True)
    ok = os.path.exists(dst) and os.path.getsize(dst) > 0
    print(f'[{i}/{len(files)}] {rel} -> {"OK" if ok else "FAIL"} {r.stderr.strip()[:120]}')
print('Done')
