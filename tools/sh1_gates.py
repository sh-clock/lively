#!/usr/bin/env python3
"""sh1_gates.py — the regression gates for the SH1 wallpaper port.
Usage: python tools/sh1_gates.py <bundle-dir> (run from the repo root,
after the three gate renders produced wp_a.png + shots/s1.png + shots/s2.png
+ shots/w1.png + shots/w2.png)."""
import sys, os
from PIL import Image

def diff_px(a, b):
    ia = Image.open(a).convert('RGB'); ib = Image.open(b).convert('RGB')
    pa, pb = ia.load(), ib.load()
    return sum(1 for x in range(ia.size[0]) for y in range(ia.size[1])
               if pa[x, y] != pb[x, y])

fails = 0
im = Image.open('wp_a.png').convert('L'); h = im.histogram()
r = sum(h[33:]) / sum(h)
print('gate1 render non-black:', round(r, 4))
if not r > 0.05:
    print('GATE1 FAIL: BLANK RENDER'); fails += 1

d2 = diff_px('shots/s1.png', 'shots/s2.png')
print('gate2 SU0203 motion px:', d2)
if not d2 > 500:
    print('GATE2 FAIL: FROZEN ANIMATION'); fails += 1

d3 = diff_px('shots/w1.png', 'shots/w2.png')
print('gate3 SUFFFE water px:', d3)
if not d3 > 300:
    print('GATE3 FAIL: STILL WATER'); fails += 1

print('ALL GATES PASS' if fails == 0 else f'{fails} GATES FAILED')
sys.exit(1 if fails else 0)
