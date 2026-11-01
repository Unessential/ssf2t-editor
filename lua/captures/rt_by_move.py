"""rt_by_move.py -- list write-tap hits (RT W lines) per move label, skipping the
per-tick mover (0x002F50..0x002F80), so only the code that SETS velocity or
deceleration remains. Usage: PREFIX=mv python rt_by_move.py"""
import collections
import os
import re

capdir = os.environ.get("SSF2T_WORK", ".")
prefix = os.environ.get("PREFIX", "mv")
for tag in ("honda", "cammy", "feilong"):
    p = os.path.join(capdir, f"{prefix}_{tag}.txt")
    if not os.path.exists(p):
        continue
    by = collections.defaultdict(list)
    installed = False
    for line in open(p):
        if line.startswith("RT installed"):
            installed = True
        m = re.match(r"RT W pc=0x(\w+) addr=0x(\w+) data=0x(\w+) .*label=(\S+)", line)
        if m and m.group(4).startswith("mv|"):
            pc = int(m.group(1), 16)
            if 0x2F50 <= pc <= 0x2F82:
                continue
            by[m.group(4)].append((m.group(1), m.group(2)[-2:], int(m.group(3), 16)))
    print(f"== {tag} (tap installed: {installed})")
    for label, hits in by.items():
        print(f"  {label}: " + ", ".join(f"pc={pc} +{a}={v if v < 0x8000 else v - 0x10000}" for pc, a, v in hits))
