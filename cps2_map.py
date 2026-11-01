#!/usr/bin/env python3
"""cps2_map.py -- flat SSF2T program image <-> individual program EPROM mapping.

PROVEN (not guessed) from cps2_decrypt.py + byte comparison against
ssf2t_data.bin:

  * The flat image is the SEVEN program ROMs concatenated in load order
    (sfxe.03c, sfxe.04a, sfxe.05, sfxe.06a, sfxe.07, sfxe.08, sfx.09),
    0x80000 bytes each -> 0x380000 total. It is NOT an even/odd interleave
    of ROM pairs.
  * Within every 16-bit (2-byte) word the two bytes are SWAPPED relative to
    the raw ROM bytes. cps2_decrypt.py reads the concatenation as little-endian
    u16 (swap=True) and writes the output as big-endian u16; the net effect on
    the data image is a per-word byte swap. So:
        flat_byte[F] == concat_byte[F ^ 1]
    Because each ROM is 0x80000 (even, word-aligned), the ROM selection uses the
    concatenation offset and the in-ROM offset simply has its low bit flipped.

This module performs ONLY the de-interleave/byte-order mapping. It says nothing
about CPS-2 decryption -- these offsets are positions, valid for the encrypted
EPROM bytes and for the decrypted flat images alike.
"""

EPROM_SIZE = 0x80000  # 524288 bytes per program EPROM

# flat offset ranges, in load order. slot index -> (eprom_name, flat_start, flat_end_exclusive)
LOAD_ORDER = [
    "sfxe.03c",  # slot 0: flat 0x000000..0x07FFFF
    "sfxe.04a",  # slot 1: flat 0x080000..0x0FFFFF
    "sfxe.05",   # slot 2: flat 0x100000..0x17FFFF
    "sfxe.06a",  # slot 3: flat 0x180000..0x1FFFFF
    "sfxe.07",   # slot 4: flat 0x200000..0x27FFFF
    "sfxe.08",   # slot 5: flat 0x280000..0x2FFFFF
    "sfx.09",    # slot 6: flat 0x300000..0x37FFFF  (the 7th ROM; closes the 0x80000 gap)
]

FLAT_SIZE = EPROM_SIZE * len(LOAD_ORDER)  # 0x380000


def flat_to_eprom(flat_off):
    """Map a byte offset in the flat image -> (eprom_name, offset_within_that_eprom)."""
    if not (0 <= flat_off < FLAT_SIZE):
        raise ValueError("flat offset 0x%x out of range [0, 0x%x)" % (flat_off, FLAT_SIZE))
    slot = flat_off // EPROM_SIZE
    within = flat_off % EPROM_SIZE
    within ^= 1  # per-word byte swap between flat image and raw ROM bytes
    return LOAD_ORDER[slot], within


def eprom_to_flat(eprom_name, eprom_off):
    """Map (eprom_name, byte offset within that EPROM) -> byte offset in the flat image."""
    if eprom_name not in LOAD_ORDER:
        raise ValueError("unknown EPROM %r (known: %s)" % (eprom_name, ", ".join(LOAD_ORDER)))
    if not (0 <= eprom_off < EPROM_SIZE):
        raise ValueError("eprom offset 0x%x out of range [0, 0x%x)" % (eprom_off, EPROM_SIZE))
    slot = LOAD_ORDER.index(eprom_name)
    return slot * EPROM_SIZE + (eprom_off ^ 1)


if __name__ == "__main__":
    # Round-trip identity over a dense sweep.
    for f in range(0, FLAT_SIZE, 0x5555):
        name, off = flat_to_eprom(f)
        assert eprom_to_flat(name, off) == f, "round-trip failed at 0x%x" % f

    # The 3 worked examples proven in the probe (byte-swap within word, 7-ROM concat):
    #   flat 0x000000 -> sfxe.03c 0x000001   (word 0 bytes swapped)
    #   flat 0x100001 -> sfxe.05  0x000000   (slot 2 start, low bit flipped)
    #   flat 0x300000 -> sfx.09   0x000001   (7th ROM, closes the 0x80000 gap)
    assert flat_to_eprom(0x000000) == ("sfxe.03c", 0x000001)
    assert flat_to_eprom(0x100001) == ("sfxe.05", 0x000000)
    assert flat_to_eprom(0x300000) == ("sfx.09", 0x000001)
    assert eprom_to_flat("sfxe.03c", 0x000001) == 0x000000
    assert eprom_to_flat("sfxe.05", 0x000000) == 0x100001
    assert eprom_to_flat("sfx.09", 0x000001) == 0x300000

    print("cps2_map self-test OK")
    print("Load order (slot -> eprom -> flat range):")
    for i, name in enumerate(LOAD_ORDER):
        lo = i * EPROM_SIZE
        print("  slot %d  %-9s  flat 0x%06X..0x%06X" % (i, name, lo, lo + EPROM_SIZE - 1))
    print("Worked examples:")
    for f in (0x000000, 0x100001, 0x300000):
        n, o = flat_to_eprom(f)
        print("  flat 0x%06X  <->  %-9s offset 0x%06X" % (f, n, o))
