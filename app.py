"""app.py -- SSF2T hitbox editor backend (FastAPI).

The ORIGINAL ssf2t_data.bin is loaded READ-ONLY into memory; edits go to an
in-memory WORKING copy. The original file on disk is never written.

Run:
    cd ssf2t_editor
    python3 -m pip install -r requirements.txt
    python3 -m uvicorn app:app --host 127.0.0.1 --port 8765
    open http://127.0.0.1:8765/
"""
import hashlib
import io
import os
import struct

from fastapi import FastAPI, Body
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import cps2_map
import exporters
import gfx_decode
import opcrypt

HERE = os.path.dirname(os.path.abspath(__file__))
import paths
DATA_BIN = paths.DATA_BIN

with open(DATA_BIN, "rb") as f:
    ORIGINAL = f.read()
WORKING = bytearray(ORIGINAL)
SRC_MD5 = hashlib.md5(ORIGINAL).hexdigest()

# Real player hitbox blocks (proven via player_hitbox_ptr_table @0x10026C, and
# confirmed by New Legacy diff editing the data under these pointers).
# Each block starts with 6 signed-16 relative offsets; the box reader uses
# +0x00/+0x02/+0x04 (vuln0/1/2) and +0x08 (attack); pool = block + rel.
import struct as _struct

# Player hitbox pointer table @ CPU 0x10026C (flat offset in the data image).
# 34 entries: 0-15 = new cast, 16 = Akuma, 17-32 = old versions, 33-34 = Claw
# extra pools. [PROVEN -- all entries decode to valid 5-channel blocks.]
HITBOX_PTR_TABLE = 0x10026C
_ROSTER = ["ryu", "honda", "blanka", "guile", "ken", "chunli", "zangief",
           "dhalsim", "dictator", "sagat", "boxer", "claw", "cammy", "thawk",
           "feilong", "deejay", "akuma"]


def _load_player_blocks():
    """Read all character hitbox-block pointers from the 0x10026C table."""
    blocks = {}
    for i, nm in enumerate(_ROSTER):            # 0-16 new (16 = akuma)
        ptr = _struct.unpack_from(">I", WORKING, HITBOX_PTR_TABLE + i * 4)[0]
        blocks[nm] = ptr & 0xFFFFFF
    for i, nm in enumerate(_ROSTER[:16]):       # 17-32 old versions (no akuma)
        ptr = _struct.unpack_from(">I", WORKING, HITBOX_PTR_TABLE + (17 + i) * 4)[0]
        blocks[nm + "_old"] = ptr & 0xFFFFFF
    return blocks


PLAYER_BLOCKS = _load_player_blocks()
BOX_CHANNELS = [("vuln0", 0x00), ("vuln1", 0x02), ("vuln2", 0x04),
                ("attack", 0x06), ("push", 0x08)]


def block_pools(block):
    """Resolve a hitbox block's 5 box-array pools from its header."""
    import struct
    out = {}
    for name, hoff in BOX_CHANNELS:
        rel = struct.unpack_from(">h", WORKING, block + hoff)[0]
        out[name] = (block + rel) & 0xFFFFFF
    return out


# Back-compat: default "pool" now points at new Ryu's primary vuln pool.
POOLS = {nm: block_pools(blk)["vuln0"] for nm, blk in PLAYER_BLOCKS.items()}

app = FastAPI(title="SSF2T Hitbox Editor v0")


def _clamp_s8(v):  return max(-128, min(127, int(v)))
def _clamp_u8(v):  return max(0, min(255, int(v)))


def decode_boxes(pool, count):
    boxes = []
    for i in range(count):
        o = pool + i * 4
        vx = WORKING[o]
        vy = WORKING[o + 1]
        rx = WORKING[o + 2]
        ry = WORKING[o + 3]
        boxes.append({
            "id": i,
            "flat_off": o,
            "val_x": vx - 256 if vx > 127 else vx,
            "val_y": vy - 256 if vy > 127 else vy,
            "rad_x": rx,
            "rad_y": ry,
            "raw": "%02x%02x%02x%02x" % (vx, vy, rx, ry),
            "sentinel": vx == 0x80,   # leading 0x80 marks a terminator slot
        })
    return boxes


ATTACK_STRIDE = 0x10          # attack-box entries are 16 bytes (not 4 like vuln)


def decode_attack_boxes(pool, count):
    """Attack-box pool: 16-byte entries. First 4 bytes = val_x,val_y,rad_x,rad_y
    (same box geometry as vuln/push); the next bytes carry per-box extra data
    (damage/stun/flags, format TBD). PROVEN: Ryu attack pool 0x198A2C decodes to
    real forward/up attack boxes at this stride."""
    boxes = []
    for i in range(count):
        o = pool + i * ATTACK_STRIDE
        if o + ATTACK_STRIDE > len(WORKING):
            break
        vx = WORKING[o]; vy = WORKING[o + 1]
        rx = WORKING[o + 2]; ry = WORKING[o + 3]
        extra = WORKING[o + 4:o + ATTACK_STRIDE]
        boxes.append({
            "id": i,
            "flat_off": o,
            "val_x": vx - 256 if vx > 127 else vx,
            "val_y": vy - 256 if vy > 127 else vy,
            "rad_x": rx,
            "rad_y": ry,
            "extra": extra.hex(),
            "empty": (rx == 0 and ry == 0),
        })
    return boxes


@app.get("/api/attackboxes")
def get_attackboxes(char: str = "ryu", count: int = 24):
    """Attack-box pool (hdr+0x06) for a character, decoded at the 16-byte stride."""
    block = PLAYER_BLOCKS.get(char)
    if block is None:
        return JSONResponse({"error": f"unknown char {char!r}; known: {list(PLAYER_BLOCKS)}"}, 400)
    pool = block_pools(block)["attack"]
    return {"char": char, "attack_pool": hex(pool),
            "stride": ATTACK_STRIDE, "boxes": decode_attack_boxes(pool, count)}


@app.get("/api/charboxes")
def get_charboxes(char: str = "ryu", count: int = 20):
    """Return all box channels (vuln0/1/2, attack, push) from a player block."""
    block = PLAYER_BLOCKS.get(char)
    if block is None:
        return JSONResponse({"error": f"unknown char {char!r}; known: {list(PLAYER_BLOCKS)}"}, 400)
    pools = block_pools(block)
    channels = {}
    for name, pool in pools.items():
        channels[name] = {"pool": hex(pool), "boxes": decode_boxes(pool, count)}
    return {"char": char, "block": hex(block), "channels": channels}


@app.get("/api/info")
def info():
    dirty = sum(1 for a, b in zip(ORIGINAL, WORKING) if a != b)
    return {
        "source": DATA_BIN,
        "source_md5": SRC_MD5,
        "dirty_bytes": dirty,
        "load_order": cps2_map.LOAD_ORDER,
        "pools": {k: hex(v) for k, v in POOLS.items()},
        "old_ready": sorted(ANIM_LISTS_OLD),
        "exporter_confidence": {
            "ips": "VERIFIED (targets EPROM files directly)",
            "bps": "VERIFIED (structural; correct CRC32 footer)",
            "mra": "UNVERIFIED (raw-concat offset assumption; test on hardware)",
        },
    }


@app.get("/api/boxes")
def get_boxes(pool: str = "0x06ED50", count: int = 32):
    p = POOLS.get(pool, None)
    if p is None:
        p = int(pool, 16) if isinstance(pool, str) and pool.lower().startswith("0x") else int(pool)
    return {"pool": hex(p), "boxes": decode_boxes(p, count)}


@app.post("/api/boxes")
def set_boxes(payload: dict = Body(...)):
    """payload: {"pool": "0x06ED50", "boxes": [{"id":1,"val_x":..,"val_y":..,"rad_x":..,"rad_y":..}, ...]}"""
    p = payload.get("pool", 0x06ED50)
    if isinstance(p, str):
        p = POOLS.get(p) or int(p, 16)
    for b in payload.get("boxes", []):
        o = p + int(b["id"]) * 4
        WORKING[o] = _clamp_s8(b["val_x"]) & 0xFF
        WORKING[o + 1] = _clamp_s8(b["val_y"]) & 0xFF
        WORKING[o + 2] = _clamp_u8(b["rad_x"])
        WORKING[o + 3] = _clamp_u8(b["rad_y"])
    dirty = sum(1 for a, c in zip(ORIGINAL, WORKING) if a != c)
    return {"ok": True, "dirty_bytes": dirty}


def _box_slot_ok(addr: int) -> bool:
    """True only if addr is exactly an entry in a real hitbox pool: vuln/push
    pools use 4-byte entries, the attack pool 16-byte (only the first 4 bytes are
    geometry). Keeps the editor from writing arbitrary ROM bytes."""
    for blk in list(PLAYER_BLOCKS.values()) + sorted(_proj_blocks()):
        pools = block_pools(blk)
        for name, pool in pools.items():
            stride = ATTACK_STRIDE if name == "attack" else 4
            if pool <= addr < pool + 0x100 * stride and (addr - pool) % stride == 0:
                return True
    return False


@app.post("/api/box")
def set_box(payload: dict = Body(...)):
    """Write one box's geometry by its flat address (as returned in each frame's
    boxes[].addr). payload: {addr: "0x198840" | int, val_x, val_y, rad_x, rad_y}.
    Box entries are shared by every frame that uses that id, so this edits all
    of them at once -- which is how the game stores them."""
    a = payload.get("addr")
    addr = int(a, 16) if isinstance(a, str) else int(a)
    if not _box_slot_ok(addr):
        return JSONResponse({"error": f"0x{addr:06X} is not a hitbox pool entry"}, status_code=400)
    WORKING[addr] = _clamp_s8(payload["val_x"]) & 0xFF
    WORKING[addr + 1] = _clamp_s8(payload["val_y"]) & 0xFF
    WORKING[addr + 2] = _clamp_u8(payload["rad_x"])
    WORKING[addr + 3] = _clamp_u8(payload["rad_y"])
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    vx = struct.unpack_from(">b", WORKING, addr)[0]
    vy = struct.unpack_from(">b", WORKING, addr + 1)[0]
    return {"ok": True, "dirty_bytes": dirty, "addr": "0x%06X" % addr,
            "box": {"val_x": vx, "val_y": vy, "rad_x": WORKING[addr + 2], "rad_y": WORKING[addr + 3]}}


# ---- Character stats: walk speed, dizzy thresholds ---------------------------
# Both tables are read through an address register (lea table(pc),a0 then
# (a0,dn)), so the game sees the raw ROM bytes -- the bytes the editor patches.
# Found by MAME write taps + disassembly, matching cps2recomp's ssf2t notes.
#  Walk: 0x078340 sets obj+0x30 = 0x07B912 + id*16 (id = character; Akuma 0x10;
#        old versions id+0x11). 0x004372 adds the (dx,dy) word pair indexed by
#        direction XOR facing each tick, in 1/256 px. Entry 0 = walking forward
#        (stored negative, the facing flips it), entry 1 = walking back.
#        Measured per tick for Ryu: forward +3.0 px (768), back -2.0 px (512).
#  Dizzy: stunned when the stun meter (obj+0x5E) reaches the word at 0x07F1C6 +
#        2*n, n = times already dizzied this round (obj+0x2B1). 30, 34, 35, 35...
#        Shared by every character.
WALK_TABLE = 0x07B912
DIZZY_TABLE, DIZZY_ENTRIES = 0x07F1C6, 12


def _walk_id(char: str, ver: str) -> int:
    base = char[:-4] if char.endswith("_old") else char
    if base == "akuma":
        return 0x10
    cid = _ROSTER.index(base)
    return cid + 0x11 if ver == "old" else cid


def _s16(addr):
    return struct.unpack_from(">h", WORKING, addr)[0]


def _w16(addr, value):
    struct.pack_into(">h", WORKING, addr, max(-32768, min(32767, int(value))))


# ---- Opcode-space stats (values the CPU fetches through CPS-2 decryption) ----
# Starting health: the immediate word of every `move.w #$90,...` that fills a
# health field, plus the Perfect check `cmpi.w #$90,$2a(a1)` at 0x04EA76 (so a
# full-health win is still a Perfect). obj+0x2A/+0x2C = health, obj+0x1BC = the
# bar's displayed value, which drains toward health. The bar itself clamps to
# 0x90 (9 tiles x 16), so health above 144 shows a full bar until it drops.
#   0x003EB6..0x003ED4  round start (P1/P2 +2A, +2C, +1BC)
#   0x054B5A / 0x054B86  per-player refill (button combo, test path)
HEALTH_SITES = [0x003EB8, 0x003EBE, 0x003EC4, 0x003ECA, 0x003ED0, 0x003ED6,
                0x054B5C, 0x054B62, 0x054B68, 0x054B6E,
                0x054B88, 0x054B8E, 0x054B94, 0x054B9A,
                0x04EA78]
# Per-hit stun for normal attacks: 0x07F0FA reads word pairs (stun points,
# stun-timer frames) PC-relative from 0x07F114, indexed by attack strength
# (victim obj+0x1FD: 0 light, 1 medium, 2 heavy). The path is picked by the hit
# reaction byte obj+0x55 through the jump table at 0x07F0AE: reactions 0x00,
# 0x02 (standing), 0x0A (crouching) and most others use 0x07F114; 0x06/0x08
# give no stun; 0x0C reads its own table at 0x07F13C (reaction not identified
# yet -- not seen on standing, crouching or sweep hits); 0x0E (sweep) adds
# immediates. 0x07F324 then adds three random terms (global 0x07F39A, attacker
# 0x07F3BA, defender 0x07F5BA; raw data tables). Verified in MAME: light base
# 2 -> 25 moved a standing jab's gain from 0 to 23 with identical RNG.
STUN_TABLES = {"stun": 0x07F114, "stun_rc": 0x07F13C}
STRENGTHS = ["light", "medium", "heavy"]
# Game speed (frame skip). 0x0E9904 turns frame skip on ($61CA = 1) and loads
# the skip rate $CD2 from the word table at 0x0E992C (PC-relative -> encrypted),
# indexed by the GAME SPEED config ($3A8; FREE SELECT = 4 uses the player's pick
# $CD4, +1 when region $2CE != 0). The per-tick counter at 0x0E9936 runs an
# extra logic tick each time it passes $CD3, so a lower value is faster and 255
# can never trigger (byte counter, bhi): one tick per frame, no frame skip.
# Measured in MAME (ticks per video frame): 64 -> 1.44, 112 -> 1.29 (default
# setting), 128 -> 1.26, 255 -> 1.000. Entries 0-3 are the reachable ones.
SPEED_TABLE, SPEED_ENTRIES = 0x0E992C, 4

_KEY = os.environ.get("SSF2T_KEY") or next(
    (p for p in (os.path.join(os.path.dirname(DATA_BIN), "ssf2t.key"),
                 os.path.join(os.path.dirname(HERE), "ssf2t.key")) if os.path.exists(p)), None)
OPCRYPT = opcrypt.OpCrypt(_KEY) if _KEY else None


def _health_ok():
    """Health is editable only if every site still decodes to one shared value
    (guards against a different ROM revision with other code at these offsets)."""
    if OPCRYPT is None:
        return False
    vals = {OPCRYPT.read(ORIGINAL, a) for a in HEALTH_SITES}
    return len(vals) == 1


def _stat_fields(char: str, ver: str):
    """name -> spec dict: addrs (all written, first is read), space ('raw' data
    reads / 'op' decrypted fetches), enc(display)->word, dec(word)->display,
    lo/hi bounds on the display value, scope ('char' or 'global')."""
    wid = _walk_id(char, ver)
    w = WALK_TABLE + wid * 16
    ident = (lambda v: round(v), lambda raw: raw)
    f = {
        "walk_fwd": dict(addrs=[w + 0], space="raw", enc=lambda px: -round(px * 256),
                         dec=lambda raw: -raw / 256, lo=0, hi=32, scope="char"),
        "walk_back": dict(addrs=[w + 4], space="raw", enc=lambda px: round(px * 256),
                          dec=lambda raw: raw / 256, lo=0, hi=32, scope="char"),
    }
    for n in range(DIZZY_ENTRIES):
        f[f"dizzy_{n}"] = dict(addrs=[DIZZY_TABLE + 2 * n], space="raw", enc=ident[0], dec=ident[1],
                               lo=1, hi=255, scope="global")
    # Defense: damage taken is reduced by value/32 (0x0BEE40); row = character
    # id as for walk speed, column = the level (2P versus: 16).
    f["defense"] = dict(addrs=[DEFENSE_TABLE + 32 * wid + VS_LEVEL], space="raw8", enc=ident[0],
                        dec=ident[1], lo=0, hi=31, scope="char")
    if _health_ok():
        f["health"] = dict(addrs=HEALTH_SITES, space="op", enc=ident[0], dec=ident[1],
                           lo=1, hi=0x3FFF, scope="global")
    if OPCRYPT is not None:
        for n in range(SPEED_ENTRIES):
            f[f"speed_{n}"] = dict(addrs=[SPEED_TABLE + 2 * n], space="op", enc=ident[0], dec=ident[1],
                                   lo=1, hi=255, scope="global")
        for tname, base in STUN_TABLES.items():
            for s, sname in enumerate(STRENGTHS):
                f[f"{tname}_{sname}"] = dict(addrs=[base + 4 * s], space="op", enc=ident[0],
                                             dec=ident[1], lo=0, hi=255, scope="global")
                f[f"{tname}_{sname}_time"] = dict(addrs=[base + 4 * s + 2], space="op", enc=ident[0],
                                                  dec=ident[1], lo=0, hi=999, scope="global")
    return f


def _read_word(image, addr, space):
    if space == "raw8":
        return image[addr]
    if space == "op":
        v = OPCRYPT.read(image, addr)
    else:
        v = (image[addr] << 8) | image[addr + 1]
    return v - 0x10000 if v & 0x8000 else v


def _write_word(addr, space, value):
    if space == "raw8":
        WORKING[addr] = max(0, min(255, int(value)))
        return
    v = max(-32768, min(32767, int(value))) & 0xFFFF
    if space == "op":
        OPCRYPT.write(WORKING, addr, v)
    else:
        struct.pack_into(">H", WORKING, addr, v)


@app.get("/api/stats")
def api_stats(char: str = "ryu", ver: str = "new"):
    if char not in _ROSTER:
        return JSONResponse({"error": f"unknown character {char!r}"}, status_code=400)
    out = {}
    for name, sp in _stat_fields(char, ver).items():
        addr = sp["addrs"][0]
        raw = _read_word(WORKING, addr, sp["space"])
        orig = _read_word(ORIGINAL, addr, sp["space"])
        out[name] = {"value": sp["dec"](raw), "raw": raw, "original": sp["dec"](orig),
                     "addr": "0x%06X" % addr, "sites": len(sp["addrs"]),
                     "encrypted": sp["space"] == "op", "scope": sp["scope"]}
    return {"char": char, "ver": ver, "walk_id": _walk_id(char, ver), "stats": out}


@app.post("/api/stats")
def set_stat(payload: dict = Body(...)):
    """payload: {char, ver, field, value}. Walk speeds are px per game tick
    (stored as 1/256 px); dizzy thresholds are stun points. Only whitelisted
    table entries can be written."""
    char, ver, field = payload.get("char", "ryu"), payload.get("ver", "new"), payload.get("field")
    if char not in _ROSTER:
        return JSONResponse({"error": f"unknown character {char!r}"}, status_code=400)
    fields = _stat_fields(char, ver)
    if field not in fields:
        return JSONResponse({"error": f"unknown field {field!r}"}, status_code=400)
    sp = fields[field]
    try:
        value = float(payload["value"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "value must be a number"}, status_code=400)
    if not (sp["lo"] <= value <= sp["hi"]):
        return JSONResponse({"error": f"{field} must be between {sp['lo']} and {sp['hi']}"}, status_code=400)
    for addr in sp["addrs"]:
        _write_word(addr, sp["space"], sp["enc"](value))
    raw = _read_word(WORKING, sp["addrs"][0], sp["space"])
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {"ok": True, "field": field, "value": sp["dec"](raw), "raw": raw, "dirty_bytes": dirty}


# ---- Patch the ROM in place ------------------------------------------------
# Targets in the data folder: the emulator's ROM zip, the loose EPROM files the
# BPS exporter reads, and the editor's own data image (so the editor's baseline
# matches the patched ROM). The first time a file is touched it is copied to
# <file>.orig, which is never overwritten afterwards.
ROM_DIR = os.path.dirname(DATA_BIN)
ROM_ZIP = os.path.join(ROM_DIR, "ssf2t.zip")


def _backup_once(path):
    """Copy path -> path.orig if no backup exists yet. Returns the backup path."""
    import shutil
    bak = path + ".orig"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    return bak


@app.post("/api/patch_rom")
def patch_rom(payload: dict = Body(...)):
    """Write the current edits into the ROM files. payload: {"confirm": true}.
    Refuses unless every byte about to change still holds the value the editor
    expects (so a ROM changed elsewhere is never half-patched)."""
    global ORIGINAL, SRC_MD5
    if payload.get("confirm") is not True:
        return JSONResponse({"error": "confirmation required"}, status_code=400)
    import zipfile, tempfile
    changes = exporters.diff_flat(ORIGINAL, bytes(WORKING))
    if not changes:
        return JSONResponse({"error": "no edits to write"}, status_code=400)
    groups = exporters.group_changes_by_eprom(changes)
    if not os.path.exists(ROM_ZIP):
        return JSONResponse({"error": f"ROM zip not found: {ROM_ZIP}"}, status_code=400)

    # 1. verify: ROM bytes at every target offset == the editor's original bytes
    with zipfile.ZipFile(ROM_ZIP) as z:
        members = {i.filename: i for i in z.infolist()}
        roms = {n: bytearray(z.read(n)) for n in groups if n in members}
    missing = [n for n in groups if n not in roms]
    if missing:
        return JSONResponse({"error": f"ROM zip has no {missing}"}, status_code=400)
    for flat_off, _new in changes:
        name, eoff = cps2_map.flat_to_eprom(flat_off)
        if roms[name][eoff] != ORIGINAL[flat_off]:
            return JSONResponse({"error": f"{name} at 0x{eoff:06X} does not match the editor's "
                                 "original data -- the ROM was changed elsewhere. Nothing was written."},
                                status_code=409)

    # 2. back up every file we are about to change (once, never overwritten)
    loose = [os.path.join(ROM_DIR, n) for n in groups if os.path.exists(os.path.join(ROM_DIR, n))]
    backups = [_backup_once(p) for p in [ROM_ZIP, DATA_BIN] + loose]

    # 3. patch the EPROM images and rebuild the zip (temp file, then atomic swap)
    for name, ch in groups.items():
        for off, byte in ch:
            roms[name][off] = byte
    fd, tmp = tempfile.mkstemp(dir=ROM_DIR, suffix=".zip.tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(ROM_ZIP) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                body = bytes(roms[info.filename]) if info.filename in roms else src.read(info.filename)
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = zipfile.ZIP_DEFLATED
                dst.writestr(zi, body)
        os.replace(tmp, ROM_ZIP)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    # 4. loose EPROM files (BPS export source) and the editor's data image
    for p in loose:
        with open(p, "r+b") as fh:
            for off, byte in groups[os.path.basename(p)]:
                fh.seek(off); fh.write(bytes([byte]))
    with open(DATA_BIN, "r+b") as fh:
        for flat_off, byte in changes:
            fh.seek(flat_off); fh.write(bytes([byte]))

    # 5. the patched ROM is the new baseline
    ORIGINAL = bytes(WORKING)
    SRC_MD5 = hashlib.md5(ORIGINAL).hexdigest()
    return {"ok": True, "bytes_written": len(changes), "rom_files": sorted(groups),
            "files_patched": [ROM_ZIP, DATA_BIN] + loose, "backups": backups, "dirty_bytes": 0}


@app.post("/api/restore_rom")
def restore_rom(payload: dict = Body(...)):
    """Copy every <file>.orig in the data folder back over its file and reload.
    payload: {"confirm": true}. Unsaved edits are discarded."""
    global ORIGINAL, WORKING, SRC_MD5
    if payload.get("confirm") is not True:
        return JSONResponse({"error": "confirmation required"}, status_code=400)
    import shutil
    restored = []
    for fn in sorted(os.listdir(ROM_DIR)):
        if fn.endswith(".orig"):
            shutil.copy2(os.path.join(ROM_DIR, fn), os.path.join(ROM_DIR, fn[:-5]))
            restored.append(fn[:-5])
    if not restored:
        return JSONResponse({"error": "no .orig backups found -- the ROM has not been patched by the editor"},
                            status_code=400)
    with open(DATA_BIN, "rb") as fh:
        ORIGINAL = fh.read()
    WORKING = bytearray(ORIGINAL)
    SRC_MD5 = hashlib.md5(ORIGINAL).hexdigest()
    return {"ok": True, "restored": restored, "dirty_bytes": 0}


@app.post("/api/reload")
def reload_working():
    global WORKING
    WORKING = bytearray(ORIGINAL)
    return {"ok": True, "dirty_bytes": 0}


@app.post("/api/export")
def export(payload: dict = Body(...)):
    fmt = payload.get("format", "ips").lower()
    changes = exporters.diff_flat(ORIGINAL, bytes(WORKING))
    if not changes:
        return JSONResponse({"error": "no changes to export"}, status_code=400)

    if fmt == "mra":
        mra = exporters.build_mra(changes, src_md5="none")
        return StreamingResponse(
            io.BytesIO(mra.encode()),
            media_type="application/xml",
            headers={"Content-Disposition": 'attachment; filename="ssf2t_hitbox_edit.mra"'},
        )

    if fmt not in ("ips", "bps"):
        return JSONResponse({"error": "unknown format %r" % fmt}, status_code=400)
    groups = exporters.group_changes_by_eprom(changes)

    def one_patch(name, ch):
        if fmt == "ips":
            return exporters.build_ips(ch)
        # BPS: build the target EPROM image from the original EPROM bytes + changes.
        src = open(os.path.join(os.path.dirname(DATA_BIN), name), "rb").read()
        tgt = bytearray(src)
        for off, byte in ch:
            tgt[off] = byte
        return exporters.build_bps(src, bytes(tgt))

    if len(groups) == 1:
        name, ch = next(iter(groups.items()))
        blob, fn, mt = one_patch(name, ch), "patch_%s.%s" % (name, fmt), "application/octet-stream"
    else:
        # Edits span several ROM files: one patch per file, zipped. (Previously
        # only the first file's patch was returned and the rest were lost.)
        import zipfile
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
            for name, ch in sorted(groups.items()):
                z.writestr("patch_%s.%s" % (name, fmt), one_patch(name, ch))
        blob, fn, mt = bio.getvalue(), "ssf2t_patches_%s.zip" % fmt, "application/zip"

    return StreamingResponse(
        io.BytesIO(blob),
        media_type=mt,
        headers={
            "Content-Disposition": 'attachment; filename="%s"' % fn,
            "X-EPROMs-Changed": ",".join(sorted(groups)),
        },
    )


# ---------------------------------------------------------------------------
# CPS-2 graphics (tile) viewer -- v1a. Decodes the sfx.*m mask ROMs into PNGs.
# Read-only: never touches ssf2t_data.bin or the ROMs.
# ---------------------------------------------------------------------------

@app.get("/api/tile")
def api_tile(index: int = 0, size: int = 16, scale: int = 8):
    """Return a single CPS-2 tile as a scaled-up PNG (false-colour grayscale)."""
    size = 16 if int(size) != 8 else 8
    scale = max(1, min(32, int(scale)))
    png = gfx_decode.render_tile_png(int(index), scale=scale, size=size)
    return StreamingResponse(io.BytesIO(png), media_type="image/png")


@app.get("/api/tilesheet")
def api_tilesheet(start: int = 0, count: int = 256, cols: int = 16,
                  scale: int = 2, size: int = 16):
    """Return a montage PNG of `count` tiles starting at `start`."""
    size = 16 if int(size) != 8 else 8
    count = max(1, min(4096, int(count)))
    cols = max(1, min(64, int(cols)))
    scale = max(1, min(8, int(scale)))
    png = gfx_decode.render_sheet_png(int(start), count=count, cols=cols,
                                      scale=scale, size=size)
    return StreamingResponse(io.BytesIO(png), media_type="image/png")


@app.get("/api/gfxinfo")
def api_gfxinfo():
    """Metadata for the Tiles panel."""
    return {
        "gfx_size": gfx_decode.GFX_SIZE,
        "tile16_bytes": gfx_decode.TILE16_BYTES,
        "max_tile16": gfx_decode.GFX_SIZE // gfx_decode.TILE16_BYTES,
        "note": "false-colour grayscale; real palettes not wired (v1a)",
        "ryu_ken_art_range": "tiles 0x000-0x0bff (sprites); 0x8000+ = font/text",
    }


try:
    import anim_decode
    _HAS_ANIM = True
except Exception:
    _HAS_ANIM = False

try:
    import obj_decode
    _HAS_OBJ = True
except Exception:
    _HAS_OBJ = False


@app.get("/api/anim")
def get_anim(index: int = 0, max_frames: int = 32):
    """Return the frames of a Ryu animation with per-frame RESOLVED boxes,
    read live from the WORKING copy so edits show up in the overlay.

    Box channels: vuln0/1/2 (vulnerable), attack. Each resolved box carries
    its real val_x/val_y/rad_x/rad_y and the flat address of its 4 bytes
    (so the overlay can map a dragged box back to an editable pool slot).
    """
    if not _HAS_ANIM:
        return JSONResponse({"error": "anim_decode unavailable"}, status_code=501)
    data = bytes(WORKING)
    frames = []
    for fr in anim_decode.walk_animation(data, index, max_frames=max_frames):
        frames.append({
            "offset": fr["offset"],
            "duration": fr["duration"],
            "terminator": fr["terminator"],
            "obj_ptr": fr["sprite_ref"]["obj_ptr"],
            "box_ids": fr["box_ids"],
            "boxes": {
                ch: {**fr["boxes"][ch], "channel": ch}
                for ch in ("vuln0", "vuln1", "vuln2", "attack")
            },
        })
    return {"index": index, "anim_table": hex(anim_decode.RYU_ANIM_TABLE),
            "frame_count": len(frames), "frames": frames}


# ---------------------------------------------------------------------------
# Assembled frame sprite (OBJ list -> composed 16x16 tiles), origin-aligned.
# Read-only. The sprite origin (0,0) == the hitbox axis; its pixel location in
# the returned image is reported in response headers X-Origin-X / X-Origin-Y
# (and X-Sprite-W / X-Sprite-H) so the frontend can line boxes up on the body.
# ---------------------------------------------------------------------------

def _sprite_png_response(obj_ptr, scale, axis):
    data = bytes(WORKING)
    png, meta = obj_decode.render_sprite(data, obj_ptr, scale=scale,
                                         draw_axis=axis)
    headers = {
        "X-Origin-X": str(meta["origin_x"]),
        "X-Origin-Y": str(meta["origin_y"]),
        "X-Sprite-W": str(meta["width"]),
        "X-Sprite-H": str(meta["height"]),
        "X-Scale": str(meta["scale"]),
        "X-Obj-Ptr": "0x%06X" % (obj_ptr & 0xFFFFFF),
        "X-Tile-Count": str(meta["count"]),
        "Access-Control-Expose-Headers":
            "X-Origin-X,X-Origin-Y,X-Sprite-W,X-Sprite-H,X-Scale,X-Obj-Ptr,X-Tile-Count",
    }
    return StreamingResponse(io.BytesIO(png), media_type="image/png",
                             headers=headers)


# ---------------------------------------------------------------------------
# Character body animation (NEW: uses live-traced anim list + body OBJ format)
# ---------------------------------------------------------------------------
RYU_ANIM_LIST = 0x1121A2   # LIVE-VERIFIED anim stream start
# Per-character animation-list start addresses. Only Ryu is live-verified so far
# (read from 0xFF8468 in FBNeo). The anim entry is code-driven per character (set
# by anim_set_animation from 84 sites), so there is NO simple table to index --
# each character's start must be captured live or traced. Add entries here as
# they are confirmed; unmapped characters return a clear 404 from /api/charanim.
ANIM_LISTS = {
    # Start of each character's anim list == start of its IDLE loop, so anim 0
    # is always the idle stance. Derived from the idle loop's own loop pointer
    # (the 4-byte target after the 0x8000-terminated frame): a live anim_ptr
    # capture can land mid-loop, but the loop target is always the idle start.
    # Earlier values for guile/chunli/dhalsim/dictator/sagat/cammy/deejay were
    # mid-loop captures, which shifted every anim index for those characters.
    # char_id in comment.
    "ryu": 0x1121A2,       # 0
    "honda": 0x119CCE,     # 1
    "blanka": 0x122A3E,    # 2
    "guile": 0x12B228,     # 3   (was 0x12B288, mid-idle)
    "ken": 0x1339F4,       # 4
    "chunli": 0x13C458,    # 5   (was 0x13C470, mid-idle)
    "zangief": 0x144F24,   # 6
    "dhalsim": 0x14E0E2,   # 7   (was 0x14E0FA, mid-idle)
    "dictator": 0x155A28,  # 8   (was 0x155A58, mid-idle)
    "sagat": 0x15CC66,     # 9   (was 0x15CCAE, mid-idle)
    "boxer": 0x16342E,     # 10  (new: idle loop start from roster capture)
    "claw": 0x16A84E,      # 11  (new)
    "cammy": 0x171E54,     # 12  (was 0x171E6C, mid-idle)
    "thawk": 0x179622,     # 13  (new)
    "feilong": 0x180DC4,   # 14  (new)
    "deejay": 0x188AE0,    # 15  (was 0x188B70, mid-idle)
    # akuma(16) not captured.
}
IDLE_ANIM_INDEX = 0        # anim 0 is the idle loop for every entry above
# Old (Super SF2) versions: their own anim lists have not been captured yet, so
# the animation endpoints refuse ver=old instead of pairing new-version frames
# with old-version boxes. Fill this in (char -> list start) once captured.
# Old (SSF2) versions: captured headless in MAME by holding P1's old-version
# flag (obj+0x3B6, read at 0x078324) set through the VS screen, then following
# the standing animation to its loop pointer. Every capture loaded the hitbox
# block the ROM lists for that old version (pointer table entries 17-32), so
# these starts belong to the old characters.
ANIM_LISTS_OLD = {
    "ryu": 0x1A970C, "honda": 0x1B0670, "blanka": 0x1B88F6, "guile": 0x1C0636,
    "ken": 0x1C8076, "chunli": 0x1CFBEE, "zangief": 0x1D7DC0, "dhalsim": 0x1E0428,
    "dictator": 0x1E7632, "sagat": 0x1EE24C, "boxer": 0x1F408C, "claw": 0x1FAE22,
    "cammy": 0x201C42, "thawk": 0x208F9E, "feilong": 0x2100D6, "deejay": 0x21759A,
}


def _anim_start(char: str, ver: str):
    return (ANIM_LISTS_OLD if ver == "old" else ANIM_LISTS).get(char)


def _char_block(char: str, ver: str):
    return PLAYER_BLOCKS.get(char + "_old" if ver == "old" else char, RYU_HITBOX_BLOCK)


def _old_not_ready(char: str, ver: str):
    if ver == "old" and char not in ANIM_LISTS_OLD:
        return JSONResponse({"error": f"old-version animations for {char!r} are not captured yet",
                             "old_ready": sorted(ANIM_LISTS_OLD)}, status_code=404)
    return None
RYU_HITBOX_BLOCK = 0x198832
_RYU_VULN_POOLS = [0x19883C, 0x198920, 0x1989A0]
_RYU_ATK_POOL   = 0x198A2C   # hdr+0x06 = real ATTACK (hitbox) pool
_RYU_PUSH_POOL  = 0x198DEC   # hdr+0x08 = PUSH (collision) pool -- was mislabeled "attack"

def _parse_anim_stream(data, start, max_frames=30):
    """Walk one animation from start (0x18-stride frame records, term flag 0x8000)."""
    frames = []; cur = start
    for _ in range(max_frames):
        dur = struct.unpack_from(">H", data, cur)[0]
        fl  = struct.unpack_from(">H", data, cur + 2)[0]
        obj = struct.unpack_from(">I", data, cur + 4)[0]
        # Frame-record box id bytes (0x18-byte ROM record). Offsets confirmed
        # against the pof/Dammit SSF2X live reader (pof-ssf2x-training2020.lua
        # box_list) AND verified byte-for-byte on captured Ryu moves:
        #   +0x08/09/0A = vuln0/1/2 ids
        #   +0x0C       = ATTACK id (into the 16-byte-stride attack pool, hdr+0x06);
        #                 nonzero only on a move's active frame (Strong Punch +0x0C=36
        #                 on the extend frame, 0 on windup/recovery -- proven).
        #   +0x0D       = PUSH id (collision pool, hdr+0x08; consistently populated).
        v0, v1, v2 = data[cur+8], data[cur+9], data[cur+0xA]
        attack = data[cur+0x0C]
        push = data[cur+0x0D]
        frames.append({"offset": cur, "dur": dur, "flags": fl, "obj_ptr": obj,
                        "vuln_ids": [v0, v1, v2], "attack_id": attack,
                        "push_id": push})
        if fl & 0x8000:
            break
        cur += 0x18
    return frames

def _sprite_extent(data, obj_ptr):
    """(top, bottom) of a frame's body sprite in game px relative to the origin:
    top = px above the origin, bottom = px below. Lets the viewer fit tall
    characters (Sagat, Claw) and high jumps without cutting off heads."""
    try:
        p = obj_decode.parse_body_obj_list(data, obj_ptr & 0xFFFFFF)
        ys = [e["y"] for e in p["entries"]]
        if ys:
            return -min(ys), max(ys) + 16
    except Exception:
        pass
    return 0, 0


def _resolve_box(data, pool, bid):
    b = pool + bid * 4
    vx = struct.unpack_from(">b", data, b)[0]
    vy = struct.unpack_from(">b", data, b + 1)[0]
    return {"val_x": vx, "val_y": vy, "rad_x": data[b+2], "rad_y": data[b+3],
            "addr": "0x%06X" % b}


def _resolve_attack_box(data, pool, bid):
    """Attack boxes live in a 16-byte-stride pool (hdr+0x06), unlike the 4-byte
    vuln/push pools. First 4 bytes are the box geometry; the remaining 12 bytes
    carry per-box extra data (hit-spark/sound class etc.). id indexes by 0x10."""
    b = pool + bid * ATTACK_STRIDE
    vx = struct.unpack_from(">b", data, b)[0]
    vy = struct.unpack_from(">b", data, b + 1)[0]
    return {"val_x": vx, "val_y": vy, "rad_x": data[b+2], "rad_y": data[b+3],
            "extra": data[b+4:b+ATTACK_STRIDE].hex(), "addr": "0x%06X" % b}

@app.get("/api/charanim")
def api_charanim(anim: int = 0, max_frames: int = 30, char: str = "ryu", ver: str = "new"):
    """Walk a character's Nth animation. Only characters with a known anim-list
    start (live-verified) are supported; others return a clear 'unmapped' error
    rather than wrong data. Boxes are resolved from THAT character's pools."""
    _nr = _old_not_ready(char, ver)
    if _nr is not None:
        return _nr
    data = bytes(WORKING)
    start = _anim_start(char, ver)
    if start is None:
        return JSONResponse({"error": f"anim list not mapped for {char!r}",
                             "mapped": sorted(ANIM_LISTS)}, status_code=404)
    block = _char_block(char, ver)
    pools = block_pools(block)
    vuln_pools = [pools["vuln0"], pools["vuln1"], pools["vuln2"]]
    push_pool = pools["push"]
    # Seek the Nth animation in the stream
    cur = start
    for n in range(anim):
        while True:
            fl = struct.unpack_from(">H", data, cur + 2)[0]
            if fl & 0x8000:
                cur += 0x18 + 4  # skip term frame + 4-byte loop ptr
                break
            cur += 0x18
    frames = _parse_anim_stream(data, cur, max_frames)
    result = []
    for f in frames:
        boxes = {}
        for i, (name, pool) in enumerate(zip(
                ["vuln0","vuln1","vuln2"], vuln_pools)):
            boxes[name] = _resolve_box(data, pool, f["vuln_ids"][i])
        boxes["push"] = _resolve_box(data, push_pool, f["push_id"])
        # Attack box: id at frame+0x0C into the 16-byte-stride attack pool
        # (hdr+0x06). id 0 = no active hitbox this frame (windup/recovery).
        if f.get("attack_id"):
            boxes["attack"] = _resolve_attack_box(data, pools["attack"],
                                                  f["attack_id"])
        top, bot = _sprite_extent(data, f["obj_ptr"])
        result.append({**f, "boxes": boxes, "spr_top": top, "spr_bot": bot})
    return {"anim": anim, "char": char, "start": "0x%06X" % cur,
            "frame_count": len(result), "frames": result}


@app.get("/api/animlist")
def api_animlist(char: str = "ryu", max_anims: int = 64, ver: str = "new"):
    """List a character's anims for the Animation-tab dropdown: index, frame
    count and a label from anim_labels.json (drafts end in '?'; unlabeled
    indices come back as 'anim N'). Stops at the first index whose frames do
    not point at plausible OBJ data, so trailing junk is not offered."""
    _nr = _old_not_ready(char, ver)
    if _nr is not None:
        return _nr
    import json
    start = _anim_start(char, ver)
    if start is None:
        return JSONResponse({"error": f"anim list not mapped for {char!r}",
                             "mapped": sorted(ANIM_LISTS)}, status_code=404)
    try:
        # old versions have their own anim lists, so their labels live under <char>_old
        labels = json.load(open(os.path.join(HERE, "anim_labels.json"))).get(
            char + "_old" if ver == "old" else char, {})
    except Exception:
        labels = {}
    data = bytes(WORKING)
    out, cur = [], start
    for n in range(max_anims):
        if cur + 0x18 > len(data):
            break
        frames = _parse_anim_stream(data, cur, 64)
        if not frames or not all(0x100000 <= (f["obj_ptr"] & 0xFFFFFF) < len(data)
                                 for f in frames):
            break
        out.append({"index": n, "frames": len(frames),
                    "label": labels.get(str(n), f"anim {n}"),
                    "labeled": str(n) in labels})
        last = frames[-1]
        cur = last["offset"] + (0x18 + 4 if last["flags"] & 0x8000 else 0x18)
        if not (last["flags"] & 0x8000):
            break                      # ran past max frames without a terminator
    return {"char": char, "count": len(out), "anims": out}


# ---- Captured attack animations (from ROSTER_WALK live capture, hit-cleaned) ----
# attack_anims.json maps char_id -> move -> [clean frame anim_ptrs]. Each listed
# address is a 0x18 frame record (same format as the idle lists), so we parse it
# with the SAME frame/box logic as /api/charanim. This is the honest state of the
# data: 14 characters captured today; honda(1) and chunli(5) were skipped by a
# select-cursor double-step and will be filled from a future ROSTER_WALK6 run.
_ATTACK_ANIMS = None
def _load_attack_anims():
    global _ATTACK_ANIMS
    if _ATTACK_ANIMS is None:
        import json
        path = os.path.join(os.path.dirname(__file__), "attack_anims.json")
        try:
            _ATTACK_ANIMS = json.load(open(path))
        except Exception:
            _ATTACK_ANIMS = {"names": {}, "moves": {}}
    return _ATTACK_ANIMS


@app.get("/api/attackmoves")
def api_attackmoves(char: str = "ryu", ver: str = "new"):
    """List which captured attack moves exist for a character (for the UI dropdown).
    Returns the move names in canonical order, or an 'uncaptured' note."""
    _nr = _old_not_ready(char, ver)
    if _nr is not None:
        return _nr
    aa = _load_attack_anims()
    # map char name -> cid
    cid = None
    for c, nm in aa.get("names", {}).items():
        if nm == char:
            cid = c
            break
    # old versions keep their own captures under "<cid>_old" (never the new
    # version's frames paired with old boxes)
    key = None if cid is None else (cid + "_old" if ver == "old" else cid)
    if key is None or key not in aa.get("moves", {}):
        return JSONResponse(
            {"error": (f"old-version moves for {char!r} are not captured yet" if ver == "old"
                       else f"no captured attack data for {char!r}")},
            status_code=404)
    moves = [m for m in aa["moves"][key].keys() if m != "idle"]
    return {"char": char, "cid": int(cid), "moves": moves}


@app.get("/api/attackanim")
def api_attackanim(char: str = "ryu", move: str = "stand_Weak Punch", ver: str = "new"):
    """Walk ONE captured attack move: parse each clean frame address as a 0x18
    frame record and resolve its boxes (incl. the real attack channel) from this
    character's pools. Same frame shape as /api/charanim so the UI renders it
    identically."""
    _nr = _old_not_ready(char, ver)
    if _nr is not None:
        return _nr
    data = bytes(WORKING)
    aa = _load_attack_anims()
    cid = None
    for c, nm in aa.get("names", {}).items():
        if nm == char:
            cid = c
            break
    key = None if cid is None else (cid + "_old" if ver == "old" else cid)
    if key is None or key not in aa.get("moves", {}) or move not in aa["moves"][key]:
        return JSONResponse(
            {"error": f"no captured frames for {char!r} / {move!r}"
                      + (" (old version)" if ver == "old" else "")},
            status_code=404)
    frame_addrs = [int(x, 16) for x in aa["moves"][key][move]]
    pools = block_pools(_char_block(char, ver))
    result = _frames_from_addrs(data, frame_addrs, pools)
    return {"char": char, "cid": int(cid), "move": move,
            "frame_count": len(result), "frames": result,
            "attack_pool": "0x%06X" % pools["attack"],
            "note": "attack-box id read from frame+0x0C (pof box_list, byte-verified); "
                    "nonzero only on active frames, resolved from the 16-byte attack pool."}


def _frames_from_addrs(data, frame_addrs, pools):
    """0x18-byte frame records at frame_addrs -> UI frames with boxes resolved
    from `pools` (a hitbox block's 5 pools: a character's, or a projectile's)."""
    vuln_pools = [pools["vuln0"], pools["vuln1"], pools["vuln2"]]
    push_pool = pools["push"]
    atk_pool = pools["attack"]
    result = []
    for addr in frame_addrs:
        dur = struct.unpack_from(">H", data, addr)[0]
        fl = struct.unpack_from(">H", data, addr + 2)[0]
        obj = struct.unpack_from(">I", data, addr + 4)[0]
        v0, v1, v2 = data[addr + 8], data[addr + 9], data[addr + 0xA]
        attack = data[addr + 0x0C]
        push = data[addr + 0x0D]
        boxes = {
            "vuln0": _resolve_box(data, vuln_pools[0], v0),
            "vuln1": _resolve_box(data, vuln_pools[1], v1),
            "vuln2": _resolve_box(data, vuln_pools[2], v2),
            "push": _resolve_box(data, push_pool, push),
        }
        # Attack box per frame: id at +0x0C into the 16-byte attack pool. Nonzero
        # only on the move's active frame(s). Confirmed vs pof box_list + bytes.
        if attack:
            boxes["attack"] = _resolve_attack_box(data, atk_pool, attack)
        top, bot = _sprite_extent(data, obj)
        result.append({"offset": addr, "dur": dur, "flags": fl, "obj_ptr": obj,
                        "vuln_ids": [v0, v1, v2], "attack_id": attack,
                        "push_id": push, "boxes": boxes,
                        "spr_top": top, "spr_bot": bot})
    return result


# ---- Frame durations (frame data) ---------------------------------------------
# Frame record +0x00 is how many game ticks the frame is shown: 0x002ED4 loads it
# into obj+0x18 when the frame starts, 0x002EE2 decrements it once per tick and
# moves to the next 0x18-byte record when it reaches 0. The record is read
# through an address register, so it is raw data. A duration of 0 wraps the
# timer (held until code changes the animation), so it is never written.
# Boxes are per record, so changing a duration keeps them in step. Records can
# be shared by several animations; editing one changes all of them.
_FRAME_USERS = None


def _frame_users():
    """offset -> [animation names] for every frame record the editor can show:
    anim lists (new + old), captured moves, projectiles. Built from ORIGINAL so
    it never depends on edits."""
    global _FRAME_USERS
    if _FRAME_USERS is not None:
        return _FRAME_USERS
    users = {}

    def add(off, name):
        users.setdefault(off, [])
        if name not in users[off]:
            users[off].append(name)
    data = bytes(ORIGINAL)
    for lists, ver in ((ANIM_LISTS, "new"), (ANIM_LISTS_OLD, "old")):
        for char, start in lists.items():
            cur = start
            for n in range(80):
                if cur + 0x18 > len(data):
                    break
                fr = _parse_anim_stream(data, cur, 64)
                if not fr or not all(0x100000 <= (f["obj_ptr"] & 0xFFFFFF) < len(data) for f in fr):
                    break
                for f in fr:
                    add(f["offset"], f"{char} ({ver}) anim {n}")
                last = fr[-1]
                if not (last["flags"] & 0x8000):
                    break
                cur = last["offset"] + 0x18 + 4
    aa = _load_attack_anims()
    for cid, moves in aa.get("moves", {}).items():
        base = cid[:-4] if cid.endswith("_old") else cid
        char = aa.get("names", {}).get(base, cid) + (" (old)" if cid.endswith("_old") else "")
        for mv, addrs in moves.items():
            for a in addrs:
                add(int(a, 16), f"{char} {mv}")
    for char, mv in _load_proj().items():
        for m, st in mv.items():
            for s, e in st.items():
                for a in e["anims"]:
                    add(int(a, 16), f"{char} {m} projectile ({s})")
    _FRAME_USERS = users
    return users


@app.get("/api/frameinfo")
def api_frameinfo(offset: str):
    off = int(offset, 16) if offset.lower().startswith("0x") else int(offset)
    u = _frame_users().get(off)
    if u is None:
        return JSONResponse({"error": f"0x{off:06X} is not a known frame record"}, status_code=404)
    dur = struct.unpack_from(">H", WORKING, off)[0]
    orig = struct.unpack_from(">H", ORIGINAL, off)[0]
    return {"offset": "0x%06X" % off, "dur": dur, "original": orig, "users": u,
            "editable": orig != 0}


@app.post("/api/framedur")
def api_framedur(payload: dict = Body(...)):
    """payload: {offset, dur} -- ticks this frame is shown (1-255)."""
    a = payload.get("offset")
    off = int(a, 16) if isinstance(a, str) else int(a)
    if off not in _frame_users():
        return JSONResponse({"error": f"0x{off:06X} is not a known frame record"}, status_code=400)
    if struct.unpack_from(">H", ORIGINAL, off)[0] == 0:
        return JSONResponse({"error": "this frame is held by game code (duration 0), so its length "
                             "isn't set here"}, status_code=400)
    try:
        dur = int(payload["dur"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "duration must be a whole number of ticks"}, status_code=400)
    if not (1 <= dur <= 255):
        return JSONResponse({"error": "duration must be between 1 and 255 ticks"}, status_code=400)
    struct.pack_into(">H", WORKING, off, dur)
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {"ok": True, "offset": "0x%06X" % off, "dur": dur, "dirty_bytes": dirty,
            "users": _frame_users()[off]}


# ---- Moving specials (velocity / slowdown) ------------------------------------
# A moving special sets the player's velocity obj+0x3C/+0x3E (x/y, 1/256 px per
# tick) and slowdown obj+0x40/+0x42; the per-tick mover at 0x002F50 does
# v -= slowdown, then position += v. The specials read their starting values
# PC-relative (encrypted) from per-strength tables; found by MAME write taps on
# obj+0x3C..0x43 + disassembly, and confirmed by patching (Honda LP 1536->512:
# travel 113.6 -> 37.6 px; Fei LP rekka 896->300: v=300 in the capture).
# Slowdown keeps applying after the speed reaches 0, so a low speed with the
# same slowdown makes the move drift backwards.
MOVE_PHYSICS = {
    # Sumo Headbutt: 0x081F5C move.w tbl(pc,d0),$3c(a6), d0 = strength*2. Slowdown 0.
    ("honda", "Sumo Headbutt"): lambda s: [("speed", "speed", 0x081F32 + 2 * s)],
    # Spiral Arrow: 0x0934D8.. 4 words per strength (vx, ax, vy, ay), d0 = $99*4.
    ("cammy", "Spiral Arrow"): lambda s: [
        ("speed", "speed", 0x093502 + 8 * s), ("slowdown", "slowdown", 0x093504 + 8 * s),
        ("rise", "rise speed", 0x093506 + 8 * s), ("rise_slow", "rise slowdown", 0x093508 + 8 * s)],
    # Rekka Ken: 0x096708.. (vx, ax) per strength (16 bytes) and rekka hit 1-3 (4 bytes).
    ("feilong", "Rekka Ken"): lambda s: [
        f for h in range(3) for f in (
            (f"hit{h + 1}_speed", f"hit {h + 1} speed", 0x09674C + 16 * s + 4 * h),
            (f"hit{h + 1}_slowdown", f"hit {h + 1} slowdown", 0x09674E + 16 * s + 4 * h))],
}


# move_physics.json (build_move_physics.py + verify_move_physics.py): every
# special/super of 15 characters, captured in MAME with a write tap on the
# velocity words, resolved to the ROM word each setter reads, and VERIFIED by
# patching each address +1 and seeing the setter write the new value. The
# hand-mapped entries above remain as a fallback (Fei Long's Rekka Ken crashes
# MAME's write tap, so it is only in the hand table).
_MOVE_JSON = None


def _move_json():
    global _MOVE_JSON
    if _MOVE_JSON is None:
        import json
        try:
            _MOVE_JSON = json.load(open(os.path.join(HERE, "move_physics.json")))
        except Exception:
            _MOVE_JSON = {}
    return _MOVE_JSON


def _strength_index(strength: str):
    w = (strength or "").split(" ")[0].lower()
    return {"weak": 0, "medium": 1, "strong": 2}.get(w)


def _move_phys_fields(char, move, strength, ver):
    """[(key, label, addr, space, shared_with)] for one move and strength, or None.
    Old versions live under "<char>_old" in move_physics.json (verified the same way)."""
    if OPCRYPT is None:
        return None
    fl = _move_json().get(char + "_old" if ver == "old" else char, {}).get(move, {}).get(strength)
    if fl:
        return [(f["key"], f["label"], int(f["addr"], 16), f["space"], f.get("shared_with", []))
                for f in fl]
    if ver != "new":
        return None
    fn = MOVE_PHYSICS.get((char, move))
    s = _strength_index(strength)
    if fn is None or s is None:
        return None
    return [(k, l, a, "op", []) for k, l, a in fn(s)]


def _phys_word(image, addr, space="op"):
    v = OPCRYPT.read(image, addr) if space == "op" else struct.unpack_from(">H", image, addr)[0]
    return v - 0x10000 if v & 0x8000 else v


@app.get("/api/movephys")
def api_movephys(char: str, move: str, strength: str, ver: str = "new"):
    """Starting speed/slowdown for one moving special and strength, in px per tick
    (raw values are 1/256 px). 404 if this move's movement isn't mapped."""
    fields = _move_phys_fields(char, move, strength, ver)
    if fields is None:
        return JSONResponse({"error": "movement not mapped for this move"}, status_code=404)
    out = []
    for key, label, addr, space, shared in fields:
        raw, orig = _phys_word(WORKING, addr, space), _phys_word(ORIGINAL, addr, space)
        out.append({"key": key, "label": label, "addr": "0x%06X" % addr, "encrypted": space == "op",
                    "value": raw / 256, "original": orig / 256, "raw": raw, "shared_with": shared})
    return {"char": char, "move": move, "strength": strength, "fields": out}


@app.post("/api/movephys")
def set_movephys(payload: dict = Body(...)):
    """payload: {char, move, strength, ver, key, value} -- value in px per tick."""
    fields = _move_phys_fields(payload.get("char"), payload.get("move"), payload.get("strength"),
                               payload.get("ver", "new"))
    if fields is None:
        return JSONResponse({"error": "movement not mapped for this move"}, status_code=400)
    match = [f for f in fields if f[0] == payload.get("key")]
    if not match:
        return JSONResponse({"error": "unknown field"}, status_code=400)
    try:
        value = float(payload["value"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "value must be a number"}, status_code=400)
    lim = 8 if "slow" in match[0][0] else 64
    if not (-lim <= value <= lim):
        return JSONResponse({"error": f"value must be between -{lim} and {lim} px per tick"}, status_code=400)
    _key, _label, addr, space, _shared = match[0]
    word = round(value * 256) & 0xFFFF
    if space == "op":
        OPCRYPT.write(WORKING, addr, word)
    else:
        struct.pack_into(">H", WORKING, addr, word)
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {"ok": True, "key": match[0][0], "value": _phys_word(WORKING, addr, space) / 256, "dirty_bytes": dirty}


# ---- Damage -------------------------------------------------------------------
# Traced from the hit routine (0x0BE5FC..0x0BE646, `sub.w d6,$2a(a2)`), a3 = the
# attacker's 16-byte attack-box record, a6 = attacker, a2 = defender:
#   0x0BED38  base   = DAMAGE_TABLE[class*32 + level]   class = box byte 4 & 0x3F,
#             level = attacker obj+0x58 (2P versus: 16; vs the CPU it follows
#             difficulty / stage, $C52). Region word $2CE in {2,4,6,8} (this
#             ROM: 4) reads 0x24E614, other regions 0x24E834 (higher classes lower).
#   0x0BEE40  + RANDOM_TABLE[row*32 + rand(0..31)]   row = box byte 9 while the
#             attacker has >= 60 health, else byte 10; then minus
#             total * DEFENSE[defender][level] / 32, minimum 1
#   0x0BEE80  defender below 31 health: a further reduction (0xE7D96)
# Verified in MAME: Ken's six normals on Ryu, every hit inside the predicted
# range (e.g. MP 21-22 vs 19-23). All three tables are raw data.
DAMAGE_TABLE, DAMAGE_TABLE_OTHER = 0x24E614, 0x24E834
RANDOM_TABLE, DEFENSE_TABLE = 0xE7996, 0x24E1F4
DAMAGE_CLASSES, VS_LEVEL = 32, 16


def _s8(b):
    return b - 256 if b > 127 else b


def _attack_box_ok(addr):
    """addr is the start of an attack-pool entry (16-byte stride) of a known block."""
    for blk in list(PLAYER_BLOCKS.values()) + sorted(_proj_blocks()):
        pool = block_pools(blk)["attack"]
        if pool <= addr < pool + 0x100 * ATTACK_STRIDE and (addr - pool) % ATTACK_STRIDE == 0:
            return True
    return False


def _damage_range(image, cls, rand_row, defense=0, level=VS_LEVEL):
    base = image[DAMAGE_TABLE + 32 * cls + level]
    outs = set()
    for r in range(32):
        v = base + _s8(image[RANDOM_TABLE + 32 * rand_row + r])
        v = 1 if v <= 0 else v
        outs.add(max(1, v - (v * defense) // 32))
    return base, min(outs), max(outs)


@app.get("/api/damage")
def api_damage(addr: str):
    """Damage data of one attack box (the editor's attack-box addr)."""
    a = int(addr, 16)
    if not _attack_box_ok(a):
        return JSONResponse({"error": f"0x{a:06X} is not an attack box"}, status_code=400)
    b4, row_hi, row_lo = WORKING[a + 4], WORKING[a + 9], WORKING[a + 10]
    cls = b4 & 0x3F
    base, lo, hi = _damage_range(WORKING, cls, row_hi)
    return {"addr": "0x%06X" % a, "class": cls, "original_class": ORIGINAL[a + 4] & 0x3F,
            "base": base, "range": [lo, hi], "strength": WORKING[a + 8],
            "rand_rows": [row_hi, row_lo],
            "classes": [{"class": c, "base": WORKING[DAMAGE_TABLE + 32 * c + VS_LEVEL]}
                        for c in range(DAMAGE_CLASSES)]}


@app.post("/api/damage")
def set_damage(payload: dict = Body(...)):
    """payload: {addr, class} -- the attack box's damage class (0-31); the box's
    flag bits (byte 4 & 0xC0) are kept."""
    try:
        a = int(payload["addr"], 16) if isinstance(payload["addr"], str) else int(payload["addr"])
        cls = int(payload["class"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "need addr and class"}, status_code=400)
    if not _attack_box_ok(a):
        return JSONResponse({"error": f"0x{a:06X} is not an attack box"}, status_code=400)
    if not 0 <= cls < DAMAGE_CLASSES:
        return JSONResponse({"error": "class must be 0-31"}, status_code=400)
    WORKING[a + 4] = (WORKING[a + 4] & 0xC0) | cls
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {**api_damage("0x%06X" % a), "dirty_bytes": dirty}


@app.get("/api/damagetable")
def api_damagetable():
    """Base damage of every class at the 2P versus level (and the full 32-level row)."""
    return {"level": VS_LEVEL, "table": "0x%06X" % DAMAGE_TABLE,
            "classes": [{"class": c, "base": WORKING[DAMAGE_TABLE + 32 * c + VS_LEVEL],
                         "original": ORIGINAL[DAMAGE_TABLE + 32 * c + VS_LEVEL],
                         "levels": list(WORKING[DAMAGE_TABLE + 32 * c:DAMAGE_TABLE + 32 * c + 32])}
                        for c in range(DAMAGE_CLASSES)]}


@app.post("/api/damagetable")
def set_damagetable(payload: dict = Body(...)):
    """payload: {class, value, all_levels} -- base damage of a class at the versus
    level. all_levels: shift every level of that class by the same amount, so
    single-player damage changes too. Every attack of that class changes."""
    try:
        cls, value = int(payload["class"]), int(payload["value"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "need class and value"}, status_code=400)
    if not (0 <= cls < DAMAGE_CLASSES and 1 <= value <= 255):
        return JSONResponse({"error": "class 0-31, value 1-255"}, status_code=400)
    row = DAMAGE_TABLE + 32 * cls
    delta = value - WORKING[row + VS_LEVEL]
    if payload.get("all_levels"):
        for k in range(32):
            WORKING[row + k] = max(1, min(255, WORKING[row + k] + delta))
    else:
        WORKING[row + VS_LEVEL] = value
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {"ok": True, "class": cls, "base": WORKING[row + VS_LEVEL], "dirty_bytes": dirty}


# ---- Special-move inputs ----------------------------------------------------
# inputs.py parses every character's motion checkers (pointer table 0x7B0B4)
# and rewrites them: same length = the direction immediates in place, other
# lengths = a compact direction-list engine in the move's own direction
# handlers (the game's button code is kept). Charge / 360 / mash moves are
# listed but not editable.
import inputs as _inputs


def _input_key(char, ver):
    if char not in _ROSTER or (char == "akuma" and ver == "old"):
        return None
    return char + "_old" if ver == "old" else char


def _charge_users():
    """charge-time byte -> [(char key, move name)] (some bytes are shared)."""
    out = {}
    for key, lst in _inputs.machines().items():
        for mc in lst:
            for a in mc.get("charge_bytes", []):
                out.setdefault(a, []).append((key, mc.get("name")))
    return out


def _input_row(mc):
    """kind: motion (rewrite in place or any length) / charge / 360 / other
    (replace with any motion) / mash (presses + windows) / null (not editable)."""
    row = {"sub": "0x%06X" % mc["sub"], "priority": mc["priority"], "kind": mc.get("kind"),
           "editable": bool(mc.get("editable") or mc.get("rewritable")),
           "why": mc.get("why"), "super": bool(mc.get("super")), "name": mc.get("name"),
           "button": mc.get("button"), "describe": mc.get("describe")}
    if mc.get("editable") or mc.get("rewritable"):
        cur, mode = _inputs.current(WORKING, mc, OPCRYPT)
        row.update(motion=_inputs.to_numpad(cur) if cur else None, mode=mode,
                   original=_inputs.to_numpad(mc["dirs"]) if mc.get("dirs") else None,
                   max_dirs=mc["max_dirs"], shared_with=[k for k in _inputs.shared_by(mc["sub"])])
    if mc.get("kind") == "charge":
        users = _charge_users()
        row["charge"] = [{**c, "shared_with": [n for k, n in users.get(int(c["addr"], 16), [])
                                               if n != mc.get("name")]}
                         for c in _inputs.charge_values(WORKING, mc)]
    if mc.get("kind") == "mash":
        row["editable"] = True
        row["mash"] = _inputs.mash_values(WORKING, mc, OPCRYPT)
    if mc.get("editable") or mc.get("rewritable"):
        row["timing"] = _inputs.timing(WORKING, mc, OPCRYPT)
        row["release_shortcut"] = _inputs.release_shortcut(WORKING, mc, OPCRYPT)
    return row


def _dirty():
    return sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)


@app.post("/api/inputs/timing")
def set_input_timing(payload: dict = Body(...)):
    """payload: {sub, dir_min?, dir_max?, light?, medium?, heavy?, button?, reset?} --
    direction window (ticks to reach each next direction) and button window
    (ticks to press after the last direction; per strength where the move has a
    threshold table, else `button`)."""
    mc = _sub_of(payload)
    if mc is None or not (mc.get("editable") or mc.get("rewritable")):
        return JSONResponse({"error": "not an editable move"}, status_code=400)
    try:
        if payload.get("reset"):
            _inputs.reset_timing(WORKING, mc, OPCRYPT)
        if payload.get("dir_min") is not None or payload.get("dir_max") is not None:
            cur = _inputs.timing(WORKING, mc, OPCRYPT)["dir"] or {}
            lo = int(payload.get("dir_min", cur.get("min", 1)))
            hi = int(payload.get("dir_max", cur.get("max", lo)))
            _inputs.set_dir_window(WORKING, mc, OPCRYPT, lo, max(lo, hi) if payload.get("dir_max") is None else hi)
        if any(payload.get(k) is not None for k in ("light", "medium", "heavy", "button")):
            _inputs.set_btn_window(WORKING, mc, OPCRYPT,
                                   *[int(payload[k]) if payload.get(k) is not None else None
                                     for k in ("light", "medium", "heavy")],
                                   all_=int(payload["button"]) if payload.get("button") is not None else None)
    except (TypeError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {**_input_row(mc), "dirty_bytes": _dirty()}


@app.post("/api/inputs/release")
def set_input_release(payload: dict = Body(...)):
    """payload: {sub, shortcut: bool} -- a charge move's release direction also
    accepts its two neighbouring diagonals (while the game's checker is in place)."""
    mc = _sub_of(payload)
    if mc is None:
        return JSONResponse({"error": "unknown move"}, status_code=400)
    try:
        _inputs.set_release_shortcut(WORKING, mc, OPCRYPT, bool(payload.get("shortcut")))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {**_input_row(mc), "dirty_bytes": _dirty()}


def _all_moves():
    seen = set()
    for lst in _inputs.machines().values():
        for mc in lst:
            if (mc.get("editable") or mc.get("rewritable")) and mc["sub"] not in seen:
                seen.add(mc["sub"])
                yield mc


@app.post("/api/inputs/global")
def set_input_global(payload: dict = Body(...)):
    """Every special move at once. payload: {action, ...}
      shortcuts_on / shortcuts_off: cardinal steps of every motion (and every
          charge release that can take one) accept / stop accepting diagonals
      dir_window {lo, hi}: every move's direction window
      btn_shift {delta}: add delta ticks to every move's button window(s)
      reset_timing: every move's direction and button windows back to stock."""
    if OPCRYPT is None:
        return JSONResponse({"error": "needs ssf2t.key"}, status_code=400)
    act, n, skipped = payload.get("action"), 0, 0
    try:
        for mc in _all_moves():
            try:
                if act in ("shortcuts_on", "shortcuts_off"):
                    on = act == "shortcuts_on"
                    cur, mode = _inputs.current(WORKING, mc, OPCRYPT)
                    if cur:
                        new = _inputs.with_shortcuts(cur, on)
                        if new != cur:
                            _inputs.apply(WORKING, mc, new, OPCRYPT)
                            n += 1
                    elif _inputs.release_shortcut(WORKING, mc, OPCRYPT) is not None:
                        _inputs.set_release_shortcut(WORKING, mc, OPCRYPT, on)
                        n += 1
                elif act == "dir_window":
                    _inputs.set_dir_window(WORKING, mc, OPCRYPT, int(payload["lo"]), int(payload["hi"]))
                    n += 1
                elif act == "btn_shift":
                    t = _inputs.timing(WORKING, mc, OPCRYPT)["btn"]
                    if t:
                        d = int(payload["delta"])
                        clamp = lambda v: max(1, min(60, v + d))
                        if "light" in t:
                            _inputs.set_btn_window(WORKING, mc, OPCRYPT, clamp(t["light"]), clamp(t["medium"]),
                                                   clamp(t["heavy"]))
                        else:
                            _inputs.set_btn_window(WORKING, mc, OPCRYPT, all_=clamp(t["all"]))
                        n += 1
                elif act == "reset_timing":
                    _inputs.reset_timing(WORKING, mc, OPCRYPT)
                    n += 1
                else:
                    return JSONResponse({"error": "unknown action"}, status_code=400)
            except ValueError:
                skipped += 1
    except (KeyError, TypeError) as e:
        return JSONResponse({"error": "missing value: %s" % e}, status_code=400)
    return {"ok": True, "action": act, "changed": n, "skipped": skipped, "dirty_bytes": _dirty()}


@app.get("/api/inputs")
def api_inputs(char: str = "ryu", ver: str = "new"):
    """Every special-move checker of a character in priority order (first match
    wins). Motions are numpad strings (2 down, 6 forward, 4 back, 3 down-forward...)."""
    if OPCRYPT is None:
        return JSONResponse({"error": "needs ssf2t.key (inputs are code immediates)"}, status_code=400)
    key = _input_key(char, ver)
    if key is None:
        return JSONResponse({"error": f"unknown character {char!r} / {ver!r}"}, status_code=400)
    by_sub = {mc["sub"]: mc for mc in _inputs.machines()[key]}
    cur = _inputs.order(WORKING, key, OPCRYPT)
    rows = []
    for prio, sub in enumerate(cur):
        row = _input_row(by_sub[sub])
        row["priority"] = prio
        row["original_priority"] = by_sub[sub]["priority"]
        rows.append(row)
    shares = [k for k, _ in _inputs.char_roots() if k != key and _inputs.root_of(k) == _inputs.root_of(key)]
    return {"char": char, "ver": ver, "key": key, "moves": rows, "checker_shared_with": shares}


@app.post("/api/inputs/priority")
def set_input_priority(payload: dict = Body(...)):
    """payload: {char, ver, sub, move: "up"|"down"} -- try this move one place
    earlier/later (first match wins); or {char, ver, reset: true}."""
    if OPCRYPT is None:
        return JSONResponse({"error": "needs ssf2t.key"}, status_code=400)
    char, ver = payload.get("char", "ryu"), payload.get("ver", "new")
    key = _input_key(char, ver)
    if key is None:
        return JSONResponse({"error": "unknown character"}, status_code=400)
    cur = _inputs.order(WORKING, key, OPCRYPT)
    if payload.get("reset"):
        new = [mc["sub"] for mc in _inputs.machines()[key]]
    else:
        try:
            sub = int(payload["sub"], 16) if isinstance(payload["sub"], str) else int(payload["sub"])
            i = cur.index(sub)
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"error": "need a sub of this character"}, status_code=400)
        j = i - 1 if payload.get("move") == "up" else i + 1
        if not 0 <= j < len(cur):
            return JSONResponse({"error": "already at the end"}, status_code=400)
        new = list(cur)
        new[i], new[j] = new[j], new[i]
    try:
        _inputs.set_order(WORKING, key, new, OPCRYPT)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return api_inputs(char, ver)


@app.post("/api/inputs")
def set_inputs(payload: dict = Body(...)):
    """payload: {sub, motion} (numpad string, e.g. "1632143") or {sub, reset: true}."""
    if OPCRYPT is None:
        return JSONResponse({"error": "needs ssf2t.key"}, status_code=400)
    try:
        sub = int(payload["sub"], 16) if isinstance(payload["sub"], str) else int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "need sub"}, status_code=400)
    mc = _inputs.find(sub)
    if mc is not None and payload.get("reset") and mc.get("kind") in ("mash", "charge"):
        # back to the game's values: mash presses/windows, charge time, checker
        if mc["kind"] == "mash":
            for f in mc["mash"]:
                _inputs.set_mash(WORKING, mc, f["strength"], OPCRYPT, window=f["window"], count=f["count"])
        else:
            for a in mc["charge_bytes"]:
                WORKING[a] = _inputs.pristine_raw()[a]
    if mc is not None and payload.get("reset") and mc.get("kind") == "mash":
        dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
        return {**_input_row(mc), "dirty_bytes": dirty}
    if mc is None or not (mc.get("editable") or mc.get("rewritable")):
        return JSONResponse({"error": (mc or {}).get("why") or "this move's input can't be replaced"},
                            status_code=400)
    try:
        if payload.get("reset"):
            _inputs.reset(WORKING, mc, OPCRYPT)      # the game's own checker again
        else:
            _inputs.apply(WORKING, mc, _inputs.from_numpad(str(payload.get("motion", ""))), OPCRYPT)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {**_input_row(mc), "dirty_bytes": dirty}


def _sub_of(payload):
    try:
        sub = int(payload["sub"], 16) if isinstance(payload["sub"], str) else int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    return _inputs.find(sub)


@app.post("/api/inputs/charge")
def set_input_charge(payload: dict = Body(...)):
    """payload: {sub, frames} -- how long the direction must be held (game ticks,
    1-255). Raw data byte; a few bytes are shared by two moves."""
    mc = _sub_of(payload)
    if mc is None or mc.get("kind") != "charge" or not mc.get("charge_bytes"):
        return JSONResponse({"error": "not a charge move"}, status_code=400)
    try:
        frames = int(payload["frames"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "need frames"}, status_code=400)
    if not 1 <= frames <= 255:
        return JSONResponse({"error": "charge time must be 1-255 ticks"}, status_code=400)
    for a in mc["charge_bytes"]:
        WORKING[a] = frames
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {**_input_row(mc), "dirty_bytes": dirty}


@app.post("/api/inputs/mash")
def set_input_mash(payload: dict = Body(...)):
    """payload: {sub, strength: light|medium|heavy|all, presses?, window?} --
    presses needed, and ticks allowed between presses (encrypted immediates)."""
    mc = _sub_of(payload)
    if mc is None or mc.get("kind") != "mash" or OPCRYPT is None:
        return JSONResponse({"error": "not a mash move"}, status_code=400)
    strength = payload.get("strength", "all")
    if strength not in ("all", "light", "medium", "heavy"):
        return JSONResponse({"error": "strength: light, medium, heavy or all"}, status_code=400)
    try:
        w = int(payload["window"]) if payload.get("window") is not None else None
        c = int(payload["presses"]) if payload.get("presses") is not None else None
        _inputs.set_mash(WORKING, mc, strength, OPCRYPT, window=w, count=c)
    except (TypeError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {**_input_row(mc), "dirty_bytes": dirty}


# ---- Projectiles (fireballs) ------------------------------------------------
# projectiles.json (build_projectiles.py, from MAME captures): per character,
# move and strength -> the projectile object's frame records, its hitbox block
# (obj+0x34, same 5-pool format as a character's) and the ROM slot its speed
# pointer (obj+0x30) is loaded from. The mover at 0x002F0C adds the word pair
# at ptr + 4*direction to x/y each tick, so a speed is a pointer to one of the
# (+v,0),(-v,0) entries of the shared velocity table at 0x2F8800; editing a
# speed repoints the slot to another entry and never touches the shared table.
VEL_TABLE, VEL_TABLE_END = 0x2F8800, 0x2F8898
_PROJ = None


def _load_proj():
    global _PROJ
    if _PROJ is None:
        import json
        try:
            _PROJ = json.load(open(os.path.join(HERE, "projectiles.json")))
        except Exception:
            _PROJ = {}
    return _PROJ


def _speed_entries():
    """[(ptr, px per tick)] for every (+v,0),(-v,0) pair in the velocity table."""
    out = []
    for p in range(VEL_TABLE, VEL_TABLE_END, 4):
        hi, lo, nhi, nlo = struct.unpack_from(">hHhH", ORIGINAL, p)
        if hi > 0 and lo == 0 and nlo == 0 and nhi == -hi:
            out.append((p, hi / 256))
    return out


def _proj_ptr(image, e):
    a, space = int(e["speed_slot"], 16), e["speed_space"]
    if space == "op":
        if OPCRYPT is None:
            return None
        return (OPCRYPT.read(image, a) << 16) | OPCRYPT.read(image, a + 2)
    return struct.unpack_from(">I", image, a)[0]


def _proj_blocks():
    return {int(e["hitbox_block"], 16) for mv in _load_proj().values()
            for st in mv.values() for e in st.values()}


def _proj_speed_info(char, move, strength):
    proj = _load_proj()
    e = proj[char][move][strength]
    speeds = dict(_speed_entries())
    cur, orig = _proj_ptr(WORKING, e), _proj_ptr(ORIGINAL, e)
    # every other move (any character, either version) loading its speed from the
    # same ROM slot -- old and new versions share their projectile objects
    def who(c, m, s):
        if c == char:
            return f"{m} · {s}"
        base, old = (c[:-4], True) if c.endswith("_old") else (c, False)
        return f"{base}{' (old)' if old else ' (new)'} {m} · {s}"
    shared = [who(c, m, s) for c, mv in proj.items() for m, st in mv.items()
              for s, o in st.items() if o["speed_slot"] == e["speed_slot"] and (c, m, s) != (char, move, strength)]
    return {"value": speeds.get(cur), "original": speeds.get(orig),
            "slot": e["speed_slot"], "encrypted": e["speed_space"] == "op",
            "editable": cur is not None and (e["speed_space"] != "op" or OPCRYPT is not None),
            "shared_with": shared, "choices": [v for _p, v in _speed_entries()]}


@app.get("/api/projectiles")
def api_projectiles(char: str = "ryu", ver: str = "new"):
    """Which of this character's specials have a mapped projectile, by strength."""
    _nr = _old_not_ready(char, ver)
    if _nr is not None:
        return _nr
    mv = _load_proj().get(char + "_old" if ver == "old" else char, {})
    return {"char": char, "moves": {m: list(st) for m, st in mv.items()}}


@app.get("/api/projanim")
def api_projanim(char: str = "ryu", move: str = "Hadouken", strength: str = "Strong Punch", ver: str = "new"):
    """The projectile object of one special: its frames (as the game showed them),
    boxes from the projectile's own hitbox block, and its speed."""
    _nr = _old_not_ready(char, ver)
    if _nr is not None:
        return _nr
    e = _load_proj().get(char + "_old" if ver == "old" else char, {}).get(move, {}).get(strength)
    if e is None:
        return JSONResponse({"error": f"no projectile mapped for {char} / {move} / {strength}"}, status_code=404)
    data = bytes(WORKING)
    block = int(e["hitbox_block"], 16)
    frames = _frames_from_addrs(data, [int(a, 16) for a in e["anims"]], block_pools(block))
    return {"char": char, "move": move, "strength": strength, "frame_count": len(frames),
            "frames": frames, "hitbox_block": e["hitbox_block"],
            "speed": _proj_speed_info(char + "_old" if ver == "old" else char, move, strength)}


@app.post("/api/projspeed")
def api_projspeed(payload: dict = Body(...)):
    """payload: {char, move, strength, speed} -- speed in px per tick, one of the
    velocity-table entries (0.5 steps). Repoints that strength's speed slot."""
    char, move, strength = payload.get("char"), payload.get("move"), payload.get("strength")
    if payload.get("ver") == "old":
        char = f"{char}_old"
    e = _load_proj().get(char, {}).get(move, {}).get(strength)
    if e is None:
        return JSONResponse({"error": "no projectile mapped for that move"}, status_code=400)
    try:
        want = float(payload["speed"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "speed must be a number"}, status_code=400)
    ptr = next((p for p, v in _speed_entries() if abs(v - want) < 1e-6), None)
    if ptr is None:
        return JSONResponse({"error": "speed must be one of " + ", ".join(
            str(v) for _p, v in _speed_entries())}, status_code=400)
    a = int(e["speed_slot"], 16)
    if e["speed_space"] == "op":
        if OPCRYPT is None:
            return JSONResponse({"error": "ssf2t.key not found; this speed is in encrypted code"}, status_code=400)
        OPCRYPT.write(WORKING, a, ptr >> 16)
        OPCRYPT.write(WORKING, a + 2, ptr & 0xFFFF)
    else:
        struct.pack_into(">I", WORKING, a, ptr)
    dirty = sum(1 for x, y in zip(ORIGINAL, WORKING) if x != y)
    return {"ok": True, "speed": _proj_speed_info(char, move, strength), "dirty_bytes": dirty}

@app.get("/api/bodysprite")
def api_bodysprite(obj_ptr: int = 0x1139C4, scale: int = 1, subpal: int = 0,
                   axis: int = 0, sub_offset: int = 0x0C):
    """Render a body sprite. sub_offset shifts into the compound OBJ structure
    (0x0C = body sub-sprite, 0 = raw). scale=1 returns native pixels so the
    frontend can do uniform canvas scaling.  Returns PNG + origin headers."""
    data = bytes(WORKING)
    target = obj_ptr + sub_offset
    try:
        png, meta = obj_decode.render_body_sprite(data, target, scale=scale,
                                                   subpal=subpal, draw_axis=bool(axis))
    except Exception as exc:
        return JSONResponse({"error": str(exc), "obj_ptr": obj_ptr,
                             "target": target}, status_code=500)
    headers = {
        "X-Origin-X": str(meta["origin_x"]),
        "X-Origin-Y": str(meta["origin_y"]),
        "X-Sprite-W": str(meta["width"]),
        "X-Sprite-H": str(meta["height"]),
        "X-Scale": str(meta["scale"]),
    }
    if meta.get("error"):
        headers["X-Error"] = meta["error"]
    return StreamingResponse(io.BytesIO(png), media_type="image/png",
                             headers=headers)


@app.get("/api/sprite")
def api_sprite(index: int = 0, frame: int = 0, scale: int = 4,
               obj_ptr: int = -1, axis: int = 0):
    """Assemble + return the frame sprite PNG, origin-aligned to the box axis.

    Resolve by (index, frame) via anim_decode, or pass obj_ptr directly.
    Origin pixel coords are returned in X-Origin-X / X-Origin-Y headers.
    """
    if not _HAS_OBJ:
        return JSONResponse({"error": "obj_decode unavailable"}, status_code=501)
    scale = max(1, min(12, int(scale)))
    optr = int(obj_ptr)
    if optr < 0:
        if not _HAS_ANIM:
            return JSONResponse({"error": "need obj_ptr (anim_decode unavailable)"},
                                status_code=400)
        data = bytes(WORKING)
        frames = list(anim_decode.walk_animation(data, int(index), max_frames=64))
        if not frames:
            return JSONResponse({"error": "no frames"}, status_code=404)
        fr = frames[max(0, min(int(frame), len(frames) - 1))]
        optr = fr["sprite_ref"]["obj_ptr"]
    return _sprite_png_response(optr & 0xFFFFFF, scale, bool(int(axis)))


@app.get("/api/spriteinfo")
def api_spriteinfo(index: int = 0, frame: int = 0, obj_ptr: int = -1):
    """Parsed OBJ list (entries with tile + x/y offsets) for one frame."""
    if not _HAS_OBJ:
        return JSONResponse({"error": "obj_decode unavailable"}, status_code=501)
    data = bytes(WORKING)
    optr = int(obj_ptr)
    if optr < 0:
        if not _HAS_ANIM:
            return JSONResponse({"error": "need obj_ptr"}, status_code=400)
        frames = list(anim_decode.walk_animation(data, int(index), max_frames=64))
        if not frames:
            return JSONResponse({"error": "no frames"}, status_code=404)
        fr = frames[max(0, min(int(frame), len(frames) - 1))]
        optr = fr["sprite_ref"]["obj_ptr"]
    p = obj_decode.parse_obj_list(data, optr & 0xFFFFFF)
    return {
        "obj_ptr": "0x%06X" % p["obj_ptr"],
        "count": p["count"], "attr": p["attr"], "piece0": p["piece0"],
        "base_x": p["base_x"], "base_y": p["base_y"],
        "coord_record": ("0x%06X" % p["coord_record"]) if p["coord_record"] else None,
        "origin": p["origin"],
        "entries": p["entries"],
    }


# Per-character attribute table @ CPU 0x7F7BA (char-indexed, 4-byte stride).
# Loaded into the player object by char_setup_install (0x5078) as obj+0x6C /
# obj+0x6E. pof box_list names obj+0x6C as the "throwable" param -- i.e. the
# throw/collision half-width used for throw-range and body collision. +0x6E is
# a shared constant (53 across the whole roster). [byte-verified vs inventory:
# ryu=29, zangief=45, chunli=25.]
CHAR_ATTR_TABLE = 0x7F7BA


def _char_cid(char: str) -> int:
    """Roster index (0=ryu .. 16=akuma). '_old' variants share the base cid."""
    base = char[:-4] if char.endswith("_old") else char
    try:
        return _ROSTER.index(base)
    except ValueError:
        return 0


@app.get("/api/charattr")
def api_charattr(char: str = "ryu"):
    """Per-character throw-range / collision attributes from the 0x7F7BA table.

    Returns the two 16-bit fields (obj+0x6C throw/collision half-width, obj+0x6E
    shared base) plus their editable flat addresses so a UI can both display the
    throwbox range and write new values back through the normal export path."""
    cid = _char_cid(char)
    a = CHAR_ATTR_TABLE + cid * 4
    v6c = struct.unpack_from(">H", WORKING, a)[0]
    v6e = struct.unpack_from(">H", WORKING, a + 2)[0]
    return {
        "char": char, "cid": cid,
        "throw_range": v6c,          # obj+0x6C -- throw/collision half-width
        "attr_6e": v6e,              # obj+0x6E -- shared base (53 roster-wide)
        "addr_6c": "0x%06X" % a,
        "addr_6e": "0x%06X" % (a + 2),
        "note": "obj+0x6C (pof 'throwable') = throw/collision half-width, drawn "
                "as the throwbox span on the axis. Editable at addr_6c.",
    }


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html")) as f:
        return f.read()
