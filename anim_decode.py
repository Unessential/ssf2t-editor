#!/usr/bin/env python3
"""
anim_decode.py — decode Super Street Fighter II Turbo (ssf2t) Ryu animation frames.

CPS-2 / Motorola 68000, BIG-ENDIAN. Flat offset == CPU address.
DATA bytes come from the flat data image (the opcode image has scrambled data).

Frame record = 0x18 bytes, stride 0x18. Field map (see ANIM_NOTES.md):
  +0x00 BE16 duration        (PROVEN)
  +0x02 BE16 ref/flags       (PROVEN; top bit 0x8000 = end-of-animation marker)
  +0x04 BE32 obj_ptr -> OBJ/sprite tile list (PROVEN: points at tile lists)
  +0x08 u8   vuln0 box id    (PROVEN)
  +0x09 u8   vuln1 box id    (PROVEN)
  +0x0A u8   vuln2 box id    (PROVEN)
  +0x0C u8   variant/color   (INFERRED)
  +0x0D u8   attack box id   (PROVEN)
  +0x12 u8   active/hit flag  (PROVEN read as bool)
  +0x15 u8   secondary OBJ select (PROVEN read; 0xFF sentinel)

Chaining: next = frame + 0x18. If the frame's +0x02 top bit is set, the frame is
terminal and the BE32 at frame+0x18 is the loop / next-animation pointer.
"""
import struct

import paths
DATA_PATH = paths.DATA_BIN

# --- proven anchors (flat offsets) ---
RYU_ANIM_TABLE   = 0x06EBCA   # ryu_anim_table: array of BE16 offsets
BOX_SELECTOR_TBL = 0x06ED46   # (0x34,A6): 4 BE16 subpool offsets, selector in {0,2,4,8}
FRAME_STRIDE     = 0x18

# field offsets within a frame record
F_DURATION = 0x00
F_REFFLAGS = 0x02
F_OBJPTR   = 0x04
F_VULN0    = 0x08
F_VULN1    = 0x09
F_VULN2    = 0x0A
F_VARIANT  = 0x0C
F_ATTACK   = 0x0D
F_FLAG12   = 0x12
F_OBJSEL   = 0x15

# selector values used by anim_read_boxes for each box channel
SEL_VULN0, SEL_VULN1, SEL_VULN2, SEL_ATTACK = 0, 2, 4, 8


def _be16(buf, off):
    return struct.unpack_from(">H", buf, off)[0]


def _be32(buf, off):
    return struct.unpack_from(">I", buf, off)[0]


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _s8(v):
    return v - 0x100 if v & 0x80 else v


def load_data(path=DATA_PATH):
    with open(path, "rb") as f:
        return f.read()


def subpool_addr(data, selector, selector_table=BOX_SELECTOR_TBL):
    """Resolve a box subpool base address from the selector table (PROVEN)."""
    return (selector_table + _be16(data, selector_table + selector)) & 0xFFFFFF


def read_box(data, selector, box_id, selector_table=BOX_SELECTOR_TBL):
    """Return a decoded box {val_x, val_y, rad_x, rad_y, addr, raw} for an id."""
    base = subpool_addr(data, selector, selector_table)
    off = base + box_id * 4
    raw = data[off:off + 4]
    return {
        "addr": off,
        "raw": raw.hex(),
        "val_x": _s8(raw[0]),
        "val_y": _s8(raw[1]),
        "rad_x": raw[2],
        "rad_y": raw[3],
        "empty": raw == b"\x00\x00\x00\x00",
    }


def read_frame(data, frame_off, selector_table=BOX_SELECTOR_TBL):
    """
    Read one frame record at flat offset `frame_off` from the data image.

    Returns dict with:
      box_ids:   {vuln0, vuln1, vuln2, attack}  (raw ids)
      boxes:     resolved box dicts for each id
      duration:  frame tick count
      sprite_ref: {obj_ptr (BE32), ref_flags (BE16), obj_sel (u8 +0x15)}
      terminator: bool (top bit of +0x02 set)
      next_off:  next frame offset (frame+0x18), or loop pointer if terminator
      raw:       24 raw bytes (hex)
    """
    b = data[frame_off:frame_off + FRAME_STRIDE]
    ref = _be16(b, F_REFFLAGS)
    terminator = bool(ref & 0x8000)
    ids = {
        "vuln0": b[F_VULN0],
        "vuln1": b[F_VULN1],
        "vuln2": b[F_VULN2],
        "attack": b[F_ATTACK],
    }
    boxes = {
        "vuln0": read_box(data, SEL_VULN0, ids["vuln0"], selector_table),
        "vuln1": read_box(data, SEL_VULN1, ids["vuln1"], selector_table),
        "vuln2": read_box(data, SEL_VULN2, ids["vuln2"], selector_table),
        "attack": read_box(data, SEL_ATTACK, ids["attack"], selector_table),
    }
    if terminator:
        next_off = _be32(data, frame_off + FRAME_STRIDE)  # loop / next-anim pointer
    else:
        next_off = frame_off + FRAME_STRIDE
    return {
        "offset": frame_off,
        "duration": _be16(b, F_DURATION),
        "ref_flags": ref,
        "terminator": terminator,
        "box_ids": ids,
        "boxes": boxes,
        "sprite_ref": {
            "obj_ptr": _be32(b, F_OBJPTR),
            "ref_flags": ref,
            "obj_sel": b[F_OBJSEL],
            "variant": b[F_VARIANT],
            "flag12": b[F_FLAG12],
        },
        "next_off": next_off,
        "raw": b.hex(),
    }


def anim_first_frame(data, index, anim_table=RYU_ANIM_TABLE):
    """Resolve the first-frame offset for Ryu animation `index`."""
    return (anim_table + _be16(data, anim_table + index * 2)) & 0xFFFFFF


def walk_animation(data, index, anim_table=RYU_ANIM_TABLE, max_frames=32):
    """Yield successive frames of an animation until the terminator (follows the loop once)."""
    off = anim_first_frame(data, index, anim_table)
    seen = set()
    for _ in range(max_frames):
        fr = read_frame(data, off)
        yield fr
        if fr["terminator"]:
            break
        if off in seen:
            break
        seen.add(off)
        off = fr["next_off"]


def _fmt_box(name, bid, box):
    if box["empty"]:
        return "%s=id%-2d(empty)" % (name, bid)
    return "%s=id%-2d[x=%d y=%d rx=%d ry=%d]" % (
        name, bid, box["val_x"], box["val_y"], box["rad_x"], box["rad_y"])


if __name__ == "__main__":
    data = load_data()
    print("Ryu box subpools:",
          {s: "0x%06X" % subpool_addr(data, s) for s in (0, 2, 4, 8)})
    print()
    idx = 0
    print("Ryu animation index %d (first frame @ 0x%06X), stride 0x%02X:"
          % (idx, anim_first_frame(data, idx), FRAME_STRIDE))
    for n, fr in enumerate(walk_animation(data, idx)):
        term = " TERMINATOR -> loop/next @0x%06X" % fr["next_off"] if fr["terminator"] else ""
        print("\n frame %d @0x%06X  raw=%s" % (n, fr["offset"], fr["raw"]))
        print("   duration=%d  ref_flags=0x%04X  obj_ptr=0x%06X  obj_sel=0x%02X  variant=0x%02X%s"
              % (fr["duration"], fr["ref_flags"], fr["sprite_ref"]["obj_ptr"],
                 fr["sprite_ref"]["obj_sel"], fr["sprite_ref"]["variant"], term))
        b = fr["boxes"]
        i = fr["box_ids"]
        print("   boxes: " + "  ".join([
            _fmt_box("vuln0", i["vuln0"], b["vuln0"]),
            _fmt_box("vuln1", i["vuln1"], b["vuln1"]),
            _fmt_box("vuln2", i["vuln2"], b["vuln2"]),
            _fmt_box("attack", i["attack"], b["attack"]),
        ]))
