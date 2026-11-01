#!/usr/bin/env python3
"""obj_decode.py -- assemble SSF2T (CPS-2) frame sprites from the OBJ list.

CPS-2 / Motorola 68000, BIG-ENDIAN. Flat offset == CPU address. DATA bytes
come from the flat data image ssf2t_data.bin (see paths.py).

================================================================================
FORMAT -- PROVEN by disassembling the sprite builder in ssf2t_opcodes.bin
          (Ghidra). The routine at CPU 0x0C6E80 is the OBJ-list interpreter:

    movea.l (0x1a,A1),A2      ; A2 = anim_ptr (frame record)
    movea.l (0x4,A2),A2       ; A2 = obj_ptr  (this OBJ list)
    move.w  (A2)+,D3          ; D3 = COUNT   (word[0])           [PROVEN]
      beq -> skip (count 0 == "reuse previous sprite")
      bmi -> macro/compressed variant (top bit set)  (not used by Ryu f0/f2)
    move.w  (A2)+,D2          ; D2 = ATTR    (word[1], =0x000e)  [PROVEN]
    move.w  (A2)+,D4          ; D4 = PIECE0  (word[2])           [PROVEN]
    bsr     0x0C74CC          ; resolve PIECE0 -> A3 = coord record
    ...                       ; peek 0x3fff special (unused here)
    move.w  (A2)+, xbase      ; word[3] = X base (signed)        [PROVEN]
    move.w  (A2)+, ybase      ; word[4] = Y base (signed)        [PROVEN]
    movea.l (0x4,frame),A2 ; lea (0xa,A2),A2   ; tile stream = obj + 0x0A
    <loop D3 times>: tile=(A2)+ ; (dx,dy)=(A3)+ ; emit (xbase+dx, ybase+dy, tile)

  PIECE0 -> coord-record resolver at 0x0C74CC  [PROVEN]:
    D5 = (pid & 0x7f80) >> 5                 ; selects one of 4 group bases
    A3 = GROUP_BASES[D5/4]                    ; longword table @ 0x0C74E4:
         { 0x00100304, 0x00102830, 0x00105698, 0x0010B34C }
    A3 = GROUP_BASES[..] + BE16[GROUP_BASE + (pid & 0x7f)*2]
         ; A3 now points at a list of signed (dx,dy) BE16 pairs, one per tile.

  So: COUNT 16x16 tiles; tile codes come from the stream at obj+0x0A; the
  per-tile (dx,dy) pixel offsets come from PIECE0's coord record. Each tile is
  placed at (xbase+dx, ybase+dy) relative to the SPRITE ORIGIN (0,0) -- which is
  the SAME origin the hitboxes are expressed around (box val_x/val_y are offsets
  from this origin; y is screen-down in sprite space, boxes use y-up so the
  frontend/overlay negates y).

  Terminator: a tile word 0x0000 ends the stream early (PROVEN: `move.w (A2),D4;
  bne` skip on zero). Tile words 0xF000 / 0xF200 / 0xFF00 are stream control
  opcodes in the general interpreter; Ryu f0/f2 use none of them.

================================================================================
CONFIRMED-BY-RENDERING (ground truth, like the font "Here Comes A New Challenger"
proof): placing the tiles at these coord-record offsets assembles SEAMLESS,
non-scrambled art (see shots/f0_boxed.png, f2_boxed.png). The Ryu anim 0/1/2
first frames (obj_ptr 0x06EDE0) are a round/stretching ENERGY-EFFECT sprite
(Hadouken-like), NOT a standing body -- that is simply what these obj_ptrs
encode. The attack box (rx28,ry19) tracks the sprite extent.

Fields are PROVEN (from the 68k drawer) except the exact y-sign convention for
overlaying boxes, which is INFERRED (boxes y-up vs sprite y-down) and applied in
the overlay only.
"""
import struct

import paths
DATA_PATH = paths.DATA_BIN

# coord-record group bases (longword table @ CPU 0x0C74E4)  [PROVEN]
GROUP_BASES = (0x00100304, 0x00102830, 0x00105698, 0x0010B34C)

HDR_WORDS = 5                 # count, attr, piece0, xbase, ybase
STREAM_OFF = 0x0A             # tiles start at obj_ptr + 0x0A  (lea (0xa,A2))


def _load(path=DATA_PATH):
    with open(path, "rb") as f:
        return f.read()


def _be16(d, o):
    return struct.unpack_from(">H", d, o)[0]


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _block_tile(code, bx, by):
    """Tile code at column bx, row by of a CPS block sprite. The column wraps
    inside the 16-tile row of the base code (MAME cps1.cpp:
    (code & ~0xf) + ((code + nxs) & 0xf) + 0x10*nys), so a block whose base is
    not 16-aligned does NOT simply count up. Without the wrap, wide frames
    (e.g. Ken's kicks, attr high byte set) came out scrambled."""
    return ((code & ~0xF) + ((code + bx) & 0xF) + 0x10 * by) & 0x1FFFF


def resolve_coord_record(data, piece_id):
    """PIECE id -> flat offset of its (dx,dy) coord record. [PROVEN 0x0C74CC]
    Returns None for a malformed piece id (group index out of range) rather than
    raising -- a bad id means the frame isn't a real body list, which the caller
    handles gracefully instead of 500ing the sprite endpoint."""
    grp = ((piece_id & 0x7F80) >> 5)        # byte offset into 4-entry longword table
    gi = grp >> 2                           # valid pieces give 0..3
    if gi >= len(GROUP_BASES):
        return None
    base = GROUP_BASES[gi]
    idx = (piece_id & 0x7F) * 2
    return (base + _be16(data, base + idx)) & 0xFFFFFF


def parse_obj_list(data, obj_ptr):
    """Decode one OBJ list.

    Returns {count, attr, piece0, base_x, base_y, origin, entries:[{tile,x,y,
    flip,pal}]} where x,y are pixel offsets from the sprite origin (0,0).
    """
    o = obj_ptr & 0xFFFFFF
    count = _be16(data, o)
    attr = _be16(data, o + 2)
    piece0 = _be16(data, o + 4)
    base_x = _s16(_be16(data, o + 6))
    base_y = _s16(_be16(data, o + 8))

    entries = []
    if count and not (count & 0x8000):
        rec = resolve_coord_record(data, piece0)
        stream = o + STREAM_OFF
        for i in range(count):
            tile = _be16(data, stream + 2 * i)
            if tile == 0x0000:                     # terminator
                break
            dx = _s16(_be16(data, rec + 4 * i))
            dy = _s16(_be16(data, rec + 4 * i + 2))
            entries.append({
                "tile": tile & 0x1FFFF,            # gfx tile index (hi bits unused here)
                "x": base_x + dx,
                "y": base_y + dy,
                "flip": (attr >> 5) & 3,           # attr bit layout (INFERRED: xflip/yflip)
                "pal": attr & 0x1F,                # low bits palette (INFERRED)
            })
    return {
        "obj_ptr": o,
        "count": count,
        "attr": attr,
        "piece0": piece0,
        "base_x": base_x,
        "base_y": base_y,
        "coord_record": resolve_coord_record(data, piece0) if count and not (count & 0x8000) else None,
        "origin": (0, 0),       # sprite origin == hitbox axis
        "entries": entries,
    }


# ---------------- body (character) OBJ-list path ----------------
# PROVEN by rendering against LIVE ground truth: new Ryu idle frame record
# @0x113742 -> obj_ptr 0x1161C6 assembles a coherent standing Ryu (white gi,
# headband, feet on the origin axis) -- see shots/ryu_idle_REAL.png.
#
# BODY OBJ-list format (differs from the projectile path above only in the
# header length and the zero-tile meaning):
#   word0 count   (number of 16x16 tile slots)
#   word1 attr    (palette/flip bits)
#   word2 piece0  (coord-record selector, resolved via resolve_coord_record)
#   word3 ------- HEADER-TYPE DISCRIMINATOR:
#                 if word3 == 0x3FFF -> 6-WORD header:
#                       word4 = base_x (signed), word5 = base_y (signed),
#                       tile stream starts at obj + 0x0C
#                 else                -> 5-WORD header:
#                       word3 = base_x (signed), word4 = base_y (signed),
#                       tile stream starts at obj + 0x0A
#   then COUNT tile words, consumed by a STREAM INTERPRETER (ported from the
#   proven 68k sprite builder at CPU 0x0C6F92). The tile pointer (A2) and the
#   coord-record pointer (A3) advance INDEPENDENTLY: the loop runs on a
#   dbf(count-1) counter, and only NORMAL tiles decrement it. Stream opcodes:
#     0x0000              SKIP slot: A2+=2, A3+=4, counter NOT decremented.
#     0xF200              BASE-SET: next 2 words are scratch_x/scratch_y added
#                         to the following tile's position (then cleared); A2+=6.
#     (word&0xFF00)==0xFF00  COORD-ADVANCE: A3 += signed_byte(word&0xFF) << 2
#                         BYTES (0xFFFC => -4 entries, a rewind -- PROVEN by
#                         render; the unsigned +252-entry reading scatters the
#                         sprite across 200px, see shots/idle_interpreter_unsigned.png).
#     0xF000              MACRO sub-sprite: skipped safely (one slot consumed).
#   Each normal tile is placed at (base_x+dx+scratch_x, base_y+dy+scratch_y)
#   from the sprite origin (0,0), the same origin the hitboxes use.
#
# NOTE: the former hardcoded BODY_HDR_WORDS=6 / BODY_STREAM_OFF=0x0C was WRONG
# for real body frames (word3 is a signed base_x like 0xFFFC, not 0x3FFF), so it
# started the tile stream one word too late and shifted every tile<->coord
# pairing by one slot -- the "jumbled tiles" bug. The 6-word path is kept for the
# genuine 0x3FFF sentinel variant.
# NOTE: the earlier simple lockstep loop (for i in range(count), 0x0000=drop)
# counted SKIP slots against the loop, truncating the last body tile(s) of every
# frame AND mis-handling the 0xFFxx opcode frames entirely. The dbf-counter
# interpreter above fixes both (all 62 renderable frames now complete).
BODY_HDR_SENTINEL = 0x3FFF    # word3 value that marks a 6-word header


def body_header_layout(data, obj_ptr):
    """Return (stream_off, base_x, base_y) for a body OBJ list, choosing the
    5-word or 6-word header dynamically from word3. [PROVEN by rendering]"""
    o = obj_ptr & 0xFFFFFF
    word3 = _be16(data, o + 6)
    if word3 == BODY_HDR_SENTINEL:            # 6-word header
        base_x = _s16(_be16(data, o + 8))     # word4
        base_y = _s16(_be16(data, o + 10))    # word5
        return 0x0C, base_x, base_y
    base_x = _s16(word3)                       # word3 (5-word header)
    base_y = _s16(_be16(data, o + 8))          # word4
    return 0x0A, base_x, base_y


MAX_BODY_TILES = 256          # sane cap -- no char has >100 tiles per pose
MAX_SPRITE_DIM = 512          # pixel cap per axis before scaling

# UNUSED / WRONG: these bytes were copied from the OPCODE image, where 0x0C7BEE
# is encrypted data. The real table (DATA image) is table[k] = nx*ny - 1 with
# nx=(k&0xF)+1, ny=(k>>4)+1; parse_body_obj_list computes it directly.
# Kept only so nothing importing the name breaks.
MACRO_SKIP_TABLE = bytes.fromhex(
    "2f4bf2173674686c26ea42bd69db4b45"
    "afcce6534686fa473b1293009ea7cd87"
    "14a692e2fdfcaee4ea5ca4912dbf5426"
    "3171c46ed62fd868b757ee8b140787fb"
    "1366399efad5431d298a3ae85db8ac67"
    "10b770c03e5c7afa8a9bafef9e44f17a"
    "c2a51b6d0f39c639f637ea25a13cd50e"
    "5aeb5524291f732e31e04c4d46a899b9"
    "55c82fcc44d146b7ef20e4aaff1c11f5"
    "4c71ca713851b1945a0a6a349bfb1e5e"
    "8be2ec77193039f5deeaff40b02fdb63"
    "5932e0a0c9f155357cccc0ecdbac34d3"
    "18854493cd186d67e2f7c01ca62ee9ea"
    "11560977187437841cb79392520ca410"
    "8a7489ef62ae378e7a0203d8530aee29"
    "80e3ecc5821e8c52c4894e40db13a3d3")


def _parse_variant_stream(data, a2, a3, count, hdr_attr, base_x, base_y):
    """Body list whose count word has bit 15 set (asm 0x0C74F4, the second
    builder): every tile carries its OWN attribute word.

      header attr -> only its flip bits are kept (andi.w #$e0); no block size
      0x0000      -> skip: 2 words, 1 coord pair
      0xF200      -> base-set (as normal)            0xFFxx -> coord advance
      0xF000      -> macro, 5 words: F000, param, tile, attr, advance
                     final attr = attr ^ (param | header flips); block size from
                     its high byte; uses nx*ny of the count (table 0x0C7BEE)
      other       -> tile word + attr word; final attr = attr ^ header flips;
                     block size (high byte) per tile; uses 1 of the count

    Returned entries carry the pixel flip ("flip") and, separately, the header
    flip ("mirror") that mirrors the whole figure -- a tile can be flipped on its
    own (reused mirrored flame/arm pieces) without moving.
    """
    hflip = hdr_attr & 0x60
    entries, emitted, guard = [], 0, 0
    sx = sy = 0
    while emitted < count and emitted < MAX_BODY_TILES and guard < MAX_BODY_TILES * 8:
        guard += 1
        if a2 + 3 >= len(data) or a3 + 3 >= len(data):
            break
        w = _be16(data, a2)
        if w == 0x0000:
            a2 += 4; a3 += 4
            continue
        if w == 0xF200:
            sx = _s16(_be16(data, a2 + 2)); sy = _s16(_be16(data, a2 + 4))
            a2 += 6
            continue
        if (w & 0xFF00) == 0xFF00:
            a3 += (w & 0xFF) * 4
            a2 += 2
            continue
        dx = _s16(_be16(data, a3)); dy = _s16(_be16(data, a3 + 2))
        if w == 0xF000:
            param = _be16(data, a2 + 2); tile = _be16(data, a2 + 4)
            final = _be16(data, a2 + 6) ^ (param | hflip); adv = _be16(data, a2 + 8)
            a2 += 10
            a3 += 4 + _s16((adv << 2) & 0xFFFF)
        else:
            tile = w
            final = _be16(data, a2 + 2) ^ hflip
            a2 += 4
            a3 += 4
        k = final >> 8
        nx, ny = (k & 0xF) + 1, (k >> 4) + 1
        pflip = (final >> 5) & 3
        own = pflip ^ (hflip >> 5)              # the tile's own flip (not the figure's)
        x0, y0 = dx - base_x + sx, base_y + dy + sy
        for by in range(ny):
            for bx in range(nx):
                cx = (nx - 1 - bx) if own & 1 else bx   # a flipped block lays its tiles out mirrored
                cy = (ny - 1 - by) if own & 2 else by
                entries.append({"tile": _block_tile(tile, bx, by),
                                "x": x0 + 16 * cx, "y": y0 + 16 * cy,
                                "flip": pflip, "mirror": hflip >> 5, "pal": final & 0x1F})
        emitted += nx * ny if w == 0xF000 else 1
        sx = sy = 0
    return entries


def parse_body_obj_list(data, obj_ptr):
    """Decode one CHARACTER-BODY OBJ list (5- or 6-word header, 0x0000 = skip slot).

    Returns the same shape as parse_obj_list; entries keep slot alignment with
    the coord record (skipped 0x0000 slots are omitted from entries but still
    advance the coord index).  Caps count at MAX_BODY_TILES to avoid OOM on
    garbage pointers.
    """
    o = obj_ptr & 0xFFFFFF
    # Minimum viable read: 5-word header = 10 bytes
    if o + 0x0A > len(data):
        return {"obj_ptr": o, "count": 0, "attr": 0, "piece0": 0,
                "base_x": 0, "base_y": 0, "coord_record": 0,
                "origin": (0, 0), "entries": [], "error": "obj_ptr out of range"}
    count = _be16(data, o)
    macro_variant = bool(count & 0x8000)   # top-bit set = macro-only count variant
    count &= 0x7FFF
    if count == 0 or count > MAX_BODY_TILES:
        return {"obj_ptr": o, "count": count, "attr": 0, "piece0": 0,
                "base_x": 0, "base_y": 0, "coord_record": 0,
                "origin": (0, 0), "entries": [],
                "error": f"bad count {count} (max {MAX_BODY_TILES})"}
    attr = _be16(data, o + 2)
    piece0 = _be16(data, o + 4)

    # Dynamic header: word3 == 0x3FFF => 6-word (tiles @ +0x0C), else 5-word (tiles @ +0x0A)
    stream_off, base_x, base_y = body_header_layout(data, o)
    stream = o + stream_off

    if stream >= len(data):
        return {"obj_ptr": o, "count": count, "attr": attr, "piece0": piece0,
                "base_x": base_x, "base_y": base_y, "coord_record": 0,
                "origin": (0, 0), "entries": [],
                "error": "tile stream starts past data end"}

    rec = resolve_coord_record(data, piece0)
    flip = (attr >> 5) & 3
    pal = attr & 0x1F
    # attr HIGH BYTE != 0 => the whole list is ONE hardware block sprite
    # (asm 0x0C6EA8: `andi.w #0xff00,D4; beq; moveq #1,D3` overrides the count
    # to 1, and the high byte rides into the colour word as the block size:
    # nx=(k&0xF)+1 wide, ny=(k>>4)+1 tall). Ryu's breathing idle (anim 0,
    # attr 0x5301) is a single 4x6 block. [PROVEN by render]
    block_k = attr >> 8
    if block_k and not macro_variant:
        count = 1
    if rec is None:
        return {"obj_ptr": o, "count": count, "attr": attr, "piece0": piece0,
                "base_x": base_x, "base_y": base_y, "coord_record": None,
                "origin": (0, 0), "entries": [], "error": "bad piece0 coord record"}

    # ---- FAITHFUL PORT of the 68k interpreter loop at CPU 0x0C6F92 ----------
    # (sprite_build_objlist, ssf2t_opcodes.bin). The body is ONE continuous
    # stream of words consumed in lockstep with the piece0 coord record. This
    # REPLACES the earlier "chain of sub-headers" heuristic, which was wrong:
    # the 0xFFxx word is a COORD-POINTER ADVANCE, not a new sub-header's base_x,
    # and 0x0000 is a transparent skip -- not a sub-list boundary. Dropping that
    # heuristic is what fixes the scrambled / truncated attack frames.
    #
    # Register map (from the disassembly):
    #   A2 = tile stream (obj + stream_off)     D7 = output sprite budget
    #   A3 = coord record (dx,dy BE16 pairs)     D3 = count-1  (dbf counter)
    #   D0/D1 = running X/Y accumulators seeded with -base_x / +base_y
    #           (0x0C6F82 `sub.w (-0x56e0,A5),D0` = SUBTRACT base_x;
    #            0x0C6F86 `add.w (-0x56de,A5),D1` = ADD base_y). So a tile's x is
    #            dx - base_x, NOT dx + base_x. base_x varies per frame (Ryu idle
    #            -4/+4/+1...), so the wrong sign made the body jump up to 49px
    #            between frames (Ryu stand_Strong Punch). [PROVEN: feet stay
    #            planted with the asm sign]
    #   scratch_x/scratch_y (A5-0x56d8 / -0x56d6) added to the NEXT tile, then cleared
    #
    # Per stream word (classified BEFORE advancing):
    #   0x0000  -> skip slot: A2+=1 word, A3+=1 pair (dx,dy). Loops via `bra`
    #              (does NOT emit, does NOT consume the count/D3 budget).
    #   0xF200  -> base-set: scratch_x=word[+1], scratch_y=word[+2], A2+=3 words. `bra`.
    #   0xFFxx  -> coord-advance: n = word & 0xFF (UNSIGNED per `andi.w #0xff`);
    #              A3 += n pairs (asm: lsl #2 bytes). A2+=1 word. `bra`.
    #   0xF000  -> macro: emit one tile (word[+2]=tile, word[+3]=attr), A2+=5 words,
    #              A3 += (word[+4] << 2) bytes, and D3 -= MACRO_SKIP_TABLE[param>>8].
    #   else    -> NORMAL tile: emit (tile=word, x=D0+dx+scratch_x, y=D1+dy+scratch_y),
    #              A2+=1 word, A3+=1 pair, clear scratch, D7--, `dbf D3`.
    # Stop when D7 hits 0 or D3 underflows (count emitted) -- i.e. `count` is the
    # number of NORMAL/macro tiles to emit; skips & opcodes are free.
    # ------------------------------------------------------------------------
    if macro_variant:
        entries = _parse_variant_stream(data, stream, rec, count, attr, base_x, base_y)
        if stream_off == 0x0C:                  # 0x3FFF header -> tile bank 1 (see below)
            for e in entries:
                e["tile"] = (e["tile"] | 0x10000) & 0x3FFFF
        return {"obj_ptr": o, "count": count, "attr": attr, "piece0": piece0,
                "base_x": base_x, "base_y": base_y, "coord_record": rec,
                "origin": (0, 0), "entries": entries, "variant": True}

    entries = []
    a2 = stream                 # tile-stream byte offset
    a3 = rec                    # coord-record byte offset
    scratch_x = scratch_y = 0
    emitted = 0
    guard = 0
    GMAX = MAX_BODY_TILES * 8   # generous stream-word guard
    while emitted < count and emitted < MAX_BODY_TILES and guard < GMAX:
        guard += 1
        if a2 + 1 >= len(data):
            break
        w = _be16(data, a2)
        if w == 0x0000:                       # skip slot
            a2 += 2
            a3 += 4
            continue
        if w == 0xF200:                       # base-set
            if a2 + 5 >= len(data):
                break
            scratch_x = _s16(_be16(data, a2 + 2))
            scratch_y = _s16(_be16(data, a2 + 4))
            a2 += 6
            continue
        if (w & 0xFF00) == 0xFF00:            # coord-advance (unsigned low byte)
            n = w & 0xFF
            a3 += n * 4
            a2 += 2
            continue
        if w == 0xF000:                       # BLOCK macro (asm @0x0C7014)
            # Record is 4 words: F000, param, tile, advance.
            #   param high byte k -> written into the sprite colour word's size
            #   nibbles: nx = (k & 0xF)+1 tiles wide, ny = (k >> 4)+1 tiles tall.
            #   One hardware sprite = an nx*ny block; tile code at (bx,by) is
            #   tile + bx + by*0x10, placed 16px apart.
            #   The loop counter drops by table[k] = nx*ny-1 extra (the 256-byte
            #   table @0x0C7BEE in the DATA image), so count counts block tiles.
            #   A3: two (A3)+ reads (+4 bytes) then += advance*4.
            if a2 + 7 >= len(data) or a3 + 3 >= len(data):
                break
            k = _be16(data, a2 + 2) >> 8
            tile = _be16(data, a2 + 4)
            adv = _be16(data, a2 + 6)
            nx, ny = (k & 0xF) + 1, (k >> 4) + 1
            dx = _s16(_be16(data, a3)); dy = _s16(_be16(data, a3 + 2))
            x0 = dx - base_x + scratch_x
            y0 = base_y + dy + scratch_y
            for by in range(ny):
                for bx in range(nx):
                    entries.append({"tile": _block_tile(tile, bx, by),
                                    "x": x0 + 16 * bx, "y": y0 + 16 * by,
                                    "flip": flip, "pal": pal})
            a3 += 4 + _s16((adv << 2) & 0xFFFF)   # lsl.w #2 + lea (A3,D4.w): signed
            a2 += 8
            scratch_x = scratch_y = 0
            emitted += nx * ny
            continue
        # NORMAL tile
        if a3 + 3 >= len(data):
            break
        dx = _s16(_be16(data, a3)); dy = _s16(_be16(data, a3 + 2))
        bnx, bny = ((block_k & 0xF) + 1, (block_k >> 4) + 1) if block_k else (1, 1)
        for by in range(bny):
            for bx in range(bnx):
                entries.append({"tile": _block_tile(w, bx, by),
                                "x": dx - base_x + scratch_x + 16 * bx,
                                "y": base_y + dy + scratch_y + 16 * by,
                                "flip": flip, "pal": pal})
        a2 += 2
        a3 += 4
        scratch_x = scratch_y = 0
        emitted += 1

    # Tile bank: a 6-word header (word3 == 0x3FFF) makes the builder set
    # A5-0x56D2 = 0x2000 (asm 0x0C6EC0..0x0C6EC6), which rides in the sprite's
    # Y word; CPS-2 takes Y bits 13-14 as tile-code bits 16-17, so every tile of
    # such a frame is in bank 1 (+0x10000). Without it, Ken's kicks drew
    # another character's tiles. [PROVEN: MAME object RAM for Ken's Kama Barai
    # Geri active frame holds code 0x19870, decoder had 0x9870]
    if stream_off == 0x0C:
        for e in entries:
            e["tile"] = (e["tile"] | 0x10000) & 0x3FFFF

    return {
        "obj_ptr": o, "count": count, "attr": attr, "piece0": piece0,
        "base_x": base_x, "base_y": base_y,
        "coord_record": rec, "origin": (0, 0), "entries": entries,
    }


def render_body_sprite(data, obj_ptr, scale=4, gfx=None, subpal=0,
                       draw_axis=False, bg=(16, 16, 40)):
    """Render a character body sprite in real CPS colors. Returns (png, meta)."""
    import io
    import gfx_decode as g
    from PIL import Image, ImageDraw
    if gfx is None:
        gfx = g.load_gfx()
    pal = g.load_cps_subpalette(data, g.CPS_PAL_TABLE, subpal)

    parsed = parse_body_obj_list(data, obj_ptr)
    if parsed.get("error") or not parsed["entries"]:
        # Return a tiny placeholder on bad/empty data
        img = Image.new("RGBA", (16, 16), bg + (255,))
        bio = io.BytesIO(); img.save(bio, format="PNG")
        meta = {"width": 16, "height": 16, "scale": 1,
                "origin_x": 8, "origin_y": 8, "bounds": [0,0,16,16],
                "count": 0, "piece0": 0, "base_x": 0, "base_y": 0,
                "tiles": [], "error": parsed.get("error", "no entries")}
        return bio.getvalue(), meta
    minx = miny = 0
    maxx = maxy = 1
    for e in parsed["entries"]:
        minx = min(minx, e["x"]);      miny = min(miny, e["y"])
        maxx = max(maxx, e["x"] + 16); maxy = max(maxy, e["y"] + 16)
    W = max(1, min(maxx - minx, MAX_SPRITE_DIM))
    H = max(1, min(maxy - miny, MAX_SPRITE_DIM))
    scale = max(1, min(12, int(scale)))
    img = Image.new("RGBA", (W * scale, H * scale), bg + (255,))
    for e in parsed["entries"]:
        rows = g.decode_tile(e["tile"], 16, gfx=gfx)
        ti = Image.new("RGBA", (16, 16))
        xr = range(15, -1, -1) if (e["flip"] & 1) else range(16)
        yr = range(15, -1, -1) if (e["flip"] & 2) else range(16)
        for yy, sy_ in enumerate(yr):
            for xx, sx_ in enumerate(xr):
                ci = rows[sy_][sx_]
                if ci == g.TRANSPARENT_PEN:
                    continue
                r, gc, b = pal[ci] if ci < len(pal) else (255, 0, 255)
                ti.putpixel((xx, yy), (r, gc, b, 255))
        ti = ti.resize((16 * scale, 16 * scale), Image.NEAREST)
        # When a tile is flipped, the CPS-2 hardware mirrors the WHOLE sprite --
        # both the tile's pixels (done above) AND its placement within the sprite.
        # Mirror the local position so a uniformly x/y-flipped multi-tile figure
        # (e.g. Honda, whose attr sets x-flip on every tile) reassembles coherently
        # instead of shattering. [PROVEN by render: honda idle -> clean sumo stance]
        lx = e["x"] - minx
        ly = e["y"] - miny
        # "mirror" = the whole figure's flip (variant lists, where a tile can be
        # flipped on its own); normal lists share one flip, so it is "flip".
        m = e.get("mirror", e["flip"])
        if m & 1:
            lx = (W - 16) - lx
        if m & 2:
            ly = (H - 16) - ly
        img.paste(ti, (lx * scale, ly * scale), ti)
    ox = (0 - minx) * scale
    oy = (0 - miny) * scale
    # The origin must follow the same mirror, else the axis/boxes misalign on
    # flipped sprites.
    m0 = parsed["entries"][0].get("mirror", parsed["entries"][0]["flip"]) if parsed["entries"] else 0
    if m0 & 1:
        ox = (W * scale) - ox
    if m0 & 2:
        oy = (H * scale) - oy
    if draw_axis:
        dr = ImageDraw.Draw(img)
        dr.line([(ox, 0), (ox, H * scale)], fill=(255, 255, 0, 255))
        dr.line([(0, oy), (W * scale, oy)], fill=(255, 255, 0, 255))
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    meta = {
        "width": W * scale, "height": H * scale, "scale": scale,
        "origin_x": ox, "origin_y": oy, "bounds": [minx, miny, maxx, maxy],
        "count": parsed["count"], "piece0": parsed["piece0"],
        "base_x": parsed["base_x"], "base_y": parsed["base_y"],
        "tiles": [e["tile"] for e in parsed["entries"]],
    }
    return bio.getvalue(), meta


# ---------------- rendering ----------------

def sprite_bounds(parsed):
    """Pixel bounding box (minx,miny,maxx,maxy) covering all tiles + origin."""
    minx = miny = 0
    maxx = maxy = 1
    for e in parsed["entries"]:
        minx = min(minx, e["x"]);      miny = min(miny, e["y"])
        maxx = max(maxx, e["x"] + 16); maxy = max(maxy, e["y"] + 16)
    return minx, miny, maxx, maxy


def render_sprite(data, obj_ptr, scale=4, gfx=None, draw_axis=False,
                  bg=(16, 16, 40)):
    """Return (png_bytes, meta). meta has origin pixel coords in the output image
    so the frontend can line the sprite up with the box axis.

    Uses gfx_decode for 16x16 tiles; pen 15 transparent; grayscale ramp.
    Requires Pillow.
    """
    import io
    import gfx_decode as g
    from PIL import Image, ImageDraw
    if gfx is None:
        gfx = g.load_gfx()

    parsed = parse_obj_list(data, obj_ptr)
    minx, miny, maxx, maxy = sprite_bounds(parsed)
    W = maxx - minx
    H = maxy - miny
    scale = max(1, min(12, int(scale)))

    img = Image.new("RGBA", (W * scale, H * scale), bg + (0,))
    px = img.load()
    for e in parsed["entries"]:
        tile = g.decode_tile(e["tile"], 16, gfx=gfx)
        ox = e["x"] - minx
        oy = e["y"] - miny
        xr = range(15, -1, -1) if (e["flip"] & 1) else range(16)
        yr = range(15, -1, -1) if (e["flip"] & 2) else range(16)
        for yy, sy_ in enumerate(yr):
            for xx, sx_ in enumerate(xr):
                pen = tile[sy_][sx_]
                if pen == 15:            # transparent
                    continue
                v = int(round(pen * 255 / 15))
                for a in range(scale):
                    for b in range(scale):
                        px[(ox + xx) * scale + b, (oy + yy) * scale + a] = (v, v, v, 255)

    origin_px = (0 - minx) * scale   # x of sprite origin in the image
    origin_py = (0 - miny) * scale   # y of sprite origin in the image
    if draw_axis:
        dr = ImageDraw.Draw(img)
        dr.line([(origin_px, 0), (origin_px, H * scale)], fill=(80, 80, 200, 255))
        dr.line([(0, origin_py), (W * scale, origin_py)], fill=(80, 80, 200, 255))

    bio = io.BytesIO()
    img.save(bio, format="PNG")
    meta = {
        "width": W * scale, "height": H * scale, "scale": scale,
        "origin_x": origin_px, "origin_y": origin_py,   # sprite origin in image px
        "bounds": [minx, miny, maxx, maxy],
        "count": parsed["count"], "piece0": parsed["piece0"],
        "base_x": parsed["base_x"], "base_y": parsed["base_y"],
        "tiles": [e["tile"] for e in parsed["entries"]],
    }
    return bio.getvalue(), meta


if __name__ == "__main__":
    import sys
    data = _load()
    for name, obj in (("f0", 0x06EDE0), ("f2", 0x06EDC8)):
        p = parse_obj_list(data, obj)
        print("%s obj=0x%06X count=%d attr=0x%04x piece0=0x%04x base=(%d,%d) rec=0x%06X"
              % (name, obj, p["count"], p["attr"], p["piece0"],
                 p["base_x"], p["base_y"], p["coord_record"]))
        for e in p["entries"]:
            print("   tile 0x%05X @ (%+d,%+d) flip=%d pal=%d"
                  % (e["tile"], e["x"], e["y"], e["flip"], e["pal"]))
    out = sys.argv[1] if len(sys.argv) > 1 else None
    if out:
        png, meta = render_sprite(data, 0x06EDE0, scale=6, draw_axis=True)
        open(out, "wb").write(png)
        print("wrote", out, meta)
