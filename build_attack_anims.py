"""build_attack_anims.py -- attack_anims.json entries from headless MAME captures.

Inputs (lua/captures/run_normals.sh, run_allmoves.sh):
  <pfx>_n_<char>.txt   STEPSET=normals   steps n_stand_LP .. n_jump_HK
  <pfx>_t_<char>.txt   STEPSET=reactions steps thrown (by P2 = Ken), p1_throw
  <pfx>_m_<char>.txt   STEPSET=moves     steps mv|<Move>|<BTN>
Each frame line logs P1's frame record (anim=0x...). A move's frames are the
records seen during its step, in first-seen order, minus "neutral" records
(the character's stand / walk / crouch / jump / turn animations from its own
anim list for that version), so only the attack itself is kept (jumping normals
keep their attack frames, not the jump). Specials that never left neutral --
the input didn't come out, or the version doesn't have the move -- are dropped.

Usage:
  python build_attack_anims.py check <capdir> <pfx>        compare to attack_anims.json (new version)
  python build_attack_anims.py write <capdir> <pfx> old    add "<cid>_old" entries
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def app_module():
    import app
    return app


BTN = {"LP": "Weak Punch", "MP": "Medium Punch", "HP": "Strong Punch",
       "LK": "Weak Kick", "MK": "Medium Kick", "HK": "Strong Kick",
       "PPP": "3 Punches", "KKK": "3 Kicks"}
# STEPSET=cmdnormals step kinds -> (category, variant shown in the move name)
CMD_KINDS = {"close": ("stand", "close"), "f": ("stand", "forward"), "b": ("stand", "back"),
             "cclose": ("crouch", "close"), "df": ("crouch", "down-forward"), "db": ("crouch", "down-back"),
             "jf": ("jump", "diagonal"), "jd": ("jump", "down"), "jfd": ("jump", "diagonal, down")}
NEUTRAL = re.compile(r"\b(stand|walk|crouch|jump|turn)", re.I)
LINE = re.compile(r"\s*\d+\s+(\S+)\s+cid=\s*(\d+) anim=0x(\w+)")


def neutral_frames(client, char, ver):
    """Frame records of the character's neutral anims (labels from the editor)."""
    out = set()
    j = client.get(f"/api/animlist?char={char}&ver={ver}").json()
    for a in j.get("anims", []):
        lab = a["label"].rstrip("?")
        if a["index"] == 0 or (NEUTRAL.search(lab) and not re.search(r"hit|block|knock|thrown", lab, re.I)):
            fr = client.get(f"/api/charanim?char={char}&ver={ver}&anim={a['index']}").json().get("frames", [])
            out |= {f["offset"] for f in fr}
    return out


def steps(path):
    seq = collections.OrderedDict()
    cids = collections.Counter()
    if not os.path.exists(path):
        return seq, None
    for line in open(path, errors="replace"):
        m = LINE.match(line)
        if not m:
            continue
        lab, cid, anim = m.group(1), m.group(2), int(m.group(3), 16)
        cids[cid] += 1
        seq.setdefault(lab, []).append(anim)
    return seq, (cids.most_common(1)[0][0] if cids else None)


def moves_for(capdir, pfx, char, client, ver, existing=None):
    neutral = neutral_frames(client, char, ver)
    out = {}

    data = bytes(app_module().WORKING)

    def fill(frames):
        """Insert records a per-video-frame sample skipped: if b follows a in the
        same 0x18-stride chain (no terminator between, at most 4 slots), the
        records between them were shown for a tick each."""
        out = []
        for a in frames:
            if out:
                p = out[-1]
                gap = a - p
                if 0 < gap <= 4 * 0x18 and gap % 0x18 == 0:
                    ok = all(not (int.from_bytes(data[r + 2:r + 4], "big") & 0x8000)
                             for r in range(p, a, 0x18))
                    if ok:
                        out.extend(range(p + 0x18, a, 0x18))
            out.append(a)
        return out

    def keep(frames):
        o = []
        for a in fill([f for f in frames if f not in neutral]):
            if a not in neutral and a not in o:
                o.append(a)
        return ["0x%06X" % a for a in o]

    seq, cid = steps(os.path.join(capdir, f"{pfx}_n_{char}.txt"))
    for lab, frames in seq.items():
        m = re.match(r"n_(stand|crouch|jump)_(\w\w)$", lab)
        if m:
            k = keep(frames)
            if k:
                out[f"{m.group(1)}_{BTN[m.group(2)]}"] = k
    # command / diagonal-jump / close normals (STEPSET=cmdnormals). One is kept
    # only if it is a different attack from the plain normal and from the
    # variants already kept for that button (e.g. most characters' back + LP is
    # just their LP).
    seq, _ = steps(os.path.join(capdir, f"{pfx}_c_{char}.txt"))
    for lab, frames in seq.items():
        m = re.match(r"c_(\w+?)_(\w\w)$", lab)
        if not m or m.group(1) not in CMD_KINDS:
            continue
        cat, variant = CMD_KINDS[m.group(1)]
        k = keep(frames)
        if len(k) < 2:
            continue
        same_btn = [set(v) for key, v in {**(existing or {}), **out}.items()
                    if key == f"{cat}_{BTN[m.group(2)]}" or key.startswith(f"{cat}_{BTN[m.group(2)]} (")]
        if any(len(set(k) & s) >= max(1, len(k) // 2) for s in same_btn):
            continue
        out[f"{cat}_{BTN[m.group(2)]} ({variant})"] = k
    seq, _ = steps(os.path.join(capdir, f"{pfx}_t_{char}.txt"))
    if seq.get("thrown"):
        # stop where the throw hands over to the knockdown / get-up: the thrown
        # frames live outside the anim list, the knockdown that follows is in it
        down = set()
        for a in client.get(f"/api/animlist?char={char}&ver={ver}").json().get("anims", []):
            down |= {f["offset"] for f in client.get(
                f"/api/charanim?char={char}&ver={ver}&anim={a['index']}").json().get("frames", [])}
        fr = seq["thrown"]
        start = next((i for i, a in enumerate(fr) if a not in down), None)
        if start is None:
            fr = []
        else:
            cut = next((i for i in range(start, len(fr)) if fr[i] in down), len(fr))
            fr = fr[start:cut]
        k = keep(fr)
        if len(k) >= 3:                       # a real thrown animation, not a whiff
            out["thrown (by Ken)"] = k
    if seq.get("p1_throw"):
        k = keep(seq["p1_throw"])
        if len(k) >= 3:
            out["throw (forward + Strong Punch)"] = k
    seq, _ = steps(os.path.join(capdir, f"{pfx}_m_{char}.txt"))
    normal_frames = {a for k, v in out.items() for a in v}
    for lab, frames in seq.items():
        m = re.match(r"mv\|(.+)\|(\w+)$", lab)
        if not m:
            continue
        name, btn = m.group(1).replace("_", " "), m.group(2)
        k = keep(frames)
        # a "special" that is really one of the normals (the input came out as a
        # plain attack -- e.g. old Ken has no crazy kicks) is not a special
        if not k or len(set(k) & normal_frames) >= max(2, len(k) // 2):
            continue
        sup = name.endswith("(super)")
        if sup and ver == "old":
            continue                          # Super SF2 versions have no super combos
        base = name[:-len(" (super)")] if sup else name
        out[f"{'super' if sup else 'special'}_{base} ({BTN.get(btn, btn)})"] = k
    return out, cid


_BTN_ORDER = ["Weak Punch", "Medium Punch", "Strong Punch", "Weak Kick", "Medium Kick", "Strong Kick"]
_VAR_ORDER = ["", "close", "forward", "back", "down-forward", "down-back", "diagonal", "down", "diagonal, down"]


def order_moves(moves):
    """Normals grouped stand / crouch / jump, by button, plain before its variants;
    everything else (idle, specials, throws) after, in its existing order."""
    def rank(k):
        m = re.match(r"(stand|crouch|jump)_(.+?)(?: \((.+)\))?$", k)
        if not m or m.group(2) not in _BTN_ORDER:
            return None
        v = m.group(3) or ""
        return (["stand", "crouch", "jump"].index(m.group(1)), _BTN_ORDER.index(m.group(2)),
                _VAR_ORDER.index(v) if v in _VAR_ORDER else 99)
    normals = sorted((k for k in moves if rank(k) is not None), key=rank)
    return {**{k: moves[k] for k in normals}, **{k: v for k, v in moves.items() if rank(k) is None}}


def main():
    mode, capdir, pfx = sys.argv[1], sys.argv[2], sys.argv[3]
    ver = sys.argv[4] if len(sys.argv) > 4 else "new"
    import app
    from fastapi.testclient import TestClient
    client = TestClient(app.app)
    path = os.path.join(HERE, "attack_anims.json")
    aa = json.load(open(path))
    names = {v: k for k, v in aa["names"].items()}
    total_ok = total = 0
    for char in sorted(names, key=lambda c: int(names[c])):
        key = names[char] + ("_old" if ver == "old" else "")
        built, cid = moves_for(capdir, pfx, char, client, ver, aa["moves"].get(key, {}))
        if not built:
            continue
        if cid is not None and cid != names[char]:
            print(f"!! {char}: capture loaded character id {cid}, expected {names[char]} -- skipped")
            continue
        if mode == "addcmd":
            # add the command / diagonal / close normals only; existing entries untouched
            have = aa["moves"].setdefault(key, {})
            new = {k: v for k, v in built.items() if re.search(r" \((close|forward|back|down|diagonal)", k)
                   and not k.startswith(("special_", "super_")) and k not in have}
            aa["moves"][key] = order_moves({**have, **new})
            print(f"{char:9s} {ver}: +{len(new)} {sorted(new)}")
            continue
        if mode == "check":
            have = aa["moves"].get(names[char], {})
            same = [k for k in built if have.get(k) == built[k]]
            diff = [k for k in built if k in have and have[k] != built[k]]
            total_ok += len(same); total += len(built)
            print(f"{char:9s} built {len(built):2d}, identical {len(same):2d}, differ {diff}")
        else:
            key = names[char] + "_old"
            aa["moves"][key] = {**aa["moves"].get(key, {}), **built}
            print(f"{char:9s} old: {len(built)} moves -> moves[{key!r}]")
    if os.environ.get("DRY"):
        print("(dry run, nothing written)")
        return
    if mode == "check":
        print(f"identical {total_ok}/{total}")
    else:
        json.dump(aa, open(path, "w"), indent=1)
        print("wrote", path)


if __name__ == "__main__":
    main()
