"""label_old_anims.py -- confirm / fill old-version animation labels from captures.

Input: os_s_<char>.txt (default state steps) and os_h_<char>.txt (STEPSET=hits)
from lua/captures/run_states.sh with OLD=1. For each step, the old anim index P1
spends most of the step in (excluding standing) is the animation for that state:
  * a draft label there ("...?") that fits the state is confirmed (the "?" goes)
  * an unlabeled index gets the state's label
  * a label that contradicts the state is reported, not changed
Usage: python label_old_anims.py <capdir>
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# step -> (label to give an unlabeled index, regex an existing label must fit)
STATE = {
    "walk_fwd": ("Walk forward", r"walk"), "walk_back": ("Walk backward", r"walk"),
    "crouch": ("Crouch", r"crouch"), "stand_up": ("Stand up from crouch", r"stand up|crouch"),
    "jump_neutral": ("Jump neutral", r"jump"), "jump_fwd": ("Jump forward", r"jump"),
    "jump_back": ("Jump backward", r"jump"),
    "block_stand": ("Block standing", r"block stand"), "block_crouch": ("Block crouching", r"block crouch"),
    "hit_stand": ("Hit standing", r"hit stand"), "hit_crouch": ("Hit crouching", r"hit crouch"),
    "knockdown": ("Knockdown", r"knock|lying|fall"),
}
HITS = {"LP": "light punch", "MP": "medium punch", "HP": "heavy punch",
        "LK": "light kick", "MK": "medium kick", "HK": "heavy kick"}
for pose, word in (("st", "standing"), ("cr", "crouching")):
    for b, s in HITS.items():
        STATE[f"hit_{pose}_{b}"] = (f"Hit {word} ({s})", rf"hit {word}")
STATE["hit_st_fireball"] = ("Hit standing (special / fireball)", r"hit standing")
LINE = re.compile(r"\s*\d+\s+(\S+)\s+cid=\s*(\d+) anim=0x(\w+)")


def main(capdir):
    import app
    from fastapi.testclient import TestClient
    c = TestClient(app.app)
    path = os.path.join(HERE, "anim_labels.json")
    labels = json.load(open(path))
    report = collections.Counter()
    for char in [n for n in app._ROSTER[:16]]:
        idx = {}
        for a in c.get(f"/api/animlist?char={char}&ver=old").json().get("anims", []):
            for f in c.get(f"/api/charanim?char={char}&ver=old&anim={a['index']}").json().get("frames", []):
                idx.setdefault(f["offset"], a["index"])
        by = collections.defaultdict(collections.Counter)
        for tag in ("s", "h"):
            p = os.path.join(capdir, f"os_{tag}_{char}.txt")
            if not os.path.exists(p):
                continue
            for line in open(p, errors="replace"):
                m = LINE.match(line)
                if m and m.group(1) in STATE and int(m.group(3), 16) in idx:
                    i = idx[int(m.group(3), 16)]
                    if i != 0:
                        by[m.group(1)][i] += 1
        lab = labels.setdefault(char + "_old", {})
        # Reaction steps (block / hit / knockdown) are mostly spent walking back
        # or crouching to block: ignore the anims the movement steps identified.
        movement = {"walk_fwd", "walk_back", "crouch", "stand_up", "jump_neutral", "jump_fwd", "jump_back"}
        neutral = {cnt.most_common(1)[0][0] for st, cnt in by.items() if st in movement and cnt}
        for step, cnt in by.items():
            if step not in movement:
                cnt = collections.Counter({k: v for k, v in cnt.items() if k not in neutral})
            if not cnt:
                continue
            i = str(cnt.most_common(1)[0][0])
            give, fits = STATE[step]
            cur = lab.get(i)
            if cur is None:
                lab[i] = give; report["added"] += 1
            elif cur.endswith("?") and re.search(fits, cur, re.I):
                lab[i] = cur[:-1]; report["confirmed"] += 1
            elif not re.search(fits, cur.rstrip("?"), re.I):
                report["conflict"] += 1
                print(f"   {char} old anim {i}: label {cur!r} but seen in step {step}")
    json.dump(labels, open(path, "w"), indent=1)
    print(dict(report))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SSF2T_WORK", "."))
