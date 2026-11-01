#!/usr/bin/env python3
"""gfx_decode.py -- decode SSF2T (CPS-2) OBJ/tile graphics into viewable PNGs.

PROVEN LAYOUT (confirmed by rendering recognizable sprite art, see gallery montage):

  Source: the 12 "sfx.*m" MASK ROMs that hold the CPS-2 "gfx" region of
  Super Street Fighter II Turbo (MAME set 'ssf2t'). The two remaining mask
  ROMs sfx.11m / sfx.12m are QSound SAMPLES, NOT graphics, and are excluded.

  1) ROM -> interleaved 64-bit gfx space (MAME ROM_LOAD64_WORD):
     Each ROM contributes one 16-bit lane of a 64-bit (8-byte) gfx word.
     gfx[word_index*8 + lane_byte_offset + {0,1}] = rom[k], rom[k+1]
       sfx.13m -> byte offset 0   (bits  0..15)
       sfx.15m -> byte offset 2   (bits 16..31)
       sfx.17m -> byte offset 4   (bits 32..47)
       sfx.19m -> byte offset 6   (bits 48..63)   at gfx base 0x000000, 0x200000 each
       sfx.14m/16m/18m/20m  -> same 4 lanes at gfx base 0x800000, 0x100000 each
       sfx.21m/23m/25m/27m  -> same 4 lanes at gfx base 0xC00000, 0x100000 each
     Total gfx space = 0x1000000 (16 MB).

  2) cps2_gfx_decode(): per 0x200000-byte bank, MAME runs unshuffle() on the
     bank viewed as an array of u64 (banksize/8 entries). This is a recursive
     bit/byte de-interleave that the CPS-2 hardware expects. Replicated here.

  3) Tile decode (MAME gfx_cps1 / cps1_layout16x16), 16x16, 4 bits/pixel:
       128 bytes per 16x16 tile (4*16*16 bits).
       planeoffset = {24, 16, 8, 0}
       xoffset     = {0..7, 32..39}   (two 8-pixel halves)
       yoffset     = {0,64,128,...}   (one row every 64 bits = 8 bytes)
     i.e. a 16x16 tile occupies two consecutive 64-byte halves; column
     alternates between the halves (that is exactly xoffset {STEP8(0,1),STEP8(32,1)}).

  Palette: real CPS-2 palettes aren't wired here, so we render a readable
  16-level grayscale false-colour ramp. Pen 0 is transparent/background.

Requires Pillow (pip install pillow). A raw-PNG fallback (zlib) is included
if Pillow is unavailable.
"""
import os
import struct
import zlib

import paths
ROM_DIR = paths.ROM_DIR

GFX_SIZE = 0x1000000          # 16 MB interleaved gfx space
BANKSIZE = 0x200000           # unshuffle bank size (bytes)
TILE16_BYTES = 128            # bytes per 16x16 4bpp tile

# (filename, gfx_base, length, lane_byte_offset)
# lane_byte_offset selects which 2 bytes of the 8-byte gfx word this ROM fills.
GFX_ROMS = [
    ("sfx.13m", 0x000000, 0x200000, 0),
    ("sfx.15m", 0x000000, 0x200000, 2),
    ("sfx.17m", 0x000000, 0x200000, 4),
    ("sfx.19m", 0x000000, 0x200000, 6),
    ("sfx.14m", 0x800000, 0x100000, 0),
    ("sfx.16m", 0x800000, 0x100000, 2),
    ("sfx.18m", 0x800000, 0x100000, 4),
    ("sfx.20m", 0x800000, 0x100000, 6),
    ("sfx.21m", 0xC00000, 0x100000, 0),
    ("sfx.23m", 0xC00000, 0x100000, 2),
    ("sfx.25m", 0xC00000, 0x100000, 4),
    ("sfx.27m", 0xC00000, 0x100000, 6),
]

_GFX_CACHE = None


def _unshuffle(buf, start, length):
    """Port of MAME cps2_state::unshuffle (operates on u64 units).

    buf is a bytearray; (start, length) is a window in units of u64 ENTRIES,
    i.e. byte range [start*8, (start+length)*8). Mirrors the recursive C code.
    """
    if length == 2:
        return
    assert length % 4 == 0, "unshuffle length must be a multiple of 4"
    half = length // 2
    _unshuffle(buf, start, half)
    _unshuffle(buf, start + half, half)
    # swap buf[start+half/2 + i] <-> buf[start+half + i] for i in 0..half/2-1
    q = half // 2
    for i in range(q):
        a = (start + q + i) * 8
        b = (start + half + i) * 8
        tmp = buf[a:a + 8]
        buf[a:a + 8] = buf[b:b + 8]
        buf[b:b + 8] = tmp


def load_gfx(rom_dir=ROM_DIR, do_unshuffle=True):
    """Load + interleave the 12 mask ROMs, then apply cps2 unshuffle per bank.

    Returns a bytearray of length GFX_SIZE. Cached after first call.
    """
    global _GFX_CACHE
    if _GFX_CACHE is not None:
        return _GFX_CACHE

    gfx = bytearray(GFX_SIZE)
    for fname, base, length, lane in GFX_ROMS:
        path = os.path.join(rom_dir, fname)
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < length:
            raise ValueError("%s shorter than expected (%d < %d)" %
                             (fname, len(data), length))
        # interleave: 16-bit words, stride 8 bytes in gfx space
        nwords = length // 2
        for w in range(nwords):
            src = w * 2
            dst = base + w * 8 + lane
            gfx[dst] = data[src]
            gfx[dst + 1] = data[src + 1]

    if do_unshuffle:
        total_entries = GFX_SIZE // 8
        bank_entries = BANKSIZE // 8
        for b in range(0, total_entries, bank_entries):
            _unshuffle(gfx, b, bank_entries)

    _GFX_CACHE = gfx
    return gfx


def _bit(byte_val, n):
    return (byte_val >> n) & 1


def decode_tile(tile_index, size=16, gfx=None):
    """Decode one tile to a size x size list-of-lists of 4-bit color indices.

    Only size=16 is the native CPS-2 OBJ tile. size=8 decodes the top-left
    8x8 quadrant of the corresponding region (useful for text/font ROMs).
    """
    if gfx is None:
        gfx = load_gfx()
    base = tile_index * TILE16_BYTES
    out = [[0] * size for _ in range(size)]
    # cps1_layout16x16: planeoffset {24,16,8,0}, xoffset {STEP8(0,1),STEP8(32,1)},
    # yoffset {STEP16(0,4*16)} => bit addressing in the 128-byte tile.
    planeoffset = (24, 16, 8, 0)
    for y in range(size):
        ybit = y * 64            # 4*16 bits per row
        for x in range(size):
            if x < 8:
                xbit = x          # STEP8(0,1)
            else:
                xbit = 32 + (x - 8)  # STEP8(32,1)
            pix = 0
            for p in range(4):     # 4 bitplanes -> 4-bit pen
                bitpos = ybit + xbit + planeoffset[p]
                byte_index = base + (bitpos >> 3)
                bit_in_byte = 7 - (bitpos & 7)   # MSB-first within byte
                pix = (pix << 1) | _bit(gfx[byte_index], bit_in_byte)
            out[y][x] = pix
    return out


# -------- rendering --------

def _false_color_palette():
    """16-entry RGB palette. Pen 0 handled as transparent by callers.
    Grayscale ramp so shapes read clearly; pen 15 kept dark (common bg pen)."""
    pal = []
    for i in range(16):
        v = int(round(i * 255 / 15))
        pal.append((v, v, v))
    return pal


PALETTE = _false_color_palette()
TRANSPARENT_PEN = 15   # CPS DRAWSPRITE uses pen 15 as the transpen


# ---- real CPS palette support -------------------------------------------
# CPS palette entries are BE16 in 0x0RGB form (4-4-4). PROVEN by rendering:
# the character-palette table lives in the DATA image at 0x031C48 (gradient
# of 16-colour subpalettes, 0x20 bytes each). A sprite's palette index comes
# from the OBJ attr word low 5 bits (attr & 0x1f). [INFERRED subpal base.]
CPS_PAL_TABLE = 0x031C48      # candidate character palette table (data image)


def cps_rgb(entry16):
    """CPS 0x0RGB BE16 word -> (r,g,b) 0..255."""
    r = (entry16 >> 8) & 0xF
    g = (entry16 >> 4) & 0xF
    b = entry16 & 0xF
    return (r * 17, g * 17, b * 17)


def load_cps_subpalette(data, table_off, subpal_index):
    """Return a 16-entry [(r,g,b)...] list for subpalette `subpal_index`
    from a CPS palette table at `table_off` in `data` (bytes)."""
    import struct
    base = table_off + subpal_index * 0x20   # 16 words = 32 bytes per subpal
    pal = []
    for i in range(16):
        w = struct.unpack_from(">H", data, base + 2 * i)[0]
        pal.append(cps_rgb(w))
    return pal



def _try_pillow():
    try:
        from PIL import Image  # noqa
        return True
    except Exception:
        return False


def render_tile_png(tile_index, scale=8, size=16, gfx=None):
    """Return PNG bytes for a single tile, scaled up `scale`x. Pen 15 -> bg."""
    px = decode_tile(tile_index, size=size, gfx=gfx)
    return _grid_to_png([px], cols=1, scale=scale, tile_w=size, tile_h=size,
                        gap=0)


def render_sheet_png(start, count=256, cols=16, scale=2, size=16, gfx=None):
    """Montage of `count` tiles starting at `start`."""
    if gfx is None:
        gfx = load_gfx()
    tiles = [decode_tile(start + i, size=size, gfx=gfx) for i in range(count)]
    return _grid_to_png(tiles, cols=cols, scale=scale, tile_w=size,
                        tile_h=size, gap=1)


def _grid_to_png(tiles, cols, scale, tile_w, tile_h, gap):
    rows = (len(tiles) + cols - 1) // cols
    W = cols * (tile_w * scale + gap) + gap
    H = rows * (tile_h * scale + gap) + gap

    if _try_pillow():
        from PIL import Image
        img = Image.new("RGB", (W, H), (16, 16, 40))  # dark blue grid bg
        pix = img.load()
        for ti, tile in enumerate(tiles):
            cx = ti % cols
            cy = ti // cols
            ox = gap + cx * (tile_w * scale + gap)
            oy = gap + cy * (tile_h * scale + gap)
            for y in range(tile_h):
                for x in range(tile_w):
                    pen = tile[y][x]
                    if pen == TRANSPARENT_PEN:
                        continue  # leave background
                    r, g, b = PALETTE[pen]
                    for sy in range(scale):
                        for sx in range(scale):
                            pix[ox + x * scale + sx, oy + y * scale + sy] = (r, g, b)
        import io
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        return bio.getvalue()

    # ---- Pillow-free fallback: hand-rolled RGB PNG via zlib ----
    row_bytes = W * 3
    raw = bytearray()
    canvas = bytearray([16, 16, 40] * (W * H))  # flat RGB
    def put(px_, py_, rgb):
        o = (py_ * W + px_) * 3
        canvas[o:o + 3] = bytes(rgb)
    for ti, tile in enumerate(tiles):
        cx = ti % cols
        cy = ti // cols
        ox = gap + cx * (tile_w * scale + gap)
        oy = gap + cy * (tile_h * scale + gap)
        for y in range(tile_h):
            for x in range(tile_w):
                pen = tile[y][x]
                if pen == TRANSPARENT_PEN:
                    continue
                rgb = PALETTE[pen]
                for sy in range(scale):
                    for sx in range(scale):
                        put(ox + x * scale + sx, oy + y * scale + sy, rgb)
    for y in range(H):
        raw.append(0)  # filter type 0
        o = y * row_bytes
        raw += canvas[o:o + row_bytes]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        crc = zlib.crc32(typ + data) & 0xFFFFFFFF
        return c + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    return (sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", comp) +
            chunk(b"IEND", b""))


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sheet.png"
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 256
    data = render_sheet_png(start, count=count)
    with open(out, "wb") as f:
        f.write(data)
    print("wrote", out, len(data), "bytes; Pillow=", _try_pillow())
