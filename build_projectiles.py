"""build_projectiles.py -- projectiles.json from headless MAME captures.

Input: proj_<char>.txt logs from mame_states.lua (STEPSET=moves), whose frame
lines carry `pjN=x..,y..,an<anim>,hb<hitbox block>,vel<speed entry>` for every
active projectile slot owned by P1 (slots: 8 x 0xC0 from 0xFF97A2, pof layout).

Per move and strength it records the projectile's frame records in the order
the game showed them, its hitbox block (obj+0x34) and the ROM slot its speed
pointer (obj+0x30) is loaded from. Speed slots were found by disassembly of
each spawn routine (`lea tbl(pc),a1; move.l (a1,d0.w),$30(a6)` -> raw data;
Dhalsim's `move.l tbl(pc,d0.w)` and the Shinku `move.l #imm` are fetched
through CPS-2 decryption -> "op"). Each build checks the slot decodes to the
speed entry the capture saw, so a wrong slot fails loudly.

Usage: python build_projectiles.py <capture dir>
"""
import json
import os
import re
import struct
import sys

import opcrypt

HERE = os.path.dirname(os.path.abspath(__file__))
import paths
DATA = paths.DATA_BIN
BTN = {"LP": "Weak Punch", "MP": "Medium Punch", "HP": "Strong Punch",
       "LK": "Weak Kick", "MK": "Medium Kick", "HK": "Strong Kick"}
STRENGTH = {"LP": 0, "MP": 1, "HP": 2, "LK": 0, "MK": 1, "HK": 2}

# (char, move) -> (slot base, space). Entry for strength s is base + 4*s, except
# fixed slots (one strength only) which are given with idx=None.
SPEED_SLOTS = {
    ("ryu", "Hadouken"): (0x07206E, "raw"),             # spawn 0x071FEC
    ("ryu", "Shakunetsu Hadouken"): (0x07206E, "raw"),  # same spawn routine
    ("ryu", "Shinku Hadouken (super)"): (0x07425C, "op", "fixed"),  # move.l #imm at 0x07425A
    ("ken", "Hadouken"): (0x06EB50, "raw"),             # spawn 0x06EAF4
    ("guile", "Sonic Boom"): (0x070FC2, "raw"),         # spawn 0x070F66
    ("chunli", "Kikoken"): (0x0731C6, "raw"),           # spawn 0x07315E
    ("dhalsim", "Yoga Fire"): (0x06EEA8, "op"),         # spawn 0x06EE52, PC-relative indexed
    ("sagat", "Tiger Shot"): (0x071440, "raw"),         # spawn 0x0713DC
    ("sagat", "Ground Tiger Shot"): (0x071440, "raw"),
    ("deejay", "Air Slasher"): (0x073C0C, "raw"),       # spawn 0x073BAA
}


def main(capdir):
    data = open(DATA, "rb").read()
    crypt = opcrypt.OpCrypt(os.path.join(os.path.dirname(HERE), "ssf2t.key"))

    def read_long(addr, space):
        if space == "op":
            return (crypt.read(data, addr) << 16) | crypt.read(data, addr + 2)
        return struct.unpack_from(">I", data, addr)[0]

    out = {}
    for fn in sorted(os.listdir(capdir)):
        m = re.match(r"proj_(\w+)\.txt$", fn)
        if not m:
            continue
        char = m.group(1)
        moves = {}
        for line in open(os.path.join(capdir, fn)):
            lm = re.match(r"\s*\d+\s+mv\|(\S+)\|(\w+)", line)
            if not lm:
                continue
            name, btn = lm.group(1).replace("_", " "), lm.group(2)
            for pj in re.finditer(r"pj(\d)=x-?\d+,y-?\d+,an([0-9A-F]+),hb([0-9A-F]+),vel([0-9A-F]+)", line):
                e = moves.setdefault(name, {}).setdefault(btn, {"anims": [], "hb": set(), "vel": set()})
                a = "0x" + pj.group(2)
                if a not in e["anims"]:
                    e["anims"].append(a)
                e["hb"].add(int(pj.group(3), 16))
                e["vel"].add(int(pj.group(4), 16))
        for name, by_btn in moves.items():
            slot = SPEED_SLOTS.get((char, name))
            if slot is None:
                print(f"skip {char}/{name}: no speed slot mapped")
                continue
            for btn, e in by_btn.items():
                assert len(e["hb"]) == 1 and len(e["vel"]) == 1, (char, name, btn, e)
                hb, vel = e["hb"].pop(), e["vel"].pop()
                addr = slot[0] if len(slot) > 2 else slot[0] + 4 * STRENGTH[btn]
                got = read_long(addr, slot[1])
                assert got == vel, f"{char}/{name}/{btn}: slot 0x{addr:06X} holds 0x{got:06X}, capture saw 0x{vel:06X}"
                out.setdefault(char, {}).setdefault(name, {})[BTN[btn]] = {
                    "anims": e["anims"], "hitbox_block": "0x%06X" % hb,
                    "speed_slot": "0x%06X" % addr, "speed_space": slot[1]}
                print(f"ok {char:8s} {name:26s} {btn} hb=0x{hb:06X} speed slot 0x{addr:06X} ({slot[1]})")
    path = os.path.join(HERE, "projectiles.json")
    json.dump(out, open(path, "w"), indent=1)
    print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
