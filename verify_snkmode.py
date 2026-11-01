"""verify_snkmode.py -- the UI's "SNK mode" secret button, reproduced on the
backend (same assignment rules as secretCrazy() in static/index.html).

  python verify_snkmode.py list [snk|ss]             print what every move gets
  python verify_snkmode.py patch <rom_dir> [snk|ss]  apply it and patch the ROM copy in <rom_dir>
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETS = {"snk": (["1632143", "2363214", "2141236", "641236", "632146", "41236236"], True),
        "ss": (["3214623", "341236421", "6321464", "123623", "32421"], False)}


def subseq(a, b):
    it = iter(b)
    return all(c in it for c in a)
CHARS = ["ryu", "honda", "blanka", "guile", "ken", "chunli", "zangief", "dhalsim",
         "dictator", "sagat", "boxer", "claw", "cammy", "thawk", "feilong", "deejay"]


def assign(client, which="snk"):
    CRAZY, pretzel = SETS[which]
    done, out, k = set(), [], 0
    for char, ver in [(c, "new") for c in CHARS] + [("akuma", "new")] + [(c, "old") for c in CHARS]:
        r = client.get("/api/inputs", params={"char": char, "ver": ver})
        if r.status_code != 200:
            continue
        used = {"P": [], "K": []}
        for m in r.json()["moves"]:
            if not m["editable"] or m.get("kind") == "mash" or m["sub"] in done:
                continue
            done.add(m["sub"])
            grp = "K" if m["button"] == "K" else "P"
            mot = "1632143" if pretzel and re.fullmatch(r"(gou )?hadouken", (m["name"] or "").lower()) else None
            for t in range(len(CRAZY)):
                if mot:
                    break
                c = CRAZY[(k + t) % len(CRAZY)]
                clash = any(subseq(c, u) or subseq(u, c) for u in used[grp])
                if not (pretzel and c == "1632143") and not clash and len(c) <= m["max_dirs"]:
                    mot = c
            if not mot:
                continue
            used[grp].append(mot)
            k += 1
            out.append((char, ver, m["name"], m["button"], m["original"] or m.get("kind"), mot, m["sub"]))
    return out


def main():
    which = next((a for a in sys.argv[2:] if a in SETS), "snk")
    rom_dir = next((a for a in sys.argv[2:] if os.path.isdir(a)), None)
    if sys.argv[1] == "patch":
        os.environ["SSF2T_DATA"] = os.path.join(rom_dir, "ssf2t_data.bin")
    sys.path.insert(0, HERE)
    import app
    from fastapi.testclient import TestClient
    c = TestClient(app.app)
    plan = assign(c, which)
    for row in plan:
        print("%-8s %-3s %-28s %-2s %-10s -> %s" % row[:6])
    if sys.argv[1] == "patch":
        for row in plan:
            r = c.post("/api/inputs", json={"sub": row[6], "motion": row[5]})
            assert r.status_code == 200, (row, r.text)
        print(c.post("/api/patch_rom", json={"confirm": True}).json().get("rom_files"))
    print(len(plan), "moves")


if __name__ == "__main__":
    main()
