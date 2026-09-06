# -*- coding: utf-8 -*-
"""把目录下全部 PSS 转成 MP4（视频轨，H.264 crf18；音频是 PS2 ADPCM 暂不封装）。"""
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
print('待导出:', len(files), '个')

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
print('完成')
