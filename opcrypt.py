"""opcrypt.py -- read/write values the 68000 fetches through CPS-2 decryption.

CPS-2 encrypts the program ROM on the opcode bus only. Instruction words,
immediates (move.w #$90,...) and PC-relative reads (move.w tbl(pc,d0.w),d1)
go through the decryption; ordinary data reads through an address register
see the raw ROM. The editor's WORKING image holds the raw (encrypted) bytes,
so an opcode-space value is edited by changing its plaintext word, encrypting
that word for its address and writing the result back.

The cipher is a per-address 16-bit permutation (keyed by the word address and
the game's ssf2t.key), so one word can be re-encrypted without touching any
other byte. cps2_decrypt.py is the MAME cps2crpt port used to build
ssf2t_opcodes.bin; round-trip over the whole ROM is exact (verified).
"""
import os

import numpy as np

import cps2_decrypt as _c


class OpCrypt:
    def __init__(self, keyfile):
        with open(keyfile, "rb") as fh:
            master, self.lower, self.upper = _c.decode_key(fh.read())
        self._k2 = _c.build_word_keys(master)

    def _run(self, addr, word, encrypt):
        if addr % 2:
            raise ValueError("opcode words are at even addresses")
        if not (self.lower <= addr <= self.upper):
            return word                       # outside the encrypted range
        idx = (addr // 2) & 0xFFFF
        keys = [np.array([k[idx]], np.uint32) for k in self._k2]
        f = _c.feistel_inv if encrypt else _c.feistel
        out = f(np.array([word], np.uint16), _c.GROUP_A2, _c.GROUP_B2, _c.ROUNDS2, keys)
        return int(out[0])

    def read(self, image, addr):
        """Plaintext word the CPU fetches at addr."""
        raw = (image[addr] << 8) | image[addr + 1]
        return self._run(addr, raw, False)

    def write(self, image, addr, plain):
        """Store plaintext word `plain` at addr (image is a bytearray of raw ROM)."""
        raw = self._run(addr, plain & 0xFFFF, True)
        image[addr] = raw >> 8
        image[addr + 1] = raw & 0xFF


def load(rom_dir, name="ssf2t.key"):
    path = os.path.join(rom_dir, name)
    return OpCrypt(path) if os.path.exists(path) else None
