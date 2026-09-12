#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_docs_i18n.py — keep the bilingual documentation in sync.

The repository ships every document twice: docs/zh/<name>.md and docs/en/<name>.md,
with the SAME ASCII base name. This script verifies that the two sides never drift apart:

  C1  every docs/zh document has a counterpart in docs/en (and vice versa)   [error]
  C2  the numeric tokens of a pair are identical:
        - tier A (hex numbers and integers >= 100) must match exactly        [error]
        - tier B (small integers, decimals, percentages)                   [warning]
        This is the important check: it catches "0x29000 typed as 0x2900"
        and any dropped offset, size or count.
  C3  every relative Markdown link resolves to a real file or directory      [error]
      (inside docs/zh and docs/en, and in the root files README.md,
      README.zh-CN.md and GLOSSARY.md)
  C4  structural counts (headings / table rows / code blocks / list items)   [warning]
      Shown side by side for human review — prose length differs by design.
  C5  every CJK character used in the English document also occurs in the
      Chinese one — catches glyphs mistyped as traditional/Japanese variants
      (e.g. 強 where the source has 强)                                     [error]
  C6  the fenced code blocks keep the same number of lines per block       [warning]
      (catches a translator silently dropping a line out of a script or an
      ASCII structure diagram)

Notes:
  - Chinese "18.8 万" (188,000) and English "188,000" are the same number: the
    checker expands 万 / 亿 notation into plain digits before comparing.

Usage:
  python tools/check_docs_i18n.py [repo-root] [--brief]
      repo-root defaults to the parent directory of the folder holding this script.
      --brief  print only documents that have problems.

Exit code: 0 when there is no ERROR, 1 otherwise. Read-only: no file is modified.

------------------------------------------------------------------------------
中文说明
  中英双语文档靠两条纪律同步：**同名 ASCII 文件名** 与 **数字逐字不变**。
  本脚本的核心是 C2：把两份文档里的所有 `0x…` 与十进制数字抽成集合比对。
  地址、偏移、大小、字节数（hex 与 ≥100 的整数）**必须完全一致**，
  这类错误（例如把 `0x29000` 写成 `0x2900`、漏掉一个 `0x1C03150`）肉眼极难发现，
  但机器一眼就能查出来。小整数与小数（「第一步」↔「Step 1」这类措辞差异）只给警告。
  C4 的结构计数供人工复核：中英行文长度本就不同，计数只作提示。
"""
import os
import re
import sys

# 数字 token：0x… 优先，其次十进制（允许千分位逗号与小数）
NUMBER_RE = re.compile(r'0[xX][0-9A-Fa-f]+|\d[\d,]*(?:\.\d+)?')
WAN_RE = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*[万萬亿億]')
CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
HEX_RE = re.compile(r'^0x', re.I)
LINK_RE = re.compile(r'\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
HEADING_RE = re.compile(r'^(#{1,6})\s')
TABLE_RE = re.compile(r'^\s*\|')
FENCE_RE = re.compile(r'^\s*```')
LIST_RE = re.compile(r'^\s*(?:[-*]|\d+[.)])\s')
PLUS_RE = re.compile(r'^\s*\+\s')          # 只有在前面是空行时才算列表项（否则是换行后的续行）
HEADING_NUM_RE = re.compile(r'^(#{1,6})\s*\d+[.、)]?\s*')       # "## 1. Foo" / "## 1、Foo"
LIST_NUM_RE = re.compile(r'^\s*\d+[.)]\s')                       # "1. foo" 列表序号


def norm_number(tok):
    t = tok.replace(',', '')
    if HEX_RE.match(t):
        return t.lower()
    if re.fullmatch(r'\d+\.\d+', t):
        return t.rstrip('0').rstrip('.') or '0'
    return t


def is_tier_a(tok):
    """hex 或 ≥100 的整数：必须两边一致。"""
    if HEX_RE.match(tok):
        return True
    return tok.isdigit() and int(tok) >= 100


def numbers_of(text):
    """返回 (tierA:set, tierB:set)，已剔除标题编号与有序列表序号。

    「18.8 万」这类中文计数会额外展开成 188000，与英文写法等价。
    """
    a, b = set(), set()
    for line in text.splitlines():
        line = HEADING_NUM_RE.sub(r'\1 ', line)
        line = LIST_NUM_RE.sub('', line)
        for m in WAN_RE.finditer(line):
            mult = 100000000 if m.group(0).strip()[-1] in '亿億' else 10000
            tok = str(int(round(float(m.group(1).replace(',', '')) * mult)))
            (a if is_tier_a(tok) else b).add(tok)
        for m in NUMBER_RE.finditer(line):
            tok = norm_number(m.group(0))
            (a if is_tier_a(tok) else b).add(tok)
    return a, b


def fence_blocks(text):
    """把 ``` 围栏之间的内容按块返回（每块是行列表）。"""
    blocks, cur, inb = [], [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            if inb:
                blocks.append(cur)
                cur, inb = [], False
            else:
                inb = True
            continue
        if inb:
            cur.append(line)
    if inb:
        blocks.append(cur)
    return blocks


def cjk_of(text):
    """文档里出现的汉字集合（用于查「英文版把简体写成了繁体/日文异体」）。"""
    return set(CJK_RE.findall(text))


INLINE_CODE_RE = re.compile(r'`[^`\n]*`')


def links_of(text):
    """抽出相对 Markdown 链接。

    先剥掉围栏代码块与行内代码：文档里会把「链接写法」本身当示例展示
    （例如术语表里 `[05 · Packaging and ISO](05-packaging-and-iso.md)` 这种写法示范），
    那些不该被当成真链接去校验。
    """
    kept, inb = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            inb = not inb
            continue
        if not inb:
            kept.append(INLINE_CODE_RE.sub('', line))
    out = []
    for m in LINK_RE.finditer('\n'.join(kept)):
        target = m.group(1)
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
            continue
        out.append(target.split('#')[0])
    return out


def structure_of(text):
    h = [0] * 6
    rows = fences = items = 0
    prev_blank = True
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            h[len(m.group(1)) - 1] += 1
            prev_blank = True
            continue
        if FENCE_RE.match(line):
            fences += 1
            prev_blank = True
            continue
        if TABLE_RE.match(line):
            rows += 1
            prev_blank = False
            continue
        # 行首的「+ 」在中文里常是「换行折叠后的续行」（如 "…（4，在 +4）\n  + flags…"），
        # 只有前面是空行时才算真正的列表项，否则会误报计数差异。
        if LIST_RE.match(line) or (PLUS_RE.match(line) and prev_blank):
            items += 1
            prev_blank = False
            continue
        prev_blank = not line.strip()
    return dict(h=h, tables=rows, fences=fences, items=items)


def read(path):
    with open(path, 'rb') as f:
        return f.read().decode('utf-8')


def check_root_files(root):
    """仓库根目录三份文件的相对链接也必须可解析（README 的语言切换、GLOSSARY 引用等）。"""
    problems = []
    for name in ('README.md', 'README.zh-CN.md', 'GLOSSARY.md'):
        path = os.path.join(root, name)
        if not os.path.exists(path):
            continue
        text = read(path)
        bad = [t for t in links_of(text)
               if not os.path.exists(os.path.normpath(os.path.join(root, t)))]
        if bad:
            problems.append('C3 broken link in %s: %s' % (name, ', '.join(sorted(set(bad)))))
    return problems


def check_pair(root, base, brief):
    zh = os.path.join(root, 'docs', 'zh', base)
    en = os.path.join(root, 'docs', 'en', base)
    problems, warns = [], []

    if not os.path.exists(en):
        problems.append('C1 English version missing: docs/en/%s' % base)
        return None, problems, warns

    tzh, ten = read(zh), read(en)
    a1, b1 = numbers_of(tzh)
    a2, b2 = numbers_of(ten)

    only_zh, only_en = sorted(a1 - a2), sorted(a2 - a1)
    if only_zh or only_en:
        problems.append('C2 big numbers differ: zh-only %s; en-only %s'
                        % (only_zh or '—', only_en or '—'))

    w1, w2 = sorted(b1 - b2), sorted(b2 - b1)
    if w1 or w2:
        warns.append('C2 small numbers differ: zh-only %s; en-only %s' % (w1 or '—', w2 or '—'))

    zhdir = os.path.dirname(zh)
    endir = os.path.dirname(en)
    for label, text, base_dir in (('zh', tzh, zhdir), ('en', ten, endir)):
        bad = [t for t in links_of(text)
               if not os.path.exists(os.path.normpath(os.path.join(base_dir, t)))]
        if bad:
            problems.append('C3 broken link in %s: %s' % (label, ', '.join(sorted(set(bad)))))

    c1, c2 = cjk_of(tzh), cjk_of(ten)
    extra = sorted(c2 - c1)
    if extra:
        problems.append('C5 English doc uses CJK characters absent from the Chinese one'
                        ' (probably simplified typed as a traditional/Japanese variant): %s'
                        % ''.join(extra))

    s1, s2 = structure_of(tzh), structure_of(ten)
    diffs = []
    for i in range(6):
        if s1['h'][i] != s2['h'][i]:
            diffs.append('H%d %d/%d' % (i + 1, s1['h'][i], s2['h'][i]))
    for k, name in (('tables', 'table rows'), ('fences', 'code fences'), ('items', 'list items')):
        if s1[k] != s2[k]:
            diffs.append('%s %d/%d' % (name, s1[k], s2[k]))
    if diffs:
        warns.append('C4 structure counts differ zh/en: ' + ', '.join(diffs))

    f1, f2 = fence_blocks(tzh), fence_blocks(ten)
    if len(f1) != len(f2):
        warns.append('C6 code block count zh %d / en %d' % (len(f1), len(f2)))
    else:
        for i, (x, y) in enumerate(zip(f1, f2), 1):
            if len(x) != len(y):
                warns.append('C6 code block #%d line count zh %d / en %d' % (i, len(x), len(y)))

    info = dict(base=base,
                lines=(tzh.count('\n') + 1, ten.count('\n') + 1),
                na=(len(a1), len(a2)), nb=(len(b1), len(b2)))

    if not brief or problems or warns:
        print('[%s]  zh %d lines / en %d lines   big numbers %d/%d  small numbers %d/%d'
              % (base, info['lines'][0], info['lines'][1],
                 info['na'][0], info['na'][1], info['nb'][0], info['nb'][1]))
        for p in problems:
            print('      ERROR  ' + p)
        for w in warns:
            print('      WARN   ' + w)
        if not problems and not warns:
            print('      OK     C1/C2/C3/C4 all pass')
    return info, problems, warns


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    brief = '--brief' in argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    root = args[0] if args else os.path.dirname(here)

    zhdir = os.path.join(root, 'docs', 'zh')
    endir = os.path.join(root, 'docs', 'en')
    for d in (zhdir, endir):
        if not os.path.isdir(d):
            raise SystemExit('directory not found: %s' % d)

    zh_bases = sorted(f for f in os.listdir(zhdir) if f.endswith('.md'))
    en_bases = sorted(f for f in os.listdir(endir) if f.endswith('.md'))

    print('repo root: %s' % root)
    print('zh %d docs / en %d docs\n' % (len(zh_bases), len(en_bases)))

    errors = 0
    warns = 0
    for base in zh_bases:
        _, p, w = check_pair(root, base, brief)
        errors += len(p)
        warns += len(w)
    for base in en_bases:
        if base not in zh_bases:
            print('[%s]' % base)
            print('      ERROR  C1 Chinese version missing: docs/zh/%s' % base)
            errors += 1

    root_problems = check_root_files(root)
    if root_problems:
        print('[root files]')
        for p in root_problems:
            print('      ERROR  ' + p)
        errors += len(root_problems)

    print('\nsummary: %d ERROR(s), %d WARN(s)' % (errors, warns))
    if errors:
        print('ERRORs must be fixed (especially C2: mismatched numbers/addresses mean the docs are wrong).')
    else:
        print('no ERROR: document sets, numbers (hex and integers >= 100) and links are all in sync.')
    return 1 if errors else 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main(sys.argv))
