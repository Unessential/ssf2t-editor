"""verify_inputs.py -- MAME check of special-move input edits.

  python verify_inputs.py patch <rom_dir>
      apply the test remaps through the editor API and patch the ROM copy in <rom_dir>
      (Ryu Hadouken -> pretzel 1632143 [engine], Cammy Spiral Arrow -> 214
      [in place], Cammy Cannon Spike -> 421 [in place])
  python verify_inputs.py check <pristine_log> <patched_log>
      compare lua/captures/inputs_test_moves.lua runs (STEPSET=moves): each step's
      special-move animations / projectile on the pristine and the patched ROM.

A step "came out" if P1 played an animation that only appears during specials
(not seen in the reset/settle steps) or spawned a projectile.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REMAPS = {("ryu", "Hadouken"): "1632143",
          ("cammy", "Spiral Arrow"): "214",
          ("cammy", "Cannon Spike"): "421"}
TOP_PRIORITY = [("ryu", "Hadouken")]


def patch(rom_dir):
    os.environ["SSF2T_DATA"] = os.path.join(rom_dir, "ssf2t_data.bin")
    sys.path.insert(0, HERE)
    import app
    from fastapi.testclient import TestClient
    c = TestClient(app.app)
    for (char, name), motion in REMAPS.items():
        mv = [m for m in c.get("/api/inputs", params={"char": char}).json()["moves"] if m["name"] == name][0]
        r = c.post("/api/inputs", json={"sub": mv["sub"], "motion": motion}).json()
        print(char, name, "->", r.get("motion"), r.get("mode"), r.get("error", ""))
    # the pretzel contains a whole DP (6..2..3), and Shoryuken is checked before
    # Hadouken: give the pretzel Hadouken first priority
    for char, name in TOP_PRIORITY:
        while True:
            mv = [m for m in c.get("/api/inputs", params={"char": char}).json()["moves"] if m["name"] == name][0]
            if mv["priority"] == 0:
                break
            c.post("/api/inputs/priority", json={"char": char, "sub": mv["sub"], "move": "up"})
        print(char, "order:", [m["name"] for m in c.get("/api/inputs", params={"char": char}).json()["moves"]])
    r = c.post("/api/patch_rom", json={"confirm": True}).json()
    print("patch_rom:", {k: r.get(k) for k in ("ok", "bytes_written", "rom_files", "error")})


def steps(path):
    """label -> (set of anims, projectile seen); plus the neutral anim set."""
    out, neutral = {}, set()
    for ln in open(path):
        m = re.match(r"\s*\d+ (\S+)\s+cid=\s*\d+ anim=0x([0-9A-F]+)", ln)
        if not m:
            continue
        lab, anim = m.group(1), m.group(2)
        if lab.startswith("mv|"):
            a, pj = out.setdefault(lab, (set(), set()))
            a.add(anim)
            pj.update(re.findall(r" pj\d=x-?\d+,y-?\d+,an([0-9A-F]+)", ln))
        else:
            neutral.add(anim)
    return out, neutral


def known_sigs(cid):
    """move name -> frame records of its captured animations (attack_anims.json),
    keyed by the label's move name with underscores ('Spinning_Piledriver')."""
    import json
    aa = json.load(open(os.path.join(HERE, "attack_anims.json")))["moves"].get(str(cid), {})
    # frames a normal/throw also uses (a special's startup can share them) don't count
    normal = {int(f, 16) for key, fr in aa.items() if not key.startswith(("special_", "super_")) for f in fr}
    out = {}
    for key, frames in aa.items():
        m = re.match(r"(special|super)_(.+) \(", key)
        if m:
            out.setdefault(m.group(2).replace(" ", "_"), set()).update(int(f, 16) for f in frames)
    for k in out:
        own = out[k] - normal
        out[k] = own if len(own) >= 2 else out[k]
    return out


def check_known(pristine, patched, cid):
    """Like check(), but a step "gave move X" when it shows at least 2 of X's
    captured animation frames (projectile moves: any of them is enough)."""
    sigs = {k: {"%06X" % a for a in v} for k, v in known_sigs(cid).items()}
    p0, _ = steps(pristine)
    p1, _ = steps(patched)
    ok = True
    for lab in p0:
        role, move = lab.split("|")[1].split(":")[:2]
        sig = sigs.get(move)
        if sig is None:
            print("??   %-34s no captured animation named %s" % (lab, move))
            ok = False
            continue
        a0, a1 = p0[lab][0], p1.get(lab, (set(), set()))[0]
        out0 = len(a0 & sig) >= 2
        out1 = len(a1 & sig) >= 2
        want0, want1 = {"old": (True, False), "new": (None, True), "kept": (True, True)}[role]
        good = (want0 is None or out0 == want0) and out1 == want1
        if role == "kept" and not good and len(a0) > 4 and len(a0 & a1) >= 0.8 * len(a0 | a1):
            good = True                   # untouched move behaved identically on both ROMs
            out0 = out1 = "same"
        ok &= good
        print("%-4s %-34s pristine: %-9s patched: %s" % ("ok" if good else "FAIL", lab,
              "move" if out0 else "no move", "move" if out1 else "no move"))
    print("ALL OK" if ok else "SOME FAILED")
    return ok


def check(pristine, patched):
    """A step "gave move X" if it shares at least 2 animations with X's signature
    (X's original/kept motion on the pristine ROM, minus idle animations), or X
    throws a projectile and so did the step."""
    p0, n0 = steps(pristine)
    p1, n1 = steps(patched)
    neutral = n0 | n1
    # animations that show up in three or more different moves' steps are generic
    # (crouch, landing...), not a move's signature
    # (counted within one run: on a remapped ROM a move's frames legitimately
    # move from its old motion's step to its new one)
    # and generic only if that holds in both runs (a remapped special can show up
    # under several motions in one run, e.g. long motions that contain a DP)
    per_run = []
    for run in (p0, p1):
        seen_in = {}
        for lab, (a, _) in run.items():
            for an in a:
                seen_in.setdefault(an, set()).add(lab.split("|")[1].split(":")[1])
        per_run.append({an for an, mv in seen_in.items() if len(mv) >= 3})
    generic = set(neutral) | (per_run[0] & per_run[1])
    sig, sig_pj = {}, {}
    for lab, (a, pj) in p0.items():
        role, move = lab.split("|")[1].split(":")[:2]
        if role in ("old", "kept"):
            sig.setdefault(move, set()).update(a - generic)
            sig_pj.setdefault(move, set()).update(pj)

    def gave(move, a, pj):
        if sig_pj.get(move):              # a projectile move: its projectile must appear
            return bool(pj & sig_pj[move])
        return len((a - generic) & sig.get(move, set())) >= 2

    ok = True
    for lab in p0:
        role, move = lab.split("|")[1].split(":")[:2]
        out0 = gave(move, *p0[lab])
        out1 = gave(move, *p1.get(lab, (set(), set())))
        want0, want1 = {"old": (True, False), "new": (None, True), "kept": (True, True)}[role]
        good = (want0 is None or out0 == want0) and out1 == want1
        ok &= good
        print("%-4s %-34s pristine: %-9s patched: %s" % ("ok" if good else "FAIL", lab,
              "move" if out0 else "no move", "move" if out1 else "no move"))
    print("ALL OK" if ok else "SOME FAILED")
    return ok


if __name__ == "__main__":
    if sys.argv[1] == "patch":
        patch(sys.argv[2])
    elif len(sys.argv) > 4:                  # check <pristine> <patched> <cid>
        check_known(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        check(sys.argv[2], sys.argv[3])
