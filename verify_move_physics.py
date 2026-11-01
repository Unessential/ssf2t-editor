"""verify_move_physics.py -- prove each move_physics.json entry in MAME.

  python verify_move_physics.py patch <rom_dir>   # +1 (1/256 px) at every mapped address
  python verify_move_physics.py check <capdir>    # read vf_<char>.txt captures of that ROM

`patch` writes original+1 at every distinct mapped address (opcode space through
CPS-2 re-encryption, raw space directly) into the ROM files in <rom_dir> via the
editor's own patch path. Then run lua/captures/run_allmoves.sh with
ROMPATH=<rom_dir> OUTPFX=vf. `check` confirms that, for each move and strength,
the entry's setter instruction now writes original+1: if so the address is the
one the game reads. Entries that fail are removed from move_physics.json (the
list is printed and kept in move_physics_rejected.json).
"""
import collections
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P1 = 0xFF844E
BTN = {"LP": "Weak Punch", "MP": "Medium Punch", "HP": "Strong Punch",
       "LK": "Weak Kick", "MK": "Medium Kick", "HK": "Strong Kick",
       "PPP": "3 Punches", "KKK": "3 Kicks"}
FIELD_OFF = {"speed": 0x3C, "rise": 0x3E, "slowdown": 0x40, "rise_slow": 0x42}


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def field_off(key):
    base = re.sub(r"\d+$", "", key)
    return FIELD_OFF[base]


def patch(rom_dir):
    os.environ["SSF2T_DATA"] = os.path.join(rom_dir, "ssf2t_data.bin")
    sys.path.insert(0, HERE)
    import app
    from fastapi.testclient import TestClient
    mp = json.load(open(os.path.join(HERE, "move_physics.json")))
    done = set()
    for char, moves in mp.items():
        for move, by_s in moves.items():
            for s, fl in by_s.items():
                for f in fl:
                    a = int(f["addr"], 16)
                    if (a, f["space"]) in done:
                        continue
                    done.add((a, f["space"]))
                    if f["space"] == "op":
                        app.OPCRYPT.write(app.WORKING, a, (app.OPCRYPT.read(app.WORKING, a) + 1) & 0xFFFF)
                    else:
                        v = struct.unpack_from(">H", app.WORKING, a)[0]
                        struct.pack_into(">H", app.WORKING, a, (v + 1) & 0xFFFF)
    r = TestClient(app.app).post("/api/patch_rom", json={"confirm": True}).json()
    print(f"patched {len(done)} addresses -> {r.get('bytes_written')} bytes in {r.get('rom_files')}")


def check(capdir):
    sys.path.insert(0, HERE)
    import opcrypt
    data = open(os.path.join(os.path.dirname(HERE), "ssf2t_data.bin"), "rb").read()
    crypt = opcrypt.OpCrypt(os.path.join(os.path.dirname(HERE), "ssf2t.key"))
    writes = collections.defaultdict(dict)      # (char, move, strength) -> {(pc, off): value}
    seen_chars = set()
    for fn in os.listdir(capdir):
        m = re.match(r"vf_(\w+)\.txt$", fn)
        if not m:
            continue
        seen_chars.add(m.group(1))
        for line in open(os.path.join(capdir, fn), errors="replace"):
            r = re.match(r"RT W pc=0x(\w+) addr=0x(\w+) data=0x(\w+) .*label=mv\|(\S+)\|(\w+)", line)
            if r:
                key = (m.group(1), r.group(4).replace("_", " "), BTN.get(r.group(5), r.group(5)))
                writes[key].setdefault((int(r.group(1), 16), int(r.group(2), 16) - P1), s16(int(r.group(3), 16)))
    path = os.path.join(HERE, "move_physics.json")
    mp = json.load(open(path))
    ok, bad, untested = 0, [], 0
    for char, moves in mp.items():
        if char not in seen_chars:
            untested += sum(len(fl) for by_s in moves.values() for fl in by_s.values())
            continue
        for move, by_s in moves.items():
            for s, fl in by_s.items():
                keep = []
                for f in fl:
                    a = int(f["addr"], 16)
                    orig = s16(crypt.read(data, a) if f["space"] == "op" else struct.unpack_from(">H", data, a)[0])
                    got = writes.get((char, move, s), {}).get((int(f["setter"], 16), field_off(f["key"])))
                    if got == s16((orig + 1) & 0xFFFF):
                        f["verified"] = True; keep.append(f); ok += 1
                    else:
                        bad.append({"char": char, "move": move, "strength": s, **f, "orig": orig, "written": got})
                by_s[s] = keep
            moves[move] = {s: fl for s, fl in by_s.items() if fl}
        mp[char] = {m: b for m, b in moves.items() if b}
    mp = {c: m for c, m in mp.items() if m}
    json.dump(mp, open(path, "w"), indent=1)
    json.dump(bad, open(os.path.join(HERE, "move_physics_rejected.json"), "w"), indent=1)
    print(f"verified {ok} entries, rejected {len(bad)}, untested {untested}; "
          f"{sum(len(m) for m in mp.values())} moves kept")
    for b in bad[:60]:
        print(f"   X {b['char']} {b['move']} {b['strength']} {b['label']} @{b['addr']}: orig {b['orig']}, wrote {b['written']}")


if __name__ == "__main__":
    {"patch": patch, "check": check}[sys.argv[1]](sys.argv[2])
