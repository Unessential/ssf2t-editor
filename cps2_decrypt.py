#!/usr/bin/env python3
"""
cps2_decrypt.py - standalone CPS-2 68000 program ROM decryptor / encryptor.

Ported from MAME's src/mame/capcom/cps2crypt.cpp (BSD-3-Clause; algorithm by
Andreas Naive, original code by Nicola Salmoria et al.) and the key decoding in
cps2.cpp (init_cps2crypt); see THIRD_PARTY_NOTICES.md for the license.
Use it only with ROMs you legally own.

IMPORTANT - what "decrypt" means on CPS-2
-----------------------------------------
Only OPCODE fetches are encrypted; data reads are plain. The ROM therefore holds
a mix: code words are ciphertext, data words (tables, pointers) are plain.
"Opcode fetches" includes everything the 68000 reads through its instruction
stream: the instruction words, their immediate operands / absolute addresses /
displacements, and even the reset vectors (initial SP and PC at address 0). Decrypting every word gives you a view that is correct for code and
garbage for data. This script writes:

  <out>_data.bin     raw ROM, 68k byte order  (correct for data, code still encrypted)
  <out>_opcodes.bin  every word decrypted     (correct for code, garbage for data)
  <out>_merged.bin   optional: opcode view inside --code-ranges, raw view elsewhere

Ranges for the merged image come from you (e.g. addresses an MAME trace shows
being executed). Nothing here can tell code from data automatically.

Usage
-----
  # easiest: drop this script into the folder with the extracted ROM files
  # (or next to the ssf2t.zip) and run it with no arguments
  python3 cps2_decrypt.py

  # manual: concatenate the program ROMs in load order, byte-swap to 68k order, decrypt
  python3 cps2_decrypt.py decrypt --key ssf2t.key --out ssf2t \\
      sfxe.03c sfxe.04a sfxe.05 sfxe.06a sfxe.07 sfxe.08 sfx.09

  # re-encrypt edited code (only the byte ranges you changed)
  python3 cps2_decrypt.py encrypt --key ssf2t.key --out patched.bin \\
      --ranges 0x1000-0x1100 edited_opcodes.bin     # input is big-endian (68k order)

decrypt: input files are assumed to be as in the MAME zip (16-bit words
byte-swapped relative to the 68k); use --no-swap if already in 68k order.
encrypt: input is assumed big-endian (use --swap otherwise).
Outputs are always 68k (big-endian) order.
"""
import argparse
import os
import sys
import zlib
import zipfile
import numpy as np

# ---------------------------------------------------------------------------
# S-box tables, extracted mechanically from MAME's cps2crypt.cpp
# each entry: (64-entry table, 6 input bit positions (-1 = key only), 2 output bits)
# ---------------------------------------------------------------------------
SBOXES = {
    'fn1_r1': [
        ([0, 2, 2, 0, 1, 0, 1, 1, 3, 2, 0, 3, 0, 3, 1, 2, 1, 1, 1, 2, 1, 3, 2, 2, 2, 3, 3, 2, 1, 1, 1, 2, 2, 2, 0, 0, 3, 1, 3, 1, 1, 1, 3, 0, 0, 1, 0, 0, 1, 2, 2, 1, 2, 3, 2, 2, 2, 3, 1, 3, 2, 0, 1, 3],
         [3, 4, 5, 6, -1, -1], [3, 6]),
        ([3, 0, 2, 2, 2, 1, 1, 1, 1, 2, 1, 0, 0, 0, 2, 3, 2, 3, 1, 3, 0, 0, 0, 2, 1, 2, 2, 3, 0, 3, 3, 3, 0, 1, 3, 2, 3, 3, 3, 1, 1, 1, 1, 2, 0, 1, 2, 1, 3, 2, 3, 1, 1, 3, 2, 2, 2, 3, 1, 3, 2, 3, 0, 0],
         [0, 1, 2, 4, 7, -1], [2, 7]),
        ([3, 0, 3, 1, 1, 0, 2, 2, 3, 1, 2, 0, 3, 3, 2, 3, 0, 1, 0, 1, 2, 3, 0, 2, 0, 2, 0, 1, 0, 0, 1, 0, 2, 3, 1, 2, 1, 0, 2, 0, 2, 1, 0, 1, 0, 2, 1, 0, 3, 1, 2, 3, 1, 3, 1, 1, 1, 2, 0, 2, 2, 0, 0, 0],
         [0, 1, 2, 3, 6, 7], [0, 1]),
        ([3, 2, 0, 3, 0, 2, 2, 1, 1, 2, 3, 2, 1, 3, 2, 1, 2, 2, 1, 3, 3, 2, 1, 0, 1, 0, 1, 3, 0, 0, 0, 2, 2, 1, 0, 1, 0, 1, 0, 1, 3, 1, 1, 2, 2, 3, 2, 0, 3, 3, 2, 0, 2, 1, 3, 3, 0, 0, 3, 0, 1, 1, 3, 3],
         [0, 1, 3, 5, 6, 7], [4, 5]),
    ],
    'fn1_r2': [
        ([3, 3, 2, 0, 3, 0, 3, 1, 0, 3, 0, 1, 0, 2, 1, 3, 1, 3, 0, 3, 3, 1, 3, 3, 3, 2, 3, 2, 2, 3, 1, 2, 0, 2, 2, 1, 0, 1, 2, 0, 3, 3, 0, 1, 3, 2, 1, 2, 3, 0, 1, 3, 0, 1, 2, 2, 1, 2, 1, 2, 0, 1, 3, 0],
         [0, 1, 2, 3, 6, -1], [1, 6]),
        ([1, 2, 3, 2, 1, 3, 0, 1, 1, 0, 2, 0, 0, 2, 3, 2, 3, 3, 0, 1, 2, 2, 1, 0, 1, 0, 1, 2, 3, 2, 1, 3, 2, 2, 2, 0, 1, 0, 2, 3, 2, 1, 2, 1, 2, 1, 0, 3, 0, 1, 2, 3, 1, 2, 1, 3, 2, 0, 3, 2, 3, 0, 2, 0],
         [2, 4, 5, 6, 7, -1], [5, 7]),
        ([0, 1, 0, 2, 1, 1, 0, 1, 0, 2, 2, 2, 1, 3, 0, 0, 1, 1, 3, 1, 2, 2, 2, 3, 1, 0, 3, 3, 3, 2, 2, 2, 1, 1, 3, 0, 3, 1, 3, 0, 1, 3, 3, 2, 1, 1, 0, 0, 1, 2, 2, 2, 1, 1, 1, 2, 2, 0, 0, 3, 2, 3, 1, 3],
         [1, 2, 3, 4, 5, 7], [0, 3]),
        ([2, 1, 0, 3, 3, 3, 2, 0, 1, 2, 1, 1, 1, 0, 3, 1, 1, 3, 3, 0, 1, 2, 1, 0, 0, 0, 3, 0, 3, 0, 3, 0, 1, 3, 3, 3, 0, 3, 2, 0, 2, 1, 2, 2, 2, 1, 1, 3, 0, 1, 0, 1, 0, 1, 1, 1, 1, 3, 1, 0, 1, 2, 3, 3],
         [0, 1, 3, 4, 6, 7], [2, 4]),
    ],
    'fn1_r3': [
        ([0, 0, 0, 3, 3, 1, 1, 0, 2, 0, 2, 0, 0, 0, 3, 2, 0, 1, 2, 3, 2, 2, 1, 0, 3, 0, 0, 0, 0, 0, 2, 3, 3, 0, 0, 1, 1, 2, 3, 3, 0, 1, 3, 2, 0, 1, 3, 3, 2, 0, 0, 1, 0, 2, 0, 0, 0, 3, 1, 3, 3, 3, 3, 3],
         [0, 1, 5, 6, 7, -1], [0, 5]),
        ([2, 3, 2, 3, 0, 2, 3, 0, 2, 2, 3, 0, 3, 2, 0, 2, 1, 0, 2, 3, 1, 1, 1, 0, 0, 1, 0, 2, 1, 2, 2, 1, 3, 0, 2, 1, 2, 3, 3, 0, 3, 2, 3, 1, 0, 2, 1, 0, 1, 2, 2, 3, 0, 2, 1, 3, 1, 3, 0, 2, 1, 1, 1, 3],
         [2, 3, 4, 6, 7, -1], [6, 7]),
        ([3, 0, 2, 1, 1, 3, 1, 2, 2, 1, 2, 2, 2, 0, 0, 1, 2, 3, 1, 0, 2, 0, 0, 2, 3, 1, 2, 0, 0, 0, 3, 0, 2, 1, 1, 2, 0, 0, 1, 2, 3, 1, 1, 2, 0, 1, 3, 0, 3, 1, 1, 0, 0, 2, 3, 0, 0, 0, 0, 3, 2, 0, 0, 0],
         [0, 2, 3, 4, 5, 6], [1, 4]),
        ([0, 1, 0, 0, 2, 1, 3, 2, 3, 3, 2, 1, 0, 1, 1, 1, 1, 1, 0, 3, 3, 1, 1, 0, 0, 2, 2, 1, 0, 3, 3, 2, 1, 3, 3, 0, 3, 0, 2, 1, 1, 2, 3, 2, 2, 2, 1, 0, 0, 3, 3, 3, 2, 2, 3, 1, 0, 2, 3, 0, 3, 1, 1, 0],
         [0, 1, 2, 3, 5, 7], [2, 3]),
    ],
    'fn1_r4': [
        ([1, 1, 1, 1, 1, 0, 1, 3, 3, 2, 3, 0, 1, 2, 0, 2, 3, 3, 0, 1, 2, 1, 2, 3, 0, 3, 2, 3, 2, 0, 1, 2, 0, 1, 0, 3, 2, 1, 3, 2, 3, 1, 2, 3, 2, 0, 1, 2, 2, 0, 0, 0, 2, 1, 3, 0, 3, 1, 3, 0, 1, 3, 3, 0],
         [1, 2, 3, 4, 5, 7], [0, 4]),
        ([3, 0, 0, 0, 0, 1, 0, 2, 3, 3, 1, 3, 0, 3, 1, 2, 2, 2, 3, 1, 0, 0, 2, 0, 1, 0, 2, 2, 3, 3, 0, 0, 1, 1, 3, 0, 2, 3, 0, 3, 0, 3, 0, 2, 0, 2, 0, 1, 0, 3, 0, 1, 3, 1, 1, 0, 0, 1, 3, 3, 2, 2, 1, 0],
         [0, 1, 2, 3, 5, 6], [1, 3]),
        ([0, 1, 1, 2, 0, 1, 3, 1, 2, 0, 3, 2, 0, 0, 3, 0, 3, 0, 1, 2, 2, 3, 3, 2, 3, 2, 0, 1, 0, 0, 1, 0, 3, 0, 2, 3, 0, 2, 2, 2, 1, 1, 0, 2, 2, 0, 0, 1, 2, 1, 1, 1, 2, 3, 0, 3, 1, 2, 3, 3, 1, 1, 3, 0],
         [0, 2, 4, 5, 6, 7], [2, 6]),
        ([0, 1, 2, 2, 0, 1, 0, 3, 2, 2, 1, 1, 3, 2, 0, 2, 0, 1, 3, 3, 0, 2, 2, 3, 3, 2, 0, 0, 2, 1, 3, 3, 1, 1, 1, 3, 1, 2, 1, 1, 0, 3, 3, 2, 3, 2, 3, 0, 3, 1, 0, 0, 3, 0, 0, 0, 2, 2, 2, 1, 2, 3, 0, 0],
         [0, 1, 3, 4, 6, 7], [5, 7]),
    ],
    'fn2_r1': [
        ([2, 0, 2, 0, 3, 0, 0, 3, 1, 1, 0, 1, 3, 2, 0, 1, 2, 0, 1, 2, 0, 2, 0, 2, 2, 2, 3, 0, 2, 1, 3, 0, 0, 1, 0, 1, 2, 2, 3, 3, 0, 3, 0, 2, 3, 0, 1, 2, 1, 1, 0, 2, 0, 3, 1, 1, 2, 2, 1, 3, 1, 1, 3, 1],
         [0, 3, 4, 5, 7, -1], [6, 7]),
        ([1, 1, 0, 3, 0, 2, 0, 1, 3, 0, 2, 0, 1, 1, 0, 0, 1, 3, 2, 2, 0, 2, 2, 2, 2, 0, 1, 3, 3, 3, 1, 1, 1, 3, 1, 3, 2, 2, 2, 2, 2, 2, 0, 1, 0, 1, 1, 2, 3, 1, 1, 2, 0, 3, 3, 3, 2, 2, 3, 1, 1, 1, 3, 0],
         [1, 2, 3, 4, 6, -1], [3, 5]),
        ([1, 0, 2, 2, 3, 3, 3, 3, 1, 2, 2, 1, 0, 1, 2, 1, 1, 2, 3, 1, 2, 0, 0, 1, 2, 3, 1, 2, 0, 0, 0, 2, 2, 0, 1, 1, 0, 0, 2, 0, 0, 0, 2, 3, 2, 3, 0, 1, 3, 0, 0, 0, 2, 3, 2, 0, 1, 3, 2, 1, 3, 1, 1, 3],
         [1, 2, 4, 5, 6, 7], [1, 4]),
        ([1, 3, 3, 0, 3, 2, 3, 1, 3, 2, 1, 1, 3, 3, 2, 1, 2, 3, 0, 3, 1, 0, 0, 2, 3, 0, 0, 0, 3, 3, 0, 1, 2, 3, 0, 0, 0, 1, 2, 1, 3, 0, 0, 1, 0, 2, 2, 2, 3, 3, 1, 2, 1, 3, 0, 0, 0, 3, 0, 1, 3, 2, 2, 0],
         [0, 2, 3, 5, 6, 7], [0, 2]),
    ],
    'fn2_r2': [
        ([3, 1, 3, 0, 3, 0, 3, 1, 3, 0, 0, 1, 1, 3, 0, 3, 1, 1, 0, 1, 2, 3, 2, 3, 3, 1, 2, 2, 2, 0, 2, 3, 2, 2, 2, 1, 1, 3, 3, 0, 3, 1, 2, 1, 1, 1, 0, 2, 0, 3, 3, 0, 0, 2, 0, 0, 1, 1, 2, 1, 2, 1, 1, 0],
         [0, 2, 4, 6, -1, -1], [4, 6]),
        ([0, 3, 0, 3, 3, 2, 1, 2, 3, 1, 1, 1, 2, 0, 2, 3, 0, 3, 1, 2, 2, 1, 3, 3, 3, 2, 1, 2, 2, 0, 1, 0, 2, 3, 0, 1, 2, 0, 1, 1, 2, 0, 2, 1, 2, 0, 2, 3, 3, 1, 0, 2, 3, 3, 0, 3, 1, 1, 3, 0, 0, 1, 2, 0],
         [1, 3, 4, 5, 6, 7], [0, 3]),
        ([0, 0, 2, 1, 3, 2, 1, 0, 1, 2, 2, 2, 1, 1, 0, 3, 1, 2, 2, 3, 2, 1, 1, 0, 3, 0, 0, 1, 1, 2, 3, 1, 3, 3, 2, 2, 1, 0, 1, 1, 1, 2, 0, 1, 2, 3, 0, 3, 3, 0, 3, 2, 2, 0, 2, 2, 1, 2, 3, 2, 1, 0, 2, 1],
         [0, 1, 3, 4, 5, 7], [1, 7]),
        ([0, 2, 1, 2, 0, 2, 2, 0, 1, 3, 2, 0, 3, 2, 3, 0, 3, 3, 2, 3, 1, 2, 3, 1, 2, 2, 0, 0, 2, 2, 1, 2, 2, 3, 3, 3, 1, 1, 0, 0, 0, 3, 2, 0, 3, 2, 3, 1, 1, 1, 1, 0, 1, 0, 1, 3, 0, 0, 1, 2, 2, 3, 2, 0],
         [1, 2, 3, 5, 6, 7], [2, 5]),
    ],
    'fn2_r3': [
        ([2, 1, 2, 1, 2, 3, 1, 3, 2, 2, 1, 3, 3, 0, 0, 1, 0, 2, 0, 3, 3, 1, 0, 0, 1, 1, 0, 2, 3, 2, 1, 2, 1, 1, 2, 1, 1, 3, 2, 2, 0, 2, 2, 3, 3, 3, 2, 0, 0, 0, 0, 0, 3, 3, 3, 0, 1, 2, 1, 0, 2, 3, 3, 1],
         [2, 3, 4, 6, -1, -1], [3, 5]),
        ([3, 2, 3, 3, 1, 0, 3, 0, 2, 0, 1, 1, 1, 0, 3, 0, 3, 1, 3, 1, 0, 1, 2, 3, 2, 2, 3, 2, 0, 1, 1, 2, 3, 0, 0, 2, 1, 0, 0, 2, 2, 0, 1, 0, 0, 2, 0, 0, 1, 3, 1, 3, 2, 0, 3, 3, 1, 0, 2, 2, 2, 3, 0, 0],
         [0, 1, 3, 5, 7, -1], [0, 2]),
        ([2, 2, 1, 0, 2, 3, 3, 0, 0, 0, 1, 3, 1, 2, 3, 2, 2, 3, 1, 3, 0, 3, 0, 3, 3, 2, 2, 1, 0, 0, 0, 2, 1, 2, 2, 2, 0, 0, 1, 2, 0, 1, 3, 0, 2, 3, 2, 1, 3, 2, 2, 2, 3, 1, 3, 0, 2, 0, 2, 1, 0, 3, 3, 1],
         [0, 1, 2, 3, 5, 7], [1, 6]),
        ([1, 2, 3, 2, 0, 2, 1, 3, 3, 1, 0, 1, 1, 2, 2, 0, 0, 1, 1, 1, 2, 1, 1, 2, 0, 1, 3, 3, 1, 1, 1, 2, 3, 3, 1, 0, 2, 1, 1, 1, 2, 1, 0, 0, 2, 2, 3, 2, 3, 2, 2, 0, 2, 2, 3, 3, 0, 2, 3, 0, 2, 2, 1, 1],
         [0, 2, 4, 5, 6, 7], [4, 7]),
    ],
    'fn2_r4': [
        ([2, 0, 1, 1, 2, 1, 3, 3, 1, 1, 1, 2, 0, 1, 0, 2, 0, 1, 2, 0, 2, 3, 0, 2, 3, 3, 2, 2, 3, 2, 0, 1, 3, 0, 2, 0, 2, 3, 1, 3, 2, 0, 0, 1, 1, 2, 3, 1, 1, 1, 0, 1, 2, 0, 3, 3, 1, 1, 1, 3, 3, 1, 1, 0],
         [0, 1, 3, 6, 7, -1], [0, 3]),
        ([1, 2, 2, 1, 0, 3, 3, 1, 0, 2, 2, 2, 1, 0, 1, 0, 1, 1, 0, 1, 0, 2, 1, 0, 2, 1, 0, 2, 3, 2, 3, 3, 2, 2, 1, 2, 2, 3, 1, 3, 3, 3, 0, 1, 0, 1, 3, 0, 0, 0, 1, 2, 0, 3, 3, 2, 3, 2, 1, 3, 2, 1, 0, 2],
         [0, 1, 2, 4, 5, 6], [4, 7]),
        ([2, 3, 2, 1, 3, 2, 3, 0, 0, 2, 1, 1, 0, 0, 3, 2, 3, 1, 0, 1, 2, 2, 2, 1, 3, 2, 2, 1, 0, 2, 1, 2, 0, 3, 1, 0, 0, 3, 1, 1, 3, 3, 2, 0, 1, 0, 1, 3, 0, 0, 1, 2, 1, 2, 3, 2, 1, 0, 0, 3, 2, 1, 1, 3],
         [0, 2, 3, 4, 5, 7], [1, 2]),
        ([2, 0, 0, 3, 2, 2, 2, 1, 3, 3, 1, 1, 2, 0, 0, 3, 1, 0, 3, 2, 1, 0, 2, 0, 3, 2, 2, 3, 2, 0, 3, 0, 1, 3, 0, 2, 2, 1, 3, 3, 0, 1, 0, 3, 1, 1, 3, 2, 0, 3, 0, 2, 3, 2, 1, 3, 2, 3, 0, 0, 1, 3, 2, 1],
         [2, 3, 4, 5, 6, 7], [5, 6]),
    ],
}

GROUP_A1 = [10, 4, 6, 7, 2, 13, 15, 14]
GROUP_B1 = [0, 1, 3, 5, 8, 9, 11, 12]
GROUP_A2 = [6, 0, 2, 13, 1, 4, 14, 7]
GROUP_B2 = [3, 5, 9, 10, 8, 15, 12, 11]

KEY1_BITS = [
    33, 58, 49, 36,  0, 31, 22, 30,  3, 16,  5, 53, 10, 41, 23, 19,
    27, 39, 43,  6, 34, 12, 61, 21, 48, 13, 32, 35,  6, 42, 43, 14,
    21, 41, 52, 25, 18, 47, 46, 37, 57, 53, 20,  8, 55, 54, 59, 60,
    27, 33, 35, 18,  8, 15, 63,  1, 50, 44, 16, 46,  5,  4, 45, 51,
    38, 25, 13, 11, 62, 29, 48,  2, 59, 61, 62, 56, 51, 57, 54,  9,
    24, 63, 22,  7, 26, 42, 45, 40, 23, 14,  2, 31, 52, 28, 44, 17,
]
KEY2_BITS = [
    34,  9, 32, 24, 44, 54, 38, 61, 47, 13, 28,  7, 29, 58, 18,  1,
    20, 60, 15,  6, 11, 43, 39, 19, 63, 23, 16, 62, 54, 40, 31,  3,
    56, 61, 17, 25, 47, 38, 55, 57,  5,  4, 15, 42, 22,  7,  2, 19,
    46, 37, 29, 39, 12, 30, 49, 57, 31, 41, 26, 27, 24, 36, 11, 63,
    33, 16, 56, 62, 48, 60, 59, 32, 12, 30, 53, 48, 10,  0, 50, 35,
     3, 59, 14, 49, 51, 45, 44,  2, 21, 33, 55, 52, 23, 28,  8, 26,
]
SUBKEY_BITS = [
     5, 10, 14,  9,  4,  0, 15,  6,  1,  8,  3,  2, 12,  7, 13, 11,
     5, 12,  7,  2, 13, 11,  9, 14,  4,  1,  6, 10,  8,  0, 15,  3,
     4, 10,  2,  0,  6,  9, 12,  1, 11,  7, 15,  8, 13,  5, 14,  3,
    14, 11, 12,  7,  4,  5,  2, 10,  1, 15,  0,  9,  8,  6, 13,  3,
]

# (shift, bit-to-copy, destination-bit) fix-ups for S-boxes with < 6 inputs
KEY1_FIX = [(0, 1, 4), (0, 2, 5), (0, 8, 11), (1, 0, 5), (1, 8, 11), (2, 1, 5), (2, 8, 11)]
KEY2_FIX = [(0, 0, 5), (0, 6, 11), (1, 0, 5), (1, 1, 4), (2, 2, 5), (2, 3, 4), (2, 7, 11), (3, 1, 5)]


def _optimise(boxes):
    """-> list of (input_lookup[256], output[64]) as uint8 arrays"""
    res = []
    for table, inputs, outputs in boxes:
        lookup = np.zeros(256, np.uint8)
        for v in range(256):
            r = 0
            for i, pos in enumerate(inputs):
                if pos >= 0:
                    r |= ((v >> pos) & 1) << i
            lookup[v] = r
        out = np.zeros(64, np.uint8)
        for i, o in enumerate(table):
            m = 0
            if o & 1:
                m |= 1 << outputs[0]
            if o & 2:
                m |= 1 << outputs[1]
            out[i] = m
        res.append((lookup, out))
    return res


def _rounds(prefix):
    return [_optimise(SBOXES['%s_r%d' % (prefix, r)]) for r in (1, 2, 3, 4)]


ROUNDS1 = _rounds('fn1')
ROUNDS2 = _rounds('fn2')


def _fn(x, boxes, key):
    out = np.zeros_like(x, dtype=np.uint8)
    for n, (lookup, outtab) in enumerate(boxes):
        k = ((key >> (6 * n)) & 0x3F).astype(np.uint8)
        out |= outtab[lookup[x] ^ k]
    return out


def _pack(val, bits):
    r = np.zeros(val.shape, np.uint8)
    for k in range(8):
        r |= (((val >> bits[k]) & 1).astype(np.uint8) << k)
    return r


def _unpack(x, bits):
    r = np.zeros(x.shape, np.uint16)
    for k in range(8):
        r |= (((x >> k) & 1).astype(np.uint16) << bits[k])
    return r


def _u32(v, like):
    return np.broadcast_to(np.asarray(v, np.uint32), like.shape)


def feistel(val, bitsA, bitsB, rounds, keys):
    val = val.astype(np.uint16)
    l = _pack(val, bitsB)
    r = _pack(val, bitsA)
    l ^= _fn(r, rounds[0], _u32(keys[0], val))
    r ^= _fn(l, rounds[1], _u32(keys[1], val))
    l ^= _fn(r, rounds[2], _u32(keys[2], val))
    r ^= _fn(l, rounds[3], _u32(keys[3], val))
    return _unpack(l, bitsA) | _unpack(r, bitsB)


def feistel_inv(val, bitsA, bitsB, rounds, keys):
    val = val.astype(np.uint16)
    l = _pack(val, bitsA)
    r = _pack(val, bitsB)
    r ^= _fn(l, rounds[3], _u32(keys[3], val))
    l ^= _fn(r, rounds[2], _u32(keys[2], val))
    r ^= _fn(l, rounds[1], _u32(keys[1], val))
    l ^= _fn(r, rounds[0], _u32(keys[0], val))
    return _unpack(l, bitsB) | _unpack(r, bitsA)


def decode_key(keydata):
    """20-byte .key file -> (master_key[2], lower, upper) exactly as MAME's init_cps2crypt"""
    if len(keydata) < 20:
        raise ValueError('key file must be 20 bytes (got %d)' % len(keydata))
    decoded = [0] * 10
    for b in range(160):
        bit = (317 - b) % 160
        if (keydata[bit // 8] >> ((bit ^ 7) % 8)) & 1:
            decoded[b // 16] |= 0x8000 >> (b % 16)
    master = [(decoded[0] << 16) | decoded[1], (decoded[2] << 16) | decoded[3]]
    if decoded[9] == 0xFFFF:       # "dead board" key
        upper, lower = 0xFFFFFF, 0xFF0000
    else:
        upper = (((~decoded[9] & 0x3FF) << 14) | 0x3FFF) + 1
        lower = 0
    return master, lower, upper


def build_word_keys(master):
    """Second-network key for each of the 65536 possible (address & 0xffff) values."""
    # first network key (scalars)
    k1 = [0, 0, 0, 0]
    for i, b in enumerate(KEY1_BITS):
        k1[i // 24] |= ((master[b // 32] >> (b % 32)) & 1) << (i % 24)
    for w, src, dst in KEY1_FIX:
        k1[w] ^= ((k1[w] >> src) & 1) << dst

    addr = np.arange(0x10000, dtype=np.uint16)
    seed = feistel(addr, GROUP_A1, GROUP_B1, ROUNDS1, k1)

    sub = [np.zeros(0x10000, np.uint32), np.zeros(0x10000, np.uint32)]
    for i, b in enumerate(SUBKEY_BITS):
        sub[i // 32] |= ((seed >> b) & 1).astype(np.uint32) << (i % 32)
    sub[0] ^= np.uint32(master[0])
    sub[1] ^= np.uint32(master[1])

    k2 = [np.zeros(0x10000, np.uint32) for _ in range(4)]
    for i, b in enumerate(KEY2_BITS):
        k2[i // 24] |= ((sub[b // 32] >> (b % 32)) & 1) << (i % 24)
    for w, src, dst in KEY2_FIX:
        k2[w] ^= ((k2[w] >> src) & 1) << dst
    return k2


def _transform(words, keyfile, encrypt, byte_ranges=None):
    master, lower, upper = decode_key(keyfile)
    k2 = build_word_keys(master)
    n = len(words)
    a = np.arange(n, dtype=np.uint32)
    idx = a & 0xFFFF
    keys = [k[idx] for k in k2]
    in_range = (a >= lower // 2) & (a <= upper // 2)
    if byte_ranges is not None:
        sel = np.zeros(n, bool)
        for lo, hi in byte_ranges:
            sel[lo // 2:hi // 2 + 1] = True
        in_range &= sel
    out = words.copy()
    f = feistel_inv if encrypt else feistel
    out[in_range] = f(words[in_range], GROUP_A2, GROUP_B2, ROUNDS2,
                      [k[in_range] for k in keys])
    return out, master, lower, upper


def parse_ranges(text):
    res = []
    for part in text.split(','):
        part = part.strip()
        if not part:
            continue
        lo, hi = part.split('-')
        lo, hi = int(lo, 0), int(hi, 0)
        if lo > hi:
            raise ValueError('bad range %s' % part)
        res.append((lo, hi))
    return res


def load_words(paths, swap):
    data = b''.join(open(p, 'rb').read() for p in paths)
    if len(data) % 2:
        raise ValueError('input length is odd')
    if swap:
        w = np.frombuffer(data, '<u2')      # file order is byte-swapped vs the 68k
    else:
        w = np.frombuffer(data, '>u2')
    return w.astype(np.uint16)


def save_words(path, words):
    with open(path, 'wb') as f:
        f.write(words.astype('>u2').tobytes())


# ---------------------------------------------------------------------------
# Known Super Street Fighter II Turbo sets (names / CRCs from MAME cps2.cpp):
#   set -> (description, key file, [(program ROM file, crc32), ...] in load order)
# Each ROM is 0x80000 bytes and they load back to back from address 0.
# ---------------------------------------------------------------------------
KNOWN_SETS = {
    'ssf2t': ('SSF2T (World 940223)', 'ssf2t.key', [
        ('sfxe.03c', 0x2fa1f396),
        ('sfxe.04a', 0xd0bc29c6),
        ('sfxe.05', 0x65222964),
        ('sfxe.06a', 0x8fe9f531),
        ('sfxe.07', 0x8a7d0cb6),
        ('sfxe.08', 0x74c24062),
        ('sfx.09', 0x642fae3f),
    ]),
    'ssf2tu': ('SSF2T (USA 940323)', 'ssf2tu.key', [
        ('sfxu.03e', 0xd6ff689e),
        ('sfxu.04a', 0x532b5ffd),
        ('sfxu.05', 0xffa3c6de),
        ('sfxu.06b', 0x83f9382b),
        ('sfxu.07a', 0x6ab673e8),
        ('sfxu.08', 0xb3c71810),
        ('sfx.09', 0x642fae3f),
    ]),
    'ssf2tur1': ('SSF2T (USA 940223)', 'ssf2tu.key', [
        ('sfxu.03c', 0x86e4a335),
        ('sfxu.04a', 0x532b5ffd),
        ('sfxu.05', 0xffa3c6de),
        ('sfxu.06a', 0xe4c04c99),
        ('sfxu.07', 0xd8199e41),
        ('sfxu.08', 0xb3c71810),
        ('sfx.09', 0x642fae3f),
    ]),
    'ssf2ta': ('SSF2T (Asia 940223)', 'ssf2ta.key', [
        ('sfxa.03c', 0x04b9ff34),
        ('sfxa.04a', 0x16ea5f7a),
        ('sfxa.05', 0x53d61f0c),
        ('sfxa.06a', 0x066d09b5),
        ('sfxa.07', 0xa428257b),
        ('sfxa.08', 0x39be596c),
        ('sfx.09', 0x642fae3f),
    ]),
    'ssf2th': ('SSF2T (Hispanic 940223)', 'ssf2th.key', [
        ('sfxh.03c', 0xfbe80dfe),
        ('sfxh.04a', 0xef9dd4b1),
        ('sfxh.05', 0x09e56ecc),
        ('sfxh.06a', 0xe6f210be),
        ('sfxh.07', 0x900ba1a4),
        ('sfxh.08', 0xc15f0424),
        ('sfxh.09', 0x5b92b3f9),
    ]),
    'ssf2xj': ('Super Street Fighter II X: Grand Master Challenge (Japan 940311)', 'ssf2xj.key', [
        ('sfxj.03d', 0x50b52b37),
        ('sfxj.04a', 0xaf7767b4),
        ('sfxj.05', 0xf4ff18f5),
        ('sfxj.06b', 0x413477c2),
        ('sfxj.07a', 0xa18b3d83),
        ('sfxj.08', 0x2de76f10),
        ('sfx.09', 0x642fae3f),
    ]),
    'ssf2xjr1': ('Super Street Fighter II X: Grand Master Challenge (Japan 940223)', 'ssf2xj.key', [
        ('sfxj.03c', 0xa7417b79),
        ('sfxj.04a', 0xaf7767b4),
        ('sfxj.05', 0xf4ff18f5),
        ('sfxj.06a', 0x260d0370),
        ('sfxj.07', 0x1324d02a),
        ('sfxj.08', 0x2de76f10),
        ('sfx.09', 0x642fae3f),
    ]),
    'ssf2xjr1r': ('Super Street Fighter II X: Grand Master Challenge (Japan 940223 rent version)', 'ssf2xjr1r.key', [
        ('sfxo.03c', 0x2ba33dc6),
        ('sfxo.04a', 0xba663dd7),
        ('sfxo.05', 0x1321625c),
        ('sfxo.06a', 0x0cc490ed),
        ('sfxo.07', 0x64b9015e),
        ('sfxo.08', 0xb60f4b58),
        ('sfxo.09', 0x642fae3f),
    ]),
}


# CRC32 of the 20-byte key files, from MAME
KEY_CRCS = {
    'ssf2t.key': 0x524d608e,
    'ssf2tu.key': 0xf7d62def,
    'ssf2ta.key': 0xc11fa8e9,
    'ssf2th.key': 0xf6ce6a35,
    'ssf2xj.key': 0x160d1424,
    'ssf2xjr1r.key': 0x82c86e63,
}


class FileSource:
    """Finds files by name (case-insensitive) in loose files first, then inside .zip files."""

    def __init__(self, folders):
        self.loose, self.zipped, self.folders = {}, {}, folders
        for folder in folders:
            try:
                entries = sorted(os.listdir(folder))
            except OSError:
                continue
            for e in entries:
                p = os.path.join(folder, e)
                if os.path.isfile(p):
                    self.loose.setdefault(e.lower(), p)
                    if e.lower().endswith('.zip'):
                        try:
                            with zipfile.ZipFile(p) as z:
                                for m in z.namelist():
                                    base = os.path.basename(m).lower()
                                    if base:
                                        self.zipped.setdefault(base, (p, m))
                        except zipfile.BadZipFile:
                            pass

    def has(self, name):
        n = name.lower()
        return n in self.loose or n in self.zipped

    def read(self, name):
        n = name.lower()
        if n in self.loose:
            return open(self.loose[n], 'rb').read()
        zpath, member = self.zipped[n]
        with zipfile.ZipFile(zpath) as z:
            return z.read(member)

    def where(self, name):
        n = name.lower()
        return self.loose[n] if n in self.loose else '%s:%s' % self.zipped[n]


def auto_decrypt(folders, wanted_set=None, order='auto'):
    src = FileSource(folders)
    candidates = []
    for setname, (desc, keyname, roms) in KNOWN_SETS.items():
        if wanted_set and setname != wanted_set:
            continue
        if src.has(keyname) and all(src.has(r) for r, _ in roms):
            candidates.append(setname)
    if not candidates:
        print('Could not find a complete Super Street Fighter II Turbo program ROM set.')
        print('Looked in:')
        for f in folders:
            print('  ', f)
        print('Each set needs its key file plus 7 program ROMs, loose or inside the .zip. For example')
        print('the World set needs ssf2t.key, sfxe.03c, sfxe.04a, sfxe.05, sfxe.06a, sfxe.07,')
        print('sfxe.08 and sfx.09. (ssf2t.key is inside MAME\'s ssf2t.zip.)')
        print('Other games / odd filenames: use  decrypt --key K --out PREFIX ROM...  (see --help).')
        return 1
    if len(candidates) > 1:
        print('Several sets are present: %s - using %s (pick another with --set).' % (', '.join(candidates), candidates[0]))
    setname = candidates[0]
    desc, keyname, roms = KNOWN_SETS[setname]
    print('Found %s: %s' % (setname, desc))

    blobs = []
    for fname, crc in roms:
        data = src.read(fname)
        status = 'ok'
        if len(data) != 0x80000:
            print('Error: %s is 0x%x bytes, expected 0x80000.' % (fname, len(data)))
            return 1
        if zlib.crc32(data) & 0xFFFFFFFF != crc:
            status = 'CRC differs from MAME (hacked/modified or different dump)'
        print('  %-10s %s  %s' % (fname, src.where(fname), status))
        blobs.append(data)
    keyfile = src.read(keyname)
    if len(keyfile) < 20:
        print('Error: %s is %d bytes, expected 20.' % (keyname, len(keyfile)))
        return 1
    kcrc = zlib.crc32(keyfile[:20]) & 0xFFFFFFFF
    if len(keyfile) != 20 or kcrc != KEY_CRCS.get(keyname):
        print('WARNING: %s does not match MAME\'s key file (size %d, crc %08x, expected crc %08x).'
              % (keyname, len(keyfile), kcrc, KEY_CRCS.get(keyname, 0)))
    raw = b''.join(blobs)

    # The CPU fetches its reset vectors (SP at 0, PC at 4) as OPCODES, so they are encrypted in the ROM.
    # Decrypt, then check that SP/PC look sane; this also tells us which byte order is right.
    def attempt(dtype):
        w = np.frombuffer(raw, dtype).astype(np.uint16)
        d, master, lower, upper = _transform(w, keyfile, encrypt=False)
        sp = (int(d[0]) << 16) | int(d[1])
        pc = (int(d[2]) << 16) | int(d[3])
        good = (pc & 1) == 0 and 0x100 <= pc < len(raw) and (sp & 1) == 0 and sp <= 0xFFFFFF
        return dict(words=w, dec=d, master=master, lower=lower, upper=upper, sp=sp, pc=pc, good=good, dtype=dtype)

    tries = {'auto': ['<u2', '>u2'], 'file': ['<u2'], '68k': ['>u2']}[order]
    best = None
    for dt in tries:
        r = attempt(dt)
        if best is None or (r['good'] and not best['good']):
            best = r
        if r['good']:
            break
    words, dec, master, lower, upper = best['words'], best['dec'], best['master'], best['lower'], best['upper']
    print('Byte order: %s' % ('file order (byte-swapped words, as in the MAME zip)' if best['dtype'] == '<u2'
                              else '68k order (big-endian)'))
    print('Decrypted reset vectors: SP=%08x PC=%08x' % (best['sp'], best['pc']))
    if not best['good']:
        print('WARNING: the decrypted start address does not look valid%s.' % (' in either byte order' if len(tries) > 1 else ' in that byte order'))
        print('         Likely causes: the key file is not the one for this ROM set, or the ROMs are modified/other')
        print('         revision. Output files were still written (using %s).' % ('file order' if best['dtype'] == '<u2' else '68k order'))
    print('Master key %08x %08x, encrypted range %06x-%06x' % (master[0], master[1], lower, upper))
    outdir = folders[0]
    prefix = os.path.join(outdir, setname)
    save_words(prefix + '_data.bin', words)
    save_words(prefix + '_opcodes.bin', dec)
    print('Wrote:')
    print('  ', prefix + '_data.bin     (raw ROM, 68k order: data words are real, code words still scrambled)')
    print('  ', prefix + '_opcodes.bin  (every word decrypted: code words are real, data words get scrambled)')
    print('Use decrypt --code-ranges to build a merged image for disassembly (see --help).')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', help='folder with the ROM files / zip (default: this script\'s folder, then the current folder)')
    ap.add_argument('--set', help='force a set name when auto-detecting, e.g. ssf2t, ssf2tu, ssf2ta')
    ap.add_argument('--order', choices=['auto', 'file', '68k'], default='auto',
                    help='(auto mode) byte order of the ROM files: auto-detect (default), file (as in the MAME zip), or 68k')
    sub = ap.add_subparsers(dest='cmd')
    for name in ('decrypt', 'encrypt'):
        p = sub.add_parser(name)
        p.add_argument('--key', required=True, help='20-byte .key file (e.g. ssf2t.key)')
        p.add_argument('--out', required=True, help='output prefix (decrypt) or file (encrypt)')
        p.add_argument('roms', nargs='+', help='program ROM files, in load order')
        if name == 'decrypt':
            p.add_argument('--no-swap', action='store_true', help='input already in 68k big-endian word order')
            p.add_argument('--code-ranges', help='byte ranges that are code, e.g. 0x0-0x3fff,0x10000-0x1ffff; '
                                                 'also writes <out>_merged.bin')
        else:
            p.add_argument('--swap', action='store_true', help='input is in dumped (byte-swapped) file order')
            p.add_argument('--ranges', help='only encrypt these byte ranges (recommended); default: whole image')
    args = ap.parse_args()

    if args.cmd is None:                      # no subcommand: auto-detect and decrypt
        here = os.path.dirname(os.path.abspath(__file__))
        folders = [os.path.abspath(args.dir)] if args.dir else [here]
        if not args.dir and os.path.abspath(os.getcwd()) != here:
            folders.append(os.path.abspath(os.getcwd()))
        try:
            rc = auto_decrypt(folders, args.set, args.order)
        except Exception as e:                # keep the window readable when double-clicked
            print('Error: %s' % e)
            rc = 1
        if sys.platform == 'win32' and len(sys.argv) == 1:
            input('Press Enter to close...')
        return rc

    keyfile = open(args.key, 'rb').read()
    words = load_words(args.roms, swap=(not args.no_swap) if args.cmd == 'decrypt' else args.swap)

    if args.cmd == 'decrypt':
        dec, master, lower, upper = _transform(words, keyfile, encrypt=False)
        print('master key: %08x %08x   encrypted range: %06x-%06x   size: 0x%x bytes' %
              (master[0], master[1], lower, upper, len(words) * 2))
        save_words(args.out + '_data.bin', words)
        save_words(args.out + '_opcodes.bin', dec)
        print('wrote', args.out + '_data.bin', 'and', args.out + '_opcodes.bin')
        if args.code_ranges:
            merged = words.copy()
            for lo, hi in parse_ranges(args.code_ranges):
                merged[lo // 2:hi // 2 + 1] = dec[lo // 2:hi // 2 + 1]
            save_words(args.out + '_merged.bin', merged)
            print('wrote', args.out + '_merged.bin')
    else:
        # for encrypt, input is a big-endian opcode-view image by default
        rng = parse_ranges(args.ranges) if args.ranges else None
        enc, master, lower, upper = _transform(words, keyfile, encrypt=True, byte_ranges=rng)
        save_words(args.out, enc)
        print('wrote', args.out)


if __name__ == '__main__':
    sys.exit(main())
