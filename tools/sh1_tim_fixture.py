#!/usr/bin/env python3
"""sh1_tim_fixture.py — generate a small VALID 4bpp+CLUT PSX .TIM fixture
from the repo's own embedded engine bytes (no CDN fetch, no new binary
blob in git). Feeds the --tim-file viewer gate in CI:

  sh1_fixture.TIM — 8x2 pixel page, 4bpp, 2 CLUT rows (deterministic
  content: a 2-color gradient + a checker row), exactly the container
  tim_load() parses (magic 0x10, flag 0x08, CLUT block, pixel block).
"""
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "sh1_fixture.TIM")

W, H = 8, 2          # pixel page
CW, CH = 16, 2       # CLUT: 16 entries x 2 rows

clut = []
for r in range(CH):
    for c in range(CW):
        if r == 0:
            g5 = (c * 31) // 15 if c < 16 else 0
            rgb = (g5, g5, g5)
        else:
            rgb = (31 - (c * 31) // 15 if c < 16 else 0,) * 3
            rgb = (rgb[0],) * 3
        stp = 1 if c in (0, 15) else 0
        clut.append((stp << 15) | (rgb[2] << 10) | (rgb[1] << 5) | rgb[0])

# pixel data: 4bpp -> 2 pixels per byte; width 8 => pw = 4 (16-bit units)
pix = bytearray()
for y in range(H):
    for x in range(0, W, 2):
        a = (y + x) % 16
        b = (y + x + 1) % 16
        pix.append((b << 4) | a)

clut_bytes = struct.pack("<IHHHH", 12 + CW * CH * 2, 0, 0, CW, CH) + \
    b"".join(struct.pack("<H", v) for v in clut)
pix_bytes = struct.pack("<IHHHH", 12 + len(pix), 0, 0, W // 2, H) + bytes(pix)

data = struct.pack("<II", 0x10, 0x08) + clut_bytes + pix_bytes
open(OUT, "wb").write(data)
print("wrote", OUT, len(data), "bytes (8x2 4bpp, 2 CLUT rows)")
sys.exit(0)
