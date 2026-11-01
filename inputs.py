"""inputs.py -- special-move motion inputs (read, remap, lengthen).

How ST reads a motion (traced from Ryu's checker, 0x07F862):
  * 0x07B08E picks the character's checker from the pointer table at 0x7B0B4
    (33 entries: 0-15 new, 16 Akuma, 17-32 old; old Ken shares old Ryu's).
    The checker calls one sub-routine per special move; the call order is the
    priority order (first match wins).
  * Each sub-routine is a state machine: `move.b $ST(a6),d0 ; move.w T(pc,d0.w),d1
    ; jmp T(pc,d1.w)`. Handler k waits for direction k: it reads the
    facing-relative stick (obj+0x3A6, &0xF: 1=back 2=forward 4=down 8=up) and
    compares it to an immediate (`cmpi.w #dir,d0`). On a match the state goes
    up by 2 and the timer byte $ST+1 is reloaded with a random 8-15 frames;
    if the timer runs out first the state is cleared. The last direction's
    handler then opens the button window (12 frames, minus 0/2/4 by strength).
  * The comparisons are code immediates, so they are encrypted opcode-space
    words (written through opcrypt).

Two ways to change a motion:
  * same number of directions: rewrite the immediates in place;
  * any other length (2..max): the direction handlers (all but the last one's
    button tail) are replaced in place by a compact engine that walks a
    direction list. Engine states are 0 and 0x80+2i, so the patched dispatch
    sends them to the engine (`ble.w`) and the original button states still go
    through the original jump table. After the last direction the engine sets
    the state the original last handler had and falls straight into that
    handler's button code, so the button window, strengths and the move itself
    are the game's own code. Kept code that branched into the replaced bytes
    (a shared `clr.b state ; rts` or `rts`) is redirected to the engine's copy.
Charge moves, 360s and button-mash moves use other code and are not editable here.
"""
import os
import re
import struct

import capstone

HERE = os.path.dirname(os.path.abspath(__file__))
import paths
_OPC_PATH = paths.OPCODES_BIN

ROOT_TABLE = 0x7B0B4
ROSTER = ["ryu", "honda", "blanka", "guile", "ken", "chunli", "zangief", "dhalsim", "dictator",
          "sagat", "boxer", "claw", "cammy", "thawk", "feilong", "deejay"]
STICK = 0x3A6                      # facing-relative stick word, obj+0x3A6

# numpad notation <-> the game's direction bits (relative: 1 back, 2 forward, 4 down, 8 up)
NUMPAD_TO_BITS = {"1": 5, "2": 4, "3": 6, "4": 1, "5": 0, "6": 2, "7": 9, "8": 8, "9": 10}
BITS_TO_NUMPAD = {v: k for k, v in NUMPAD_TO_BITS.items()}

ENGINE_SIZE = 56                   # bytes of engine code before the kept button tail
MAX_DIRS = 40

# Move names for each checker, by (directions in numpad, button group).
# Old versions use the same names (minus supers); Akuma has no st_moves entry.
_NAMES = {
    "ryu": {("236", "P"): "Hadouken", ("623", "P"): "Shoryuken", ("214", "K"): "Tatsumaki",
            ("41236", "P"): "Shakunetsu Hadouken", ("236236", "P"): "Shinku Hadouken (super)"},
    "ken": {("236", "P"): "Hadouken", ("623", "P"): "Shoryuken", ("214", "K"): "Tatsumaki",
            ("23623", "P"): "Shoryureppa (super)", ("236", "K"): "Kama Barai Geri",
            ("632", "K"): "Nata Otoshi Geri", ("41236", "K"): "Oosoto Mawashi Geri"},
    "akuma": {("236", "P"): "Gou Hadouken", ("623", "P"): "Gou Shoryuken", ("214", "K"): "Tatsumaki",
              ("41236", "P"): "Shakunetsu Hadouken"},
    "dhalsim": {("236", "P"): "Yoga Fire", ("41236", "P"): "Yoga Flame", ("41236", "K"): "Yoga Blast",
                ("412341236", "P"): "Yoga Inferno (super)"},
    "sagat": {("236", "P"): "Tiger Shot", ("236", "K"): "Ground Tiger Shot", ("623", "P"): "Tiger Uppercut",
              ("269", "K"): "Tiger Knee", ("23623", "K"): "Tiger Genocide (super)"},
    "cammy": {("236", "K"): "Spiral Arrow", ("623", "K"): "Cannon Spike", ("416", "P"): "Spinning Knuckle",
              ("23623", "K"): "Spin Drive Smasher (super)"},
    "thawk": {("623", "P"): "Tomahawk Buster"},
    "zangief": {("632", "P"): "Banishing Flat"},
    "feilong": {("236", "P"): "Rekka Ken", ("421", "K"): "Shien Kyaku",
                ("236236", "P"): "Rekka Shinken (super)"},
}

_MD = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
_PRISTINE = None


def pristine():
    """The unpatched, decrypted program image (instruction words in plaintext)."""
    global _PRISTINE
    if _PRISTINE is None:
        _PRISTINE = open(_OPC_PATH, "rb").read()
    return _PRISTINE


def _w(img, a):
    return (img[a] << 8) | img[a + 1]


def _dis(img, pc, count):
    out = []
    while len(out) < count:
        ins = next(_MD.disasm(bytes(img[pc:pc + 12]), pc), None)
        if ins is None:
            out.append((pc, ".word", "", 2))
            pc += 2
            continue
        out.append((ins.address, ins.mnemonic, ins.op_str, ins.size))
        pc += ins.size
    return out


def _hex(s):
    m = re.search(r"\$([0-9a-f]+)", s)
    return int(m.group(1), 16) if m else None


def char_roots():
    """[(key, root addr)] for every checker (key like 'ryu' / 'ryu_old' / 'akuma')."""
    img = pristine()
    keys = ROSTER + ["akuma"] + [n + "_old" for n in ROSTER]
    return [(k, struct.unpack_from(">I", img, ROOT_TABLE + 4 * i)[0]) for i, k in enumerate(keys)]


def _root_slots(root, img=None):
    """[(insn addr, mnemonic, target)] of the checker's call list, in order."""
    out = []
    for a, m, o, _ in _dis(pristine() if img is None else img, root, 40):
        if m in ("bsr.w", "bsr.b"):
            out.append((a, m, _hex(o)))
        elif m in ("bra.w", "bra.b"):
            out.append((a, m, _hex(o)))
            break
        elif m == "rts" or m.startswith("jmp"):
            break
    return out


def _root_calls(root):
    return [t for _, _, t in _root_slots(root)]


def root_of(key):
    return dict(char_roots())[key]


def order(image, key, crypt):
    """Current call order (sub addresses) of a checker in image."""
    out = []
    for a, m, t in _root_slots(root_of(key)):
        disp = crypt.read(image, a + 2)
        out.append(a + 2 + (disp - 0x10000 if disp & 0x8000 else disp))
    return out


def set_order(image, key, subs, crypt):
    """Rewrite the checker's call list so the moves are tried in `subs` order
    (first match wins). Only .w calls can be retargeted."""
    slots = _root_slots(root_of(key))
    if sorted(subs) != sorted(t for _, _, t in slots):
        raise ValueError("order must list every move of this character once")
    if any(not m.endswith(".w") for _, m, _ in slots):
        raise ValueError("this character's call list uses short branches")
    for (a, m, _), sub in zip(slots, subs):
        crypt.write(image, a + 2, _s16(sub - (a + 2), "0x%06X" % a))


def _dir_handler(img, h, st, first):
    """Parse a direction handler; None if it is not one."""
    ins = _dis(img, h, 10)
    i = 0
    if not first:
        if not (ins[0][1] == "subq.b" and ins[0][2] == "#$1, $%x(a6)" % (st + 1)
                and ins[1][1] in ("beq.b", "beq.w")):
            return None
        i = 2
    s = ins[i:i + 4]
    if not (s[0][1] == "move.w" and s[0][2] == "$%x(a6), d0" % STICK and s[1][1] == "andi.w"
            and s[1][2] == "#$f, d0" and s[2][1] == "cmpi.w" and s[2][2].endswith(", d0")
            and s[3][1] == "bne.b"):
        return None
    after = s[3][0] + s[3][3]
    return {"addr": h, "dir": _hex(s[2][2]), "imm": s[2][0] + 2, "mask_at": s[1][0] + 2, "after": after,
            "miss": _hex(s[3][2]), "expire": _hex(ins[1][2]) if not first else None}


def _advance_target(img, a, st):
    """If code at a is `addq.b #2,$st(a6) ; bra RELOAD` return RELOAD."""
    ins = _dis(img, a, 2)
    if ins[0][1] == "addq.b" and ins[0][2] == "#$2, $%x(a6)" % st and ins[1][1] in ("bra.w", "bra.b"):
        return _hex(ins[1][2])
    return None


def _semantic(img, a, st):
    """What kept code expects at a branch target inside the replaced bytes."""
    ins = _dis(img, a, 4)
    if ins[0][1] == "rts" or (ins[0][1] == "moveq" and ins[0][2] == "#$0, d0" and ins[1][1] == "rts"):
        return "ret"
    if ins[0][1] == "clr.b" and ins[0][2] == "$%x(a6)" % st and (
            ins[1][1] == "rts" or (ins[1][2] == "#$0, d0" and ins[2][1] == "rts")):
        return "rst"
    # a charge move's "back to charging" (state 2 + reload the charge counter):
    # once the charge is replaced by a motion, that means start the motion over
    if (ins[0][1] == "move.b" and ins[0][2] == "#$2, $%x(a6)" % st and ins[1][1] == "movea.l"
            and ins[2][1] == "move.b" and ins[3][1] == "rts"):
        return "rst"
    if _advance_target(img, a, st) is not None:
        return "adv"
    return None


def _flow_branches(img, starts, skip_lo, skip_hi, limit_lo, limit_hi):
    """Follow kept code from `starts` (not entering [skip_lo, skip_hi)), within
    [limit_lo, limit_hi). Returns [(insn addr, mnemonic, size, target)] for every
    PC-relative branch seen."""
    seen, todo, out = set(), list(starts), []
    while todo:
        pc = todo.pop()
        while limit_lo <= pc < limit_hi and pc not in seen and not (skip_lo <= pc < skip_hi):
            seen.add(pc)
            a, m, o, sz = _dis(img, pc, 1)[0]
            if m == ".word":
                break
            nxt = pc + sz
            if m.startswith("b") and m[1:3] not in ("se", "cl", "ch", "ts") or m.startswith("db"):
                tgt = _hex(o.split(",")[-1])
                if tgt is not None:
                    out.append((a, m, sz, tgt))
                    todo.append(tgt)
                if m.startswith("bra"):
                    break
            if m in ("rts", "rte") or m.startswith("jmp"):
                break
            pc = nxt
    return out


def parse_machine(sub):
    """Parse one move's checker. Returns a dict; 'editable' False (with 'why') when
    it is not a plain motion machine."""
    img = pristine()
    info = {"sub": sub, "editable": False}
    ins = _dis(img, sub, 16)
    disp = None
    for i in range(len(ins) - 2):
        a, m, o, _ = ins[i]
        if (m == "move.b" and re.fullmatch(r"\$[0-9a-f]+\(a6\), d0", o) and ins[i + 1][1] == "move.w"
                and "(pc, d0.w), d1" in ins[i + 1][2] and ins[i + 2][1] == "jmp"):
            disp = (i, _hex(o), ins[i + 1][0], _hex(ins[i + 1][2]))
            break
    if disp is None:
        info["why"] = "not a state machine (button or special logic)"
        return info
    i, st, dispatch, tbl = disp
    pre = ins[:i]
    info["super"] = any(m == "jsr" and _hex(o) == 0x4038 for _, m, o, _ in pre)
    # the table normally follows the jmp; Guile's super has an `rts` in between
    # (the prologue's "no meter" exit), which the rewrite keeps
    info["gap_rts"] = tbl == dispatch + 10 and _w(img, dispatch + 8) == 0x4E75
    if tbl != dispatch + 8 and not info["gap_rts"]:
        info["why"] = "unusual dispatch"
        return info
    # entries run up to the lowest handler address
    # entries run up to the lowest handler address (stop early at an entry that
    # can't be a handler: code may sit between the table and the handlers)
    hs, low = [], 1 << 30
    while tbl + 2 * len(hs) < low and len(hs) < 64:
        off = _w(img, tbl + 2 * len(hs))
        if not 2 * (len(hs) + 1) <= off < 0x400 or off % 2:
            break
        hs.append(tbl + off)
        low = min(low, tbl + off)
    steps = []
    for k, h in enumerate(hs):
        d = _dir_handler(img, h, st, k == 0)
        if d is None:
            break
        steps.append(d)
    info.update(state=st, table=tbl, dispatch=dispatch, handlers=hs, steps=steps)
    m = len(steps)
    if m < 2:
        return _parse_other(info, img)
    # every direction handler but the last only advances (+2 and the timer reload)
    reload = None
    for d in steps[:-1]:
        r = _advance_target(img, d["after"], st)
        if r is None:
            a2, m2, o2, _ = _dis(img, d["after"], 1)[0]
            if m2 in ("bra.b", "bra.w"):
                r = _advance_target(img, _hex(o2), st)
        if r is None or (reload is not None and r != reload):
            info["why"] = "direction step with extra logic"
            return info
        reload = r
    last = steps[-1]
    tail = last["after"]
    # the bytes replaced by the engine: from the lowest direction handler up to
    # the last one's button code. Handlers may be shared or out of order (Fei
    # Long's super), but the last direction handler must come after the others
    # and no button-state handler may sit inside.
    h0 = min(hs[:m])
    if max(hs[:m - 1]) >= hs[m - 1] or any(h0 <= h < tail for h in hs[m:]) or h0 < tbl + 2 * len(hs):
        info["why"] = "handlers not laid out in order"
        return info
    first_tail = _dis(img, tail, 1)[0]
    if re.search(r"\bd0\b", first_tail[2].split(",")[0]) and first_tail[1] != "moveq":
        info["why"] = "button code reads d0"
        return info
    # kept code: dispatch prologue, the last handler's button tail, later handlers
    lo, hi = sub - 0x100, max(hs) + 0x400
    starts = [sub, tail] + hs[m:]
    br = _flow_branches(img, starts, h0, tail, lo, hi)
    fixes = []
    for a, mn, sz, tgt in br:
        if dispatch <= tgt < tbl + 2 * m:
            info["why"] = "kept code jumps into the dispatch"
            return info
        if h0 <= tgt < tail:
            sem = _semantic(img, tgt, st)
            if sem is None:
                info["why"] = "kept code jumps into a direction handler (0x%06X)" % tgt
                return info
            fixes.append((a, mn, sz, sem))
    btn = None
    for a, mn, o, _ in _dis(img, tail, 4):
        mm = re.fullmatch(r"#\$([0-9a-f]+), d1", o)
        if mn == "move.w" and mm:
            v = int(mm.group(1), 16)
            btn = "P" if v == 0x70 else "K" if v == 0x700 else "PK" if v == 0x770 else hex(v)
            break
    if btn is None:
        info["why"] = "the last direction step has no button check"
        return info
    need_ls = not (first_tail[1] == "addq.b" and first_tail[2] == "#$2, $%x(a6)" % st)
    room = tail - h0 - ENGINE_SIZE - RST_SIZE - (8 if any(f[3] == "adv" for f in fixes) else 0) \
        - ((LS_SIZE + LS_CHECK) if need_ls else 0)
    info.update(editable=True, kind="motion", need_ls=need_ls, reload=reload, tail=tail, h0=h0, fixes=fixes, button=btn,
                timer=st + 1, L=2 * (m - 1), nrep=m,
                max_dirs=max(m, min(MAX_DIRS, room - (room % 2))),
                dirs=[d["dir"] for d in steps])
    return info


RST_SIZE = 8          # engine's RST: clr.b $st(a6) ; RET: moveq #0,d0 ; rts
LS_SIZE = 4           # re-check entry for the last-direction state (see build_engine)
LS_CHECK = 8          # engine's extra "state L -> button code" check when LS is used
STUB_SIZE = 8         # fixed timer reload: move.b #12,$t(a6) ; rts
STUB_FRAMES = 12      # window per direction when the move has no random reload of its own
_STICK_READ = re.compile(r"\$(3a6|392|393)\(a6\), d[0-7]")
_BTN_MASK = re.compile(r"#\$(70|700|770), d1")
_COND = ("beq", "bne", "bcc", "bcs", "bhi", "bls", "bpl", "bmi", "bge", "blt", "bgt", "ble")


def _button_after(img, tail):
    """Button group of the code at tail (follows one bra)."""
    pc = tail
    for _ in range(2):
        for a, mn, o, sz in _dis(img, pc, 8):
            mm = _BTN_MASK.fullmatch(o)
            if mn == "move.w" and mm:
                v = int(mm.group(1), 16)
                return "P" if v == 0x70 else "K" if v == 0x700 else "PK"
            if mn in ("bra.b", "bra.w"):
                pc = _hex(o)
                break
            if mn == "rts":
                return None
        else:
            return None
    return None


def _anchor(img, hs, st):
    """The last handler that checks the stick before the button code: returns
    (index, tail, timer byte) where tail is the code right after its matching
    branch, or None."""
    for k in range(len(hs) - 1, 0, -1):
        ins = _dis(img, hs[k], 24)
        if not (ins[0][1] == "subq.b" and ins[0][2].startswith("#$1, $") and ins[1][1].startswith("beq")):
            continue
        timer = _hex(ins[0][2].split(",")[1])
        read, last_cond = False, None
        for i, (a, mn, o, sz) in enumerate(ins):
            if mn == "jsr" or mn == "rts":
                break
            if _STICK_READ.search(o):
                read = True
            if read and mn.split(".")[0] in _COND and i > 0 and ins[i - 1][1].split(".")[0] in (
                    "cmp", "cmpi", "andi", "btst", "tst", "and"):
                last_cond = a + sz
                prev = ins[i - 1]
                _anchor.release = (("exact", _hex(prev[2])) if prev[1] == "cmpi.w" else
                                   ("any", _hex(prev[2])) if prev[1] == "andi.w" else (None, None))
                # `andi.w #$f,d0 ; cmpi.w #dir,d0` can take a shortcut in place
                _anchor.cmp_at = ((ins[i - 2][0] + 2, prev[0] + 2) if prev[1] == "cmpi.w" and i >= 2
                                  and ins[i - 2][1] == "andi.w" and ins[i - 2][2] == "#$f, d0" else None)
            if read and last_cond and ((mn == "addq.b" and o == "#$2, $%x(a6)" % st) or _BTN_MASK.fullmatch(o)):
                return k, last_cond, timer
    return None


def _charge_bytes(img, hs):
    """Charge-time bytes the replaced handlers load: movea.l #tbl,a0 ;
    move.b $k(a0),$x(a6) (raw data, frames)."""
    out = []
    for h in hs:
        ins = _dis(img, h, 16)
        for i in range(len(ins) - 1):
            mm = re.fullmatch(r"#\$([0-9a-f]+), a0", ins[i][2])
            if ins[i][1] == "movea.l" and mm and ins[i + 1][1] == "move.b":
                k = re.match(r"\$([0-9a-f]+)\(a0\)", ins[i + 1][2]) or re.match(r"\(a0\)", ins[i + 1][2])
                if k:
                    a = int(mm.group(1), 16) + (int(k.group(1), 16) if k.groups() else 0)
                    if a not in out:
                        out.append(a)
            if ins[i][1] == "rts":
                break
    return out


def _charge_dirs(img, hs):
    """Direction masks the charge handlers hold (andi.w #m,d0 after a stick read)."""
    out = []
    for h in hs:
        ins = _dis(img, h, 6)
        for i in range(len(ins) - 1):
            if _STICK_READ.search(ins[i][2]) and ins[i + 1][1] == "andi.w":
                v = _hex(ins[i + 1][2])
                if v not in (0xF, None) and v not in out:
                    out.append(v)
    return out


def _parse_mash(img, hs):
    """Button-mash checker (Hundred Hand Slap, Electricity, Lightning Legs):
    per strength `move.w #button,d0 ; move.b #window,d1 ; bsr count` and later
    `cmpi.b #presses,$n(a6)`. Each press restarts a `window`-tick timer and
    counts one; when the timer runs out the count is cleared; the move comes
    out on a press once the count reaches `presses`."""
    if len(hs) != 2:
        return None
    ins = _dis(img, hs[1], 80)
    wins, counts = [], []
    for i, (a, mn, o, sz) in enumerate(ins):
        if mn == "rts":
            break
        mm = re.fullmatch(r"#\$([0-9a-f]+), d0", o)
        if mn == "move.w" and mm and i + 1 < len(ins) and ins[i + 1][1] == "move.b" and ins[i + 1][2].endswith(", d1"):
            wins.append((int(mm.group(1), 16), ins[i + 1][0] + 2, _hex(ins[i + 1][2])))
        mc = re.fullmatch(r"#\$([0-9a-f]+), \$[0-9a-f]+\(a6\)", o)
        if mn == "cmpi.b" and mc:
            counts.append((a + 2, int(mc.group(1), 16)))
    if len(wins) != 3 or len(counts) != 3:
        return None
    names = ["light", "medium", "heavy"]
    return [{"strength": names[i], "mask": wins[i][0], "window_at": wins[i][1], "window": wins[i][2],
             "count_at": counts[i][0], "count": counts[i][1]} for i in range(3)]


def mash_values(image, mc, crypt):
    return [{"strength": f["strength"], "window": crypt.read(image, f["window_at"]) & 0xFF,
             "count": crypt.read(image, f["count_at"]) & 0xFF,
             "orig_window": f["window"], "orig_count": f["count"]} for f in mc["mash"]]


def set_mash(image, mc, strength, crypt, window=None, count=None):
    """Mash timing for one strength (or 'all'): window in ticks (1-255), presses (1-30)."""
    for f in mc["mash"]:
        if strength not in ("all", f["strength"]):
            continue
        if window is not None:
            if not 1 <= window <= 255:
                raise ValueError("window must be 1-255 ticks")
            crypt.write(image, f["window_at"], window)
        if count is not None:
            if not 1 <= count <= 30:
                raise ValueError("presses must be 1-30")
            crypt.write(image, f["count_at"], count)


def charge_values(image, mc):
    return [{"addr": "0x%06X" % a, "frames": image[a], "original": pristine_raw()[a]} for a in mc.get("charge_bytes", [])]


_RAW = None


def pristine_raw():
    """Unpatched raw data image (data reads see these bytes)."""
    global _RAW
    if _RAW is None:
        p = paths.DATA_BIN
        _RAW = open(p + ".orig" if os.path.exists(p + ".orig") else p, "rb").read()
    return _RAW


def _parse_other(info, img):
    """Charge / 360 / other checkers: everything before the anchor (the last
    direction check before the button code) can be replaced by the engine."""
    hs, st, tbl = info["handlers"], info["state"], info["table"]
    info["why"] = "charge, 360 or other special input"
    mash = _parse_mash(img, hs)
    if mash:
        info.update(kind="mash", mash=mash, button="K" if mash[0]["mask"] >= 0x100 else "P", why=None)
        return info
    an = _anchor(img, hs, st)
    if an is None:
        return info
    k, tail, timer = an
    info["release"] = getattr(_anchor, "release", (None, None))
    info["release_cmp"] = getattr(_anchor, "cmp_at", None)
    rep = hs[:k + 1]
    h0 = min(rep)
    if any(h0 <= h < tail for h in hs[k + 1:]) or h0 < tbl + 2 * len(hs) or max(rep[:-1]) >= rep[-1]:
        info["why"] = "handlers not laid out in order"
        return info
    first_tail = _dis(img, tail, 1)[0]
    if re.search(r"\bd[0-4]\b", first_tail[2].split(",")[0]) and first_tail[1] != "moveq":
        info["why"] = "button code reads a register"
        return info
    btn = _button_after(img, tail)
    if btn is None:
        info["why"] = "no button check after the last direction"
        return info
    # the move's own random reload (jsr $2e96 ... move.b ...,$timer(a6)), if any
    reload = None
    for h in rep:
        for a, mn, o, sz in _dis(img, h, 20):
            if mn in ("bra.w", "bra.b"):
                t = _hex(o)
                body = _dis(img, t, 4)
                if body[0][1] == "jsr" and _hex(body[0][2]) == 0x2E96 and any(
                        b[2].endswith("$%x(a6)" % timer) for b in body[1:]):
                    reload = t
            if mn == "rts":
                break
    dispatch = info["dispatch"]
    lo, hi = info["sub"] - 0x100, max(hs) + 0x400
    br = _flow_branches(img, [info["sub"], tail] + hs[k + 1:], h0, tail, lo, hi)
    fixes = []
    for a, mn, sz, tgt in br:
        if dispatch <= tgt < tbl + 2 * (k + 1) and not (info["gap_rts"] and tgt == dispatch + 8):
            info["why"] = "kept code jumps into the dispatch"
            return info
        if h0 <= tgt < tail:
            sem = _semantic(img, tgt, st)
            if sem is None or (sem == "adv" and reload is None):
                info["why"] = "kept code jumps into a replaced handler (0x%06X)" % tgt
                return info
            fixes.append((a, mn, sz, sem))
    kind = "charge" if _charge_bytes(img, rep) else (
        "360" if any(_STICK_READ.search(o) and "393" in o for h in rep for _, _, o, _ in _dis(img, h, 8)) else "other")
    need_ls = not (first_tail[1] == "addq.b" and first_tail[2] == "#$2, $%x(a6)" % st)
    room = tail - h0 - ENGINE_SIZE - RST_SIZE - (8 if any(f[3] == "adv" for f in fixes) else 0) \
        - (STUB_SIZE if reload is None else 0) - ((LS_SIZE + LS_CHECK) if need_ls else 0)
    if room < 2:
        info["why"] = "not enough room to rewrite"
        return info
    info.update(editable=False, rewritable=True, kind=kind, need_ls=need_ls, reload=reload, tail=tail, h0=h0, fixes=fixes,
                button=btn, timer=timer, L=2 * k, nrep=k + 1, dirs=None,
                max_dirs=min(MAX_DIRS, room - (room % 2)),
                charge_bytes=_charge_bytes(img, rep) if kind == "charge" else [],
                charge_masks=_charge_dirs(img, rep) if kind == "charge" else [])
    info["why"] = None
    return info


# Shortcuts: a direction value with LENIENT set is checked with its own bit as
# the mask (`andi #bit ; cmpi #bit`), so 2* accepts 1/2/3, 6* accepts 3/6/9,
# 4* accepts 1/4/7, 8* accepts 7/8/9. Only the four cardinals can be lenient.
LENIENT = 0x100
CARDINALS = (1, 2, 4, 8)


def mask_of(d):
    return (d & 0xFF) if (d & LENIENT) else 0xF


def to_numpad(bits_list):
    return "".join(BITS_TO_NUMPAD.get(b & 0xFF, "?") + ("*" if b & LENIENT else "") for b in bits_list)


def from_numpad(s):
    """'2*36' -> [any-down, down-forward, forward]. A * after 2/4/6/8 makes that
    step a shortcut (it also accepts the two diagonals next to it)."""
    s = re.sub(r"[\s,]", "", s)
    if not s or s[0] == "*" or any(c not in NUMPAD_TO_BITS and c != "*" for c in s):
        raise ValueError("use numpad digits 1-9 (2=down, 6=forward, 4=back, 8=up, 3=down-forward...),"
                         " with * after 2/4/6/8 for a shortcut")
    out = []
    for c in s:
        if c == "*":
            if out[-1] & LENIENT or out[-1] not in CARDINALS:
                raise ValueError("* only works after 2, 4, 6 or 8")
            out[-1] |= LENIENT
        else:
            out.append(NUMPAD_TO_BITS[c])
    return out


def with_shortcuts(dirs, on=True):
    """Every cardinal step lenient (on) or exact (off)."""
    return [((d & 0xFF) | LENIENT) if on and (d & 0xFF) in CARDINALS else d & 0xFF for d in dirs]


_CACHE = None
# checkers st_moves.lua can't name (its "motion" entries for them are the
# game's real inputs, but they don't match a parsed motion)
_OTHER_NAMES = {"honda": {"P": "Oicho Throw"}, "cammy": {"P": "Hooligan Combination"},
                "feilong": {"K": "Rekku Kyaku"}}


def _st_moves():
    """{char: [(name, kind, first dir, button group, super)]} from lua/st_moves.lua."""
    path = os.path.join(HERE, "lua", "st_moves.lua")
    out, cur = {}, None
    consts = {"CHB": "B", "CHD": "D", "CBFBF": "B", "CDBDF": "DB", "R360": "360", "R720": "360"}
    for line in open(path):
        m = re.match(r"\s*(\w+) = \{\s*$", line)
        if m:
            cur = out.setdefault(m.group(1), [])
            continue
        m = re.search(r'name = "([^"]+)",\s*kind = "(\w+)"(?:,\s*dirs = (\{[^}]*\}|\w+))?', line)
        if cur is not None and m:
            d = m.group(3) or ""
            first = consts.get(d) or (re.findall(r'"(\w+)"', d) or [""])[0]
            btn = re.search(r'btn = "(\w+)"', line).group(1)
            grp = "K" if "K" in btn else "P"
            out_name = m.group(1)
            cur.append((out_name.replace(" (super)", "") + (" (super)" if "super = true" in line else ""),
                        m.group(2), first, grp, "super = true" in line))
    return out


def _name_other(base, mc, table):
    """Name a charge / 360 / mash checker from st_moves.lua (unique match only)."""
    grp = "K" if mc.get("button") == "K" else "P"
    if mc["kind"] == "mash":
        c = [n for n, kd, f, g, s in table if kd == "mash" and g == grp]
    elif mc["kind"] == "360":
        c = [n for n, kd, f, g, s in table if f == "360" and g == grp and s == bool(mc.get("super"))]
    elif mc["kind"] == "charge":
        if mc.get("super"):
            c = [n for n, kd, f, g, s in table if kd == "charge" and s and g == grp]
        else:
            want = {1: ("B", "DB"), 4: ("D",)}.get((mc.get("charge_masks") or [0])[0], ())
            c = [n for n, kd, f, g, s in table if kd == "charge" and not s and g == grp and f in want]
    else:
        return _OTHER_NAMES.get(base, {}).get(grp)
    return c[0] if len(c) == 1 else None


_DIR_WORD = {1: "back", 2: "forward", 4: "down", 8: "up", 5: "down-back", 6: "down-forward",
             9: "up-back", 10: "up-forward"}
_BTN_WORD = {"P": "punch", "K": "kick", "PK": "punch or kick"}


def describe(mc):
    """The game's original input of a non-motion move, in words."""
    b = _BTN_WORD.get(mc.get("button"), "button")
    kind = mc.get("kind")
    if kind == "mash":
        return "press %s %d times quickly" % (b, mc["mash"][0]["count"])
    if kind == "360":
        return ("720" if mc.get("super") else "360") + " + " + b
    rel = mc.get("release") or (None, None)
    rw = _DIR_WORD.get(rel[1], "") if rel[0] == "exact" else ("any " + _DIR_WORD.get(rel[1], "")) if rel[0] else ""
    if kind == "charge":
        held = {1: "back", 4: "down"}.get((mc.get("charge_masks") or [0])[0], "down-back")
        if mc.get("super"):
            return "charge %s, then a super motion ending %s + %s" % (held, rw, b)
        return "charge %s, then %s + %s" % (held, rw, b)
    return ("special input ending %s + %s" % (rw, b)) if rw else ("special input + %s" % b)


def machines():
    """{key: [machine info, in priority order]} for every checker (old Ken is
    reported under 'ken_old' but shares old Ryu's code)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        for key, root in char_roots():
            base = key[:-4] if key.endswith("_old") else key
            if key == "ken_old":
                base = "ryu"                  # old Ken runs old Ryu's checker
            out = []
            table = _st_moves().get(base, [])
            for prio, sub in enumerate(_root_calls(root)):
                mc = parse_machine(sub)
                mc["priority"] = prio
                if mc.get("editable"):
                    sig = (to_numpad(mc["dirs"]), "P" if mc["button"] == "P" else "K")
                    mc["name"] = _NAMES.get(base, {}).get(sig)
                elif mc.get("kind"):
                    mc["name"] = _name_other(base, mc, table)
                    mc["describe"] = describe(mc)
                out.append(mc)
            # the move list can't tell same-button charge moves apart by release
            # direction (Boxer's dash punches/kicks), and new Chun-Li's kick
            # charges don't match it: name those by their input instead
            names = [m.get("name") for m in out]
            for m in out:
                if m.get("kind") in ("charge", "other") and (
                        (m.get("name") and names.count(m["name"]) > 1) or key == "chunli" and m.get("button") == "K"
                        and not m.get("super")):
                    m["name"] = None
            for m in out:
                if not m.get("editable") and m.get("kind") and not m.get("name"):
                    m["name"] = m["describe"][0].upper() + m["describe"][1:]
            _CACHE[key] = out
        _cross_check()
        for lst in _CACHE.values():
            for mc in lst:
                if mc.get("editable") or mc.get("rewritable"):
                    _fit_max(mc)
                    _timing_parse(pristine(), mc)
    return _CACHE


def _cross_check():
    """A machine stays editable only if no OTHER move's code of the same
    character branches into the bytes it would replace."""
    img = pristine()
    for key, lst in _CACHE.items():
        for mc in lst:
            if not (mc.get("editable") or mc.get("rewritable")):
                continue
            for other in lst:
                if other is mc:
                    continue
                starts = [other["sub"]] + list(other.get("handlers", []))
                br = _flow_branches(img, starts, mc["dispatch"], mc["tail"],
                                    other["sub"] - 0x100, max(starts) + 0x400)
                if any(mc["dispatch"] <= t < mc["tail"] for _, _, _, t in br):
                    mc["editable"] = mc["rewritable"] = False
                    mc["why"] = "another move's code jumps into this one"
                    break


# ---- input timing ---------------------------------------------------------------
# Direction window: after each direction the move gets a random number of ticks
# to reach the next one: `jsr $2e96 ; andi.w #$1f,d0 ; move.b TABLE(pc,d0.w),$t(a6)`
# picks one of 32 bytes (8-15 in the stock game; 360s add 8 with an addq). The
# table is PC-relative, so encrypted code space. Charge moves keep the release
# window's table inside their charge code.
# Button window: the last direction sets the button timer (`move.b #12,$b(a6)`),
# and a press counts while timer >= the strength's threshold
# (`move.w THR(pc,d1.w),d0 ; cmp.b $b(a6),d0 ; bhi`: 0/2/4), so light ~12,
# medium ~10, heavy ~8 ticks. Supers and some charge moves use one threshold.
def _rand_tables(img, starts):
    """[(table addr, timer byte, extra ticks)] of the random-window loads reachable
    from `starts` (each scanned linearly up to its rts)."""
    out = []
    for s in starts:
        ins = _dis(img, s, 40)
        for i, (a, mn, o, sz) in enumerate(ins):
            if mn == "rts" and i > 2:
                break
            if mn == "jsr" and _hex(o) == 0x2E96:
                for j in range(i + 1, min(i + 4, len(ins))):
                    mm = re.fullmatch(r"\$([0-9a-f]+)\(pc, d0\.w\), \$([0-9a-f]+)\(a6\)", ins[j][2])
                    if ins[j][1] == "move.b" and mm:
                        t, tm = int(mm.group(1), 16), int(mm.group(2), 16)
                        extra = 0
                        nx = ins[j + 1] if j + 1 < len(ins) else None
                        if nx and nx[1] == "addq.b" and nx[2].endswith("$%x(a6)" % tm):
                            extra = _hex(nx[2])
                        if all(x[0] != t for x in out):
                            out.append((t, tm, extra))
                        break
    return out


def _button_window(img, mc):
    """{'timer', 'start_at', 'start', 'thr_at', 'thr'} of the move's button window."""
    hs, k = mc["handlers"], mc["L"] // 2
    if k + 1 >= len(hs):
        return None
    b = _dis(img, hs[k + 1], 30)
    if not (b[0][1] == "subq.b" and b[0][2].startswith("#$1, $")):
        return None
    timer = _hex(b[0][2].split(",")[1])
    out = {"timer": timer, "thr_at": None, "thr": None}
    for i, (a, mn, o, sz) in enumerate(b[:-1]):
        mm = re.fullmatch(r"\$([0-9a-f]+)\(pc, d1\.w\), d0", o)
        if mn == "move.w" and mm and b[i + 1][1] == "cmp.b" and b[i + 1][2] == "$%x(a6), d0" % timer:
            t = int(mm.group(1), 16)
            out["thr_at"], out["thr"] = t, [_w(img, t + 2 * s) for s in range(3)]
            break
    for a, mn, o, sz in _dis(img, mc["tail"], 14):
        mm = re.fullmatch(r"#\$([0-9a-f]+), \$([0-9a-f]+)\(a6\)", o)
        if mn == "move.b" and mm and int(mm.group(2), 16) == timer:
            out["start_at"], out["start"] = a + 2, int(mm.group(1), 16)
            return out
        if mn == "rts":
            break
    return None


def _timing_parse(img, mc):
    """Attach dir_tables (outside the replaceable bytes: always editable),
    dir_tables_inner (inside: only while the game's checker is in place) and btn."""
    lo, hi = mc["dispatch"], mc["tail"]
    starts = list(mc["handlers"]) + ([mc["reload"]] if mc.get("reload") else [])
    tabs = _rand_tables(img, starts)
    mc["dir_tables"] = [t for t in tabs if not lo <= t[0] < hi]
    mc["dir_tables_inner"] = [t for t in tabs if lo <= t[0] < hi]
    mc["btn"] = _button_window(img, mc)


def _table_bytes(image, addr, crypt):
    return [b for k in range(16) for b in divmod(crypt.read(image, addr + 2 * k), 256)]


def stub_at(image, mc, crypt):
    """Address of the engine's fixed-window stub (move.b #n,$t(a6)) if the move
    is rewritten and has no random reload of its own, else None."""
    if mc.get("reload") is not None or current(image, mc, crypt)[1] != "engine":
        return None
    x8 = LS_CHECK if mc.get("need_ls") else 0
    e = mc["tail"] - ENGINE_SIZE - x8
    n = (crypt.read(image, e + x8 + 42) & 0xFF) - 0x80 >> 1
    adv = any(f[3] == "adv" for f in mc["fixes"])
    return e - 2 * n - (8 if adv else 0) - STUB_SIZE


def timing(image, mc, crypt):
    """Current direction and button windows of a move (game ticks)."""
    mode = current(image, mc, crypt)[1]
    out = {"dir": None, "btn": None}
    st = stub_at(image, mc, crypt)
    if st is not None:
        v = crypt.read(image, st + 2) & 0xFF
        out["dir"] = {"min": v, "max": v, "orig_min": STUB_FRAMES, "orig_max": STUB_FRAMES,
                      "extra": 0, "fixed_engine": True}
    else:
        tabs = mc.get("dir_tables", []) + (mc.get("dir_tables_inner", []) if mode == "original" else [])
        if tabs:
            cur = [b for t in tabs for b in _table_bytes(image, t[0], crypt)]
            orig = [b for t in tabs for b in _table_bytes_plain(t[0])]
            out["dir"] = {"min": min(cur), "max": max(cur), "orig_min": min(orig), "orig_max": max(orig),
                          "extra": max(t[2] for t in tabs), "fixed_engine": False,
                          "shared": len(tabs) > 1}
    b = mc.get("btn")
    if b:
        start = crypt.read(image, b["start_at"]) & 0xFF
        if b["thr_at"]:
            thr = [crypt.read(image, b["thr_at"] + 2 * s) & 0xFF for s in range(3)]
            out["btn"] = {"light": start - thr[0], "medium": start - thr[1], "heavy": start - thr[2],
                          "orig": [b["start"] - t for t in b["thr"]]}
        else:
            out["btn"] = {"all": start, "orig": [b["start"]]}
    return out


def _table_bytes_plain(addr):
    img = pristine()
    return [b for k in range(16) for b in divmod(_w(img, addr + 2 * k), 256)]


def set_dir_window(image, mc, crypt, lo, hi):
    """Direction window lo..hi ticks. The stock spread (mostly the low end) is
    kept by mapping every table entry linearly; lo == hi gives a fixed window."""
    if not (1 <= lo <= hi <= 120):
        raise ValueError("direction window must be 1-120 ticks, min <= max")
    st = stub_at(image, mc, crypt)
    if st is not None:
        crypt.write(image, st + 2, hi)
        return
    mode = current(image, mc, crypt)[1]
    tabs = mc.get("dir_tables", []) + (mc.get("dir_tables_inner", []) if mode == "original" else [])
    if not tabs:
        raise ValueError("this move has no direction window to edit")
    for t in tabs:
        orig = _table_bytes_plain(t[0])
        omin, omax = min(orig), max(orig)
        new = [lo + (round((v - omin) * (hi - lo) / (omax - omin)) if omax > omin else 0) for v in orig]
        for k in range(16):
            crypt.write(image, t[0] + 2 * k, (new[2 * k] << 8) | new[2 * k + 1])


def set_btn_window(image, mc, crypt, light=None, medium=None, heavy=None, all_=None):
    """Button window(s) in ticks (1-60). Per strength when the move has a
    threshold table, otherwise one value."""
    b = mc.get("btn")
    if not b:
        raise ValueError("this move has no button window to edit")
    if b["thr_at"]:
        cur = timing(image, mc, crypt)["btn"]
        w = [light if light is not None else cur["light"], medium if medium is not None else cur["medium"],
             heavy if heavy is not None else cur["heavy"]]
        if all_ is not None:
            w = [all_] * 3
        if not all(1 <= x <= 60 for x in w):
            raise ValueError("button windows must be 1-60 ticks")
        start = max(w)
        crypt.write(image, b["start_at"], start)
        for s in range(3):
            crypt.write(image, b["thr_at"] + 2 * s, start - w[s])
    else:
        v = all_ if all_ is not None else light
        if v is None or not 1 <= v <= 60:
            raise ValueError("button window must be 1-60 ticks")
        crypt.write(image, b["start_at"], v)


def reset_timing(image, mc, crypt):
    img = pristine()
    for t in mc.get("dir_tables", []) + mc.get("dir_tables_inner", []):
        for k in range(16):
            crypt.write(image, t[0] + 2 * k, _w(img, t[0] + 2 * k))
    b = mc.get("btn")
    if b:
        crypt.write(image, b["start_at"], _w(img, b["start_at"]))
        if b["thr_at"]:
            for s in range(3):
                crypt.write(image, b["thr_at"] + 2 * s, _w(img, b["thr_at"] + 2 * s))
    st = stub_at(image, mc, crypt)
    if st is not None:
        crypt.write(image, st + 2, STUB_FRAMES)


def release_shortcut(image, mc, crypt):
    """True/False for charge / other moves whose release is `andi #$f ; cmpi #dir`
    and a cardinal, while the game's checker is in place; None otherwise."""
    rc = mc.get("release_cmp")
    if not rc or current(image, mc, crypt)[1] != "original" or (mc.get("release") or (0, 0))[1] not in CARDINALS:
        return None
    return (crypt.read(image, rc[0]) & 0xFF) != 0xF


def set_release_shortcut(image, mc, crypt, on):
    if release_shortcut(image, mc, crypt) is None:
        raise ValueError("this move's release direction can't take a shortcut")
    crypt.write(image, mc["release_cmp"][0], mc["release"][1] if on else 0xF)


def _fit_max(mc):
    """Longest motion the engine can really build for this move (the room
    estimate ignores short-branch reach and the extra reset pair)."""
    n = mc["max_dirs"]
    while n >= 2:
        try:
            build_engine(mc, [2] * n)
            break
        except ValueError:
            n -= 1
    k = n                                      # with shortcuts the list is a word per direction
    while k >= 2:
        try:
            build_engine(mc, [2 | LENIENT] * k)
            break
        except ValueError:
            k -= 1
    mc["max_dirs_shortcut"] = max(k, len(mc["steps"]) if mc.get("kind") == "motion" else 0)
    if mc.get("kind") == "motion":
        n = max(n, len(mc["steps"]))          # same length always works in place
    mc["max_dirs"] = n
    if n < 2:
        mc["editable"] = mc["rewritable"] = False
        mc["why"] = "not enough room to rewrite"


def find(sub):
    for lst in machines().values():
        for mc in lst:
            if mc["sub"] == sub:
                return mc
    return None


def shared_by(sub):
    return [k for k, lst in machines().items() if any(mc["sub"] == sub for mc in lst)]


# ---- reading and writing a machine in the editor's raw image -------------------
def _region(mc):
    """(lo, hi) of every byte this module may rewrite for the machine."""
    return mc["dispatch"], mc["tail"]


def _restore(image, mc, crypt):
    """Put the machine's bytes (dispatch..tail and fixed branches) back to pristine."""
    img = pristine()
    lo, hi = _region(mc)
    for a in range(lo, hi, 2):
        crypt.write(image, a, _w(img, a))
    for a, mn, sz, sem in mc["fixes"]:
        for k in range(0, sz, 2):
            crypt.write(image, a + k, _w(img, a + k))


def current(image, mc, crypt):
    """Current directions (bit values) of a machine in image, and the mode."""
    lo, hi = _region(mc)
    img = pristine()
    if all(crypt.read(image, a) == _w(img, a) for a in range(lo, mc["table"], 2)):
        if mc.get("kind") != "motion":
            return None, "original"
        out = []
        for d in mc["steps"]:
            v, m = crypt.read(image, d["imm"]) & 0xFF, crypt.read(image, d["mask_at"]) & 0xFF
            out.append(v | LENIENT if m != 0xF and v in CARDINALS and m == v else v)
        return out, "in place"
    # engine: list length from the cmpi.b #$80+2n, list just before the engine
    x8 = LS_CHECK if mc.get("need_ls") else 0
    e = mc["tail"] - ENGINE_SIZE - x8
    n = (crypt.read(image, e + x8 + 42) & 0xFF) - 0x80 >> 1
    if crypt.read(image, e + 12) == 0xE248:   # first engine version: one byte per direction
        lst = e - _pad(n)
        raw = b"".join(struct.pack(">H", crypt.read(image, a)) for a in range(lst, lst + _pad(n), 2))
        return list(raw[:n]), "engine"
    lst = e - 2 * n                           # (mask, value) word per direction
    out = []
    for a in range(lst, lst + 2 * n, 2):
        w = crypt.read(image, a)
        m, v = w >> 8, w & 0xFF
        out.append(v | LENIENT if m != 0xF and v in CARDINALS and m == v else v)
    return out, "engine"


def _pad(n):
    return n + (n & 1)


def _s8(v, where):
    if not -128 <= v <= 127 or v == 0:
        raise ValueError("short branch out of range at " + where)
    return v & 0xFF


def _s16(v, where):
    if not -32768 <= v <= 32767:
        raise ValueError("branch out of range at " + where)
    return v & 0xFFFF


def build_engine(mc, dirs, stub_frames=None):
    """{addr: plaintext word} for the engine version of a machine."""
    n = len(dirs)
    st, t, tail, h0 = mc["state"], mc["timer"], mc["tail"], mc["h0"]
    L = mc["L"]
    need_adv = any(f[3] == "adv" for f in mc["fixes"])
    need_ls = mc.get("need_ls")
    x8 = LS_CHECK if need_ls else 0           # engine grows by the state-L check
    e = tail - ENGINE_SIZE - x8
    # direction list: one byte per direction (exact checks), or a (mask, value)
    # word per direction when any step is a shortcut
    pairs = any(dv & LENIENT for dv in dirs)
    lst = e - (2 * n if pairs else _pad(n))
    adv = lst - 8 if need_adv else None
    stub = None
    below = adv if need_adv else lst
    if mc["reload"] is None:                 # no random reload of its own: fixed window
        stub = below - STUB_SIZE
        below = stub
    rst = below - RST_SIZE
    ret = rst + 4
    # LS: if the game's button code can return without advancing the state
    # (it checks the button before its `addq.b #2`), the last-direction state L
    # persists and next frame the dispatch runs state L again. The original
    # handler for L re-checks the timer and the last direction, then the
    # button. LS does the same through the engine: moveq #2(n-1),d0 and enter
    # the engine's timer/compare; the engine then sends state L to the button
    # code instead of advancing. LS's table entry (index L/2) is restored.
    ls = rst - (LS_SIZE if need_ls else 0)
    reload = mc["reload"] if stub is None else stub
    if ls < h0:
        raise ValueError("motion too long for this move (max %d directions)" % mc["max_dirs"])
    if need_ls and L < (8 if mc.get("gap_rts") else 4):
        raise ValueError("this move's dispatch has no room for the rewrite")
    words = {}

    def put(a, *ws):
        for k, wv in enumerate(ws):
            words[a + 2 * k] = wv & 0xFFFF

    # dispatch: ble.w E ; move.w T(pc,d0.w),d1 ; jmp T(pc,d1.w) ; nops over the dead entries
    d, tbl = mc["dispatch"], mc["table"]
    put(d, 0x6F00, _s16(e - (d + 2), "dispatch"))
    if mc.get("gap_rts"):
        # keep the rts at d+8: ble.w E ; bra.s X ; rts ; X: move.w / jmp over
        # the dead table entries (needs 4 of them)
        if mc["nrep"] < 4:
            raise ValueError("not enough room in this move's dispatch")
        x = tbl
        put(d + 4, 0x6000 | _s8(x - (d + 6), "dispatch"))
        put(x, 0x323B, _s8(tbl - (x + 2), "dispatch"))
        put(x + 4, 0x4EFB, 0x1000 | _s8(tbl - (x + 6), "dispatch"))
        fill_from = x + 8
        put(d + 6, 0x4E71)
    else:
        put(d + 4, 0x323B, _s8(tbl - (d + 6), "dispatch") | 0x0000)
        put(d + 8, 0x4EFB, 0x1000 | _s8(tbl - (d + 10), "dispatch"))
        fill_from = d + 12
    for a in range(fill_from, tbl + 2 * mc["nrep"], 2):
        put(a, 0x4E71)
    for a in range(h0, ls, 2):
        put(a, 0x4E71)
    if need_ls:
        put(tbl + L, ls - tbl)                                     # state L -> LS
        put(ls, 0x7000 | (2 * (n - 1)))                            # LS: moveq #2(n-1),d0
        put(ls + 2, 0x6000 | _s8((e + 6) - (ls + 4), "re-check"))  # bra.s engine timer/compare
    put(rst, 0x422E, st)                      # RST: clr.b $st(a6)
    put(ret, 0x7000, 0x4E75)                  # RET: moveq #0,d0 ; rts  ("nothing happened")
    if stub is not None:                      # fixed window: move.b #12,$t(a6) ; rts
        put(stub, 0x1D7C, stub_frames or STUB_FRAMES, t, 0x4E75)
    if need_adv:                              # ADV: addq.b #2,$st(a6) ; bra.w RELOAD
        put(adv, 0x542E, st, 0x6000, _s16(reload - (adv + 6), "adv"))
    if pairs:
        for k, dv in enumerate(dirs):
            put(lst + 2 * k, (mask_of(dv) << 8) | (dv & 0xFF))
    else:
        data = bytes(dv & 0xFF for dv in dirs) + (b"\x00" if n & 1 else b"")
        for k in range(0, len(data), 2):
            put(lst + k, (data[k] << 8) | data[k + 1])
    # andi first: some checkers load the state with move.b alone (no moveq #0),
    # so the index word must be cleaned before it is used; Z = state was 0
    put(e + 0, 0x0240, 0x007F)                                     # andi.w #$7f,d0
    put(e + 4, 0x6700 | _s8(12 - 6, "engine"))                     # beq.s S0
    put(e + 6, 0x532E, t)                                          # subq.b #1,$t(a6)
    put(e + 10, 0x6700 | _s8(rst - (e + 12), "engine"))            # beq.s RST
    if pairs:
        put(e + 12, 0x323B, _s8(lst - (e + 14), "engine"))         # S0: move.w LIST(pc,d0.w),d1
        put(e + 16, 0x302E, STICK)                                 # move.w $3a6(a6),d0
        put(e + 20, 0xE059)                                        # ror.w #8,d1   (mask low)
        put(e + 22, 0xC001)                                        # and.b d1,d0
        put(e + 24, 0xE059)                                        # ror.w #8,d1   (value low)
    else:
        put(e + 12, 0xE248)                                        # S0: lsr.w #1,d0
        put(e + 14, 0x123B, _s8(lst - (e + 16), "engine"))         # move.b LIST(pc,d0.w),d1
        put(e + 18, 0x302E, STICK)                                 # move.w $3a6(a6),d0
        put(e + 22, 0x0240, 0x000F)                                # andi.w #$f,d0
    put(e + 26, 0xB001)                                            # cmp.b d1,d0
    put(e + 28, 0x6600 | _s8(ret - (e + 30), "engine"))            # bne.s RET
    if need_ls:                                                    # state L (via LS): last dir
        put(e + 30, 0x0C2E, L, st)                                 #   still held -> button code
        put(e + 36, 0x6700 | _s8(tail - (e + 38), "engine"))       #   cmpi.b #L,$st ; beq.s TAIL
    q = e + x8
    put(q + 30, 0x542E, st)                                        # addq.b #2,$st(a6)
    put(q + 34, 0x08EE, 0x0007, st)                                # bset #7,$st(a6)
    put(q + 40, 0x0C2E, 0x80 + 2 * n, st)                          # cmpi.b #$80+2n,$st(a6)
    put(q + 46, 0x6600, _s16(reload - (q + 48), "engine"))         # bne.w RELOAD
    put(q + 50, 0x1D7C, L, st)                                     # move.b #L,$st(a6)
    assert q + 56 == tail                                          # falls into the button tail
    # kept branches into the replaced bytes -> the engine's copies. A short
    # branch from before the engine (the prologue) that can't reach them gets a
    # second `clr.b ; rts` pair at the start of the freed bytes.
    img = pristine()
    near = None
    for a, mn, sz, sem in mc["fixes"]:
        tgt = {"ret": ret, "rst": rst, "adv": adv}[sem]
        if sz == 2 and not mn.startswith("db") and not -128 <= tgt - (a + 2) <= 127 and sem != "adv":
            if near is None:
                if h0 + RST_SIZE > ls:
                    raise ValueError("motion too long for this move")
                put(h0, 0x422E, st, 0x7000, 0x4E75)
                near = {"rst": h0, "ret": h0 + 4}
            tgt = near[sem]
        op = _w(img, a)
        if mn.startswith("db"):
            put(a, op, _s16(tgt - (a + 2), "0x%06X" % a))
        elif sz == 2:
            put(a, (op & 0xFF00) | _s8(tgt - (a + 2), "0x%06X" % a))
        else:
            put(a, op, _s16(tgt - (a + 2), "0x%06X" % a))
    return words


def apply(image, mc, dirs, crypt):
    """Set a machine's motion to `dirs` (list of direction bit values). Same length
    as the original: immediates rewritten in place; otherwise the engine."""
    if not (mc.get("editable") or mc.get("rewritable")):
        raise ValueError(mc.get("why") or "not editable")
    if not 2 <= len(dirs) <= mc["max_dirs"]:
        raise ValueError("this move takes 2 to %d directions" % mc["max_dirs"])
    in_place_ok = mc.get("kind") == "motion" and len(dirs) == len(mc["steps"])
    if not in_place_ok and any(d & LENIENT for d in dirs) and len(dirs) > mc.get("max_dirs_shortcut", 0):
        raise ValueError("with shortcuts this move takes at most %d directions" % mc.get("max_dirs_shortcut", 0))
    if any((b & 0xFF) not in BITS_TO_NUMPAD or (b & LENIENT and (b & 0xFF) not in CARDINALS)
           or b & ~(0xFF | LENIENT) for b in dirs):
        raise ValueError("bad direction value")
    in_place = mc.get("kind") == "motion" and len(dirs) == len(mc["steps"])
    st = stub_at(image, mc, crypt)            # keep an edited fixed window across rebuilds
    words = None if in_place else build_engine(mc, dirs, crypt.read(image, st + 2) & 0xFF if st else None)
    _restore(image, mc, crypt)
    if words is None:
        for d, b in zip(mc["steps"], dirs):
            crypt.write(image, d["imm"], b & 0xFF)
            crypt.write(image, d["mask_at"], mask_of(b))
    else:
        for a, wv in words.items():
            crypt.write(image, a, wv)


def reset(image, mc, crypt):
    """Back to the game's own checker for this move."""
    _restore(image, mc, crypt)


def disassemble(image, mc, crypt, lo=None, hi=None):
    """Decrypted listing of the machine's patched range (for checks)."""
    lo = mc["dispatch"] if lo is None else lo
    hi = mc["tail"] + 8 if hi is None else hi
    buf = bytearray(len(pristine()))
    for a in range(lo, hi + 12, 2):
        struct.pack_into(">H", buf, a, crypt.read(image, a))
    out, pc = [], lo
    while pc < hi:
        a, m, o, sz = _dis(buf, pc, 1)[0]
        out.append("%06X  %-8s %s" % (a, m, o))
        pc += sz
    return out
