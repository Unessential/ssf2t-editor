"""analyze_movers.py -- summarize moving-special captures (run_movers.sh output).

For each mv|<move>|<button> step: which character loaded, the distinct movement
pointers (obj+0x30) in the order they appeared with the per-frame X/Y change
while each was active, and the code that wrote obj+0x30 (RT W lines).
Usage: python analyze_movers.py [capture_dir]
"""
import collections
import os
import re
import sys

capdir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SSF2T_WORK", ".")
LINE = re.compile(r"\s*(\d+)\s+(\S+)\s+cid=\s*(\d+) anim=0x(\w+) x1=\s*(-?\d+).*?mp=0x(\w+) xl=0x(\w+) yl=0x(\w+)")


VA = re.compile(r" v=(-?\d+),(-?\d+) a=(-?\d+),(-?\d+)")


def s32(h):
    v = int(h, 16)
    return v - (1 << 32) if v & 0x80000000 else v


PREFIX = os.environ.get("PREFIX", "mv")
for tag in ("honda", "cammy", "feilong"):
    path = os.path.join(capdir, f"{PREFIX}_{tag}.txt")
    if not os.path.exists(path):
        print(f"== {tag}: no capture"); continue
    rows, writers = [], {}
    raw = collections.defaultdict(list)          # label -> raw lines (for v/a)
    for line in open(path):
        lm = re.match(r"\s*\d+\s+(mv\|\S+)", line)
        if lm:
            raw[lm.group(1)].append(line)
        if line.startswith("RT W"):
            m = re.search(r"pc=0x(\w+) addr=0x(\w+) data=0x(\w+)", line)
            writers.setdefault((m.group(1), m.group(2)), m.group(3))   # first value written
            continue
        m = LINE.match(line)
        if m:
            rows.append(m.groups())
    cids = collections.Counter(r[2] for r in rows if r[1].startswith("mv|"))
    print(f"== {tag}: P1 cid {dict(cids)}; obj+0x30 writers (pc, addr): {sorted(writers)[:12]}")
    by = collections.OrderedDict()
    for r in rows:
        if r[1].startswith("mv|"):
            by.setdefault(r[1], []).append(r)
    for label, rs in by.items():
        segs = []   # (mp, frames, dx/frame list, dy/frame list)
        prev = None
        for r in rs:
            mp, xl, yl = r[5], s32(r[6]), s32(r[7])
            if prev is not None:
                dx, dy = (xl - prev[0]) / 65536, (yl - prev[1]) / 65536
                if segs and segs[-1][0] == mp:
                    segs[-1][1] += 1; segs[-1][2].append(dx); segs[-1][3].append(dy)
                else:
                    segs.append([mp, 1, [dx], [dy]])
            prev = (xl, yl)
        print(f"  {label}")
        for mp, n, dxs, dys in segs:
            moving = [d for d in dxs if d] or [0]
            print(f"     mp=0x{mp}  {n:3d}f  x/frame {min(moving):+.3f}..{max(moving):+.3f}"
                  f"  total dx {sum(dxs):+.1f}  dy {sum(dys):+.1f}")
        # velocity/deceleration: print each frame where (a) changes or v jumps
        # (anything other than the mover's own v -= a step)
        pv = pa = None
        for r, line_v in zip(rs, [VA.search(x) for x in raw[label]]):
            if not line_v:
                continue
            vx, vy, ax, ay = (int(g) for g in line_v.groups())
            if pa is None or (ax, ay) != pa or (pv is not None and abs(vx - pv[0]) > max(abs(ax) * 3, 1) and vx != 0):
                print(f"       f{r[0]} anim=0x{r[3]}  v=({vx},{vy})  a=({ax},{ay})")
            pv, pa = (vx, vy), (ax, ay)
    print(f"  obj+0x3C..0x43 writers: " + ", ".join(f"pc={p} @{a}={writers[(p, a)]}" for (p, a) in sorted(writers)))
