"""build_move_physics.py -- move_physics.json from MAME write-tap captures.

Input: am_<char>.txt logs from lua/captures/run_allmoves.sh (STEPSET=moves with
a write tap on P1 obj+0x3C..0x43: "RT W pc=.. addr=.. data=.. label=mv|Move|BTN").
Each hit is the FIRST write by one instruction to one field during one move and
strength. MAME reports the PC after the writing instruction, so the instruction
is the one that ends there.

For each setter instruction:
  move.w $T(pc,dN.w),$F(a6)   per-strength table (opcode space, encrypted): the
                              entry whose word equals that strength's written
                              value (consistent stride preferred)
  move.w #imm,$F(a6)          the immediate word (shared by every strength that
                              runs this instruction)
  move.l #imm,$F(a6)          two immediate words (F and F+2)
Anything else (register / computed / address-register reads) is reported, not
mapped. Fields: +0x3C speed, +0x3E rise speed, +0x40 slowdown, +0x42 rise
slowdown, all 1/256 px per tick; the per-tick mover (0x002F50) and the walk
setter (0x002F34) are skipped. A field set twice in one move gets "(phase 2)".

Usage: python build_move_physics.py <capture dir>
"""
import collections
import itertools
import json
import os
import re
import struct
import sys

import capstone

HERE = os.path.dirname(os.path.abspath(__file__))
OPC = open(os.path.join(os.path.dirname(HERE), "ssf2t_opcodes.bin"), "rb").read()
MD = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
P1 = 0xFF844E
FIELD = {0x3C: ("speed", "speed"), 0x3E: ("rise", "rise speed"),
         0x40: ("slowdown", "slowdown"), 0x42: ("rise_slow", "rise slowdown")}
BTN = {"LP": "Weak Punch", "MP": "Medium Punch", "HP": "Strong Punch",
       "LK": "Weak Kick", "MK": "Medium Kick", "HK": "Strong Kick",
       "PPP": "3 Punches", "KKK": "3 Kicks"}   # same labels as attack_anims.json variants
GENERIC = [(0x002F34, 0x002F82)]   # walk setter + per-tick mover


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def word(a):
    return s16(struct.unpack_from(">H", OPC, a)[0])


DATA = open(os.path.join(os.path.dirname(HERE), "ssf2t_data.bin"), "rb").read()


def instr_ending_at(pc, off):
    """The instruction that ends at pc AND writes field `off` of a6 (several
    decodes can end at pc; only the one whose destination is the field counts)."""
    best = None
    for back in range(2, 12, 2):
        s = pc - back
        ins = next(MD.disasm(OPC[s:s + 12], s), None)
        if not ins or ins.address + ins.size != pc:
            continue
        dst = ins.op_str.split(",")[-1].strip()
        if dst in (f"${off:x}(a6)", f"${off - 2:x}(a6)") and ins.mnemonic.split(".")[0] in ("move", "clr", "neg", "add", "sub"):
            best = ins
    return best


def areg_base(at, reg):
    """Address loaded into a<reg> by the nearest `lea $T(pc),aN` or
    `movea.l #$T,aN` in the 0x40 bytes before `at` (the setter's routine)."""
    best = None
    for s in range(at - 0x40, at, 2):
        ins = next(MD.disasm(OPC[s:s + 8], s), None)
        if not ins or ins.address + ins.size > at:
            continue
        m = (re.match(rf"\$([0-9a-f]+)\(pc\), a{reg}$", ins.op_str) if ins.mnemonic == "lea.l" else
             re.match(rf"#\$([0-9a-f]+), a{reg}$", ins.op_str) if ins.mnemonic == "movea.l" else None)
        if m:
            best = int(m.group(1), 16)        # keep the closest one
    return best


def find_sequence(vals):
    """vals: [(field_off, value)] written together (same frame, PC order). Find
    them as words in that order, at most 3 words apart, in the raw image (data
    read) or the opcode image (PC-relative). Returns (space, {off: addr}) when
    exactly one place matches, else None."""
    found = []
    for img, space in ((DATA, "raw"), (OPC, "op")):
        first = struct.pack(">h", vals[0][1])
        for m in re.finditer(re.escape(first), img):
            a = m.start()
            if a % 2:
                continue
            addrs, cur, ok = {vals[0][0]: a}, a, True
            for off, v in vals[1:]:
                nxt = next((cur + 2 * k for k in range(1, 4)
                            if cur + 2 * k + 2 <= len(img) and s16(struct.unpack_from(">H", img, cur + 2 * k)[0]) == v), None)
                if nxt is None:
                    ok = False; break
                addrs[off], cur = nxt, nxt
            if ok:
                found.append((space, addrs))
            if len(found) > 1:
                return None
    return found[0] if len(found) == 1 else None


def main(capdir):
    # hits[(char, move)][strength] = [(frame, pc, field_off, value)]
    hits = collections.defaultdict(lambda: collections.defaultdict(list))
    for fn in sorted(os.listdir(capdir)):
        m = re.match(r"am_(\w+)\.txt$", fn)
        if not m:
            continue
        char = m.group(1)
        for line in open(os.path.join(capdir, fn), errors="replace"):
            r = re.match(r"RT W pc=0x(\w+) addr=0x(\w+) data=0x(\w+) mask=0x\w+ frame=(\d+) label=mv\|(\S+)\|(\w+)", line)
            if not r:
                continue
            pc, addr, data, frame = int(r.group(1), 16), int(r.group(2), 16), int(r.group(3), 16), int(r.group(4))
            off = addr - P1
            if off not in FIELD or any(lo <= pc <= hi for lo, hi in GENERIC):
                continue
            hits[(char, r.group(5).replace("_", " "))][BTN.get(r.group(6), r.group(6))].append((frame, pc, off, s16(data)))

    out, skipped = collections.defaultdict(dict), []
    users = collections.defaultdict(set)          # rom addr -> {"char move"}
    for (char, move), by_str in sorted(hits.items()):
        # every setter (pc, field) in order of first use -> stable key / label
        order = sorted({(f, pc, off) for lst in by_str.values() for f, pc, off, v in lst})
        setters = []
        for _f, pc, off in order:
            if (pc, off) not in setters:
                setters.append((pc, off))
        phase, names = collections.Counter(), {}
        for pc, off in setters:
            phase[off] += 1
            key, label = FIELD[off]
            if phase[off] > 1:
                key, label = f"{key}{phase[off]}", f"{label} (phase {phase[off]})"
            names[(pc, off)] = (key, label)
        entry = {}
        for strength, lst in by_str.items():
            fields = []
            lst = sorted(lst)
            # register-sourced writes, grouped by frame, resolved as one sequence
            reg_groups = collections.defaultdict(list)
            for frame, pc, off, v in lst:
                key, label = names[(pc, off)]
                ins = instr_ending_at(pc, off)
                desc = f"{ins.mnemonic} {ins.op_str}" if ins else "?"
                if ins is None:
                    skipped.append(f"{char} {move} {strength} {label}: no matching instruction at 0x{pc:06X}"); continue
                m0 = ins.mnemonic.split(".")[0]
                if m0 in ("clr", "neg", "add", "sub"):
                    continue                          # stop / facing flip / adjust: not a tunable value
                src = ins.op_str[:ins.op_str.rfind(",")].strip()   # source = all but the last operand
                mt = re.match(r"\$([0-9a-f]+)\(pc, d\d\.[wl]\)$", src)
                mi = re.match(r"#\$([0-9a-f]+)$", src)
                ma = re.match(r"(?:\$([0-9a-f]+))?\(a(\d)(?:, d\d\.[wl])?\)$", src)
                addr = space = base = None
                if mt and ins.mnemonic == "move.w":
                    base = int(mt.group(1), 16)
                    cands = [a for a in range(base, base + 0x60, 2) if word(a) == v]
                    if cands:
                        addr, space = cands, "op"
                elif ma:
                    # read through an address register: find the lea/movea that
                    # loaded it; the table is raw data (a data read, no decryption)
                    disp, reg = int(ma.group(1) or "0", 16), ma.group(2)
                    tbase = areg_base(ins.address, reg)
                    if tbase is not None:
                        base = tbase + disp
                        cands = [a for a in range(base, base + 0x60, 2)
                                 if s16(struct.unpack_from(">H", DATA, a)[0]) == v]
                        if cands:
                            addr, space = cands, "raw"
                    if addr is None and v != 0:
                        reg_groups[frame].append((pc, off, v, key, label))   # record search instead
                        continue
                elif mi and ins.mnemonic == "move.w":
                    if v == 0:
                        continue      # a 'stop' (#0) write, not a tunable movement value
                    if word(ins.address + 2) == v:
                        addr, space = [ins.address + 2], "op"
                elif mi and ins.mnemonic == "move.l":
                    if v == 0:
                        continue      # 'stop' write
                    dst_off = int(re.search(r"\$([0-9a-f]+)\(a6\)", ins.op_str).group(1), 16)
                    a = ins.address + 2 + (2 if off != dst_off else 0)
                    if word(a) == v:
                        addr, space = [a], "op"
                elif (re.match(r"d\d$", src) or re.search(r"\(a\d", src)) and v != 0:
                    # from a data register, or read through an address register
                    # (a raw data record at a runtime address): resolve the values
                    # written together as one record
                    reg_groups[frame].append((pc, off, v, key, label))
                    continue
                if addr is None:
                    if v != 0:
                        skipped.append(f"{char} {move} {strength} {label}: {desc} (value {v})")
                    continue
                fields.append({"key": key, "label": label, "cands": addr, "space": space,
                               "setter": "0x%06X" % pc, "ins": desc, "value": v,
                               "base": base})
            for frame, grp in reg_groups.items():
                grp.sort()
                seq = [(off, v) for _pc, off, v, _k, _l in grp]
                res = find_sequence(seq) if len(seq) >= 3 else None
                if res is None:
                    for _pc, off, v, _k, label in grp:
                        skipped.append(f"{char} {move} {strength} {label}: from a register; "
                                       f"values {[x[1] for x in seq]} not found uniquely as a record")
                    continue
                space, addrs = res
                for pc, off, v, key, label in grp:
                    fields.append({"key": key, "label": label, "cands": [addrs[off]], "space": space,
                                   "setter": "0x%06X" % pc, "ins": "register (record)", "value": v})
            entry[strength] = fields
        # table candidates, step 1: within one strength, every table read of this
        # move uses the same index register, so a field whose value is unique pins
        # the index offset (addr - table base) for the others. (Cammy's slowdown is
        # -32 for every strength; only the speed tells the records apart.)
        # Fields set by one routine (setter PCs within 0x30 bytes) share that
        # index, so each strength's offset is voted on by every field of the
        # routine whose value sits at base+offset; the winner resolves them all.
        for s, e in entry.items():
            tab = sorted((f for f in e if f.get("base") is not None), key=lambda f: int(f["setter"], 16))
            clusters, cur = [], []
            for f in tab:
                if cur and int(f["setter"], 16) - int(cur[-1]["setter"], 16) > 0x30:
                    clusters.append(cur); cur = []
                cur.append(f)
            if cur:
                clusters.append(cur)
            for cl in clusters:
                votes = collections.Counter(c - f["base"] for f in cl for c in f["cands"])
                if not votes:
                    continue
                top = max(votes.values())
                off = min(o for o, n in votes.items() if n == top)
                for f in cl:
                    if f["base"] + off in f["cands"]:
                        f["cands"] = [f["base"] + off]
        # step 2: anything still ambiguous -> one address per strength, preferring a single stride
        for key in {f["key"] for e in entry.values() for f in e}:
            items = [(s, f) for s, e in entry.items() for f in e if f["key"] == key]
            multi = [(s, f) for s, f in items if len(f["cands"]) > 1]
            if multi:
                combos = list(itertools.islice(itertools.product(*[f["cands"] for _s, f in items]), 5000))
                def score(c):
                    pairs = sorted(zip([s for s, _f in items], c))
                    return (len({b - a for (_x, a), (_y, b) in zip(pairs, pairs[1:])}), sum(c))
                best = min(combos, key=score)
                for (_s, f), a in zip(items, best):
                    f["cands"] = [a]
        for s, e in entry.items():
            entry[s] = [{"key": f["key"], "label": f["label"], "addr": "0x%06X" % f["cands"][0],
                         "space": f["space"], "setter": f["setter"], "ins": f["ins"]} for f in e]
            for f in entry[s]:
                users[f["addr"]].add(f"{char} {move}")
        entry = {s: e for s, e in entry.items() if e}
        if entry:
            out[char][move] = entry
    for char, moves in out.items():
        for move, by_s in moves.items():
            for s, fl in by_s.items():
                for f in fl:
                    others = sorted(users[f["addr"]] - {f"{char} {move}"})
                    if others:
                        f["shared_with"] = others
    path = os.path.join(HERE, "move_physics.json")
    json.dump(out, open(path, "w"), indent=1)
    n = sum(len(m) for m in out.values())
    print(f"wrote {path}: {n} moves over {len(out)} characters")
    for char, moves in sorted(out.items()):
        for move, by_s in moves.items():
            ks = sorted({f['label'] for fl in by_s.values() for f in fl})
            sp = sorted({f['space'] for fl in by_s.values() for f in fl})
            print(f"  {char:9s} {move:30s} {len(by_s)} str [{'/'.join(sp)}]: {', '.join(ks)}")
    print(f"skipped {len(skipped)}:")
    for s in skipped:
        print("   ", s)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SSF2T_WORK", "."))
