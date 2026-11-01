"""selftest.py -- prove the edit -> patch -> ROM round-trip without the server.

Edits Ryu's id1 rad_x (0x1C -> 0x20) at flat 0x06ED56, then:
  * IPS: confirm it targets sfxe.03c at 0x06ED57 (= flat ^ 1) and that applying
    it to a real copy of sfxe.03c flips exactly that one byte.
  * BPS: build against the real sfxe.03c, recompute CRCs, apply, round-trip.
  * MRA: confirm well-formed XML and the UNVERIFIED label is present.
"""
import os
import xml.dom.minidom
import cps2_map
import exporters

import paths
ST = os.environ.get("ST_DIR", paths.ROM_DIR)
DATA = os.path.join(ST, "ssf2t_data.bin")

orig = open(DATA, "rb").read()
work = bytearray(orig)

FLAT = 0x06ED56  # Ryu id1 rad_x
assert work[FLAT] == 0x1C, "unexpected starting byte 0x%02X" % work[FLAT]
work[FLAT] = 0x20
print("STEP 1-2  flat 0x%06X: 0x1C -> 0x%02X" % (FLAT, work[FLAT]))

changes = exporters.diff_flat(orig, bytes(work))
groups = exporters.group_changes_by_eprom(changes)
print("STEP 3    changed:", [(hex(f), hex(b)) for f, b in changes], "EPROMs:", list(groups))
assert list(groups) == ["sfxe.03c"]

# IPS
ips = exporters.build_ips(groups["sfxe.03c"])
print("STEP 4    IPS bytes:", ips.hex())
# record offset must be flat ^ 1
name, eoff = cps2_map.flat_to_eprom(FLAT)
assert (name, eoff) == ("sfxe.03c", 0x06ED57), (name, hex(eoff))
assert ips[5:8] == bytes.fromhex("06ED57"), ips[5:8].hex()
print("STEP 4a   IPS targets sfxe.03c @ 0x%06X (= flat ^ 1)  OK" % eoff)

eprom = open(os.path.join(ST, "sfxe.03c"), "rb").read()
patched = exporters.apply_ips(eprom, ips)
diffs = [i for i in range(len(eprom)) if eprom[i] != patched[i]]
assert diffs == [0x06ED57] and patched[0x06ED57] == 0x20, diffs
assert patched[eoff] == work[FLAT], "patched EPROM byte != edited flat byte under F^1"
print("STEP 4b   sfxe.03c[0x06ED57] 0x1C -> 0x20, exactly 1 byte changed  OK")

# BPS
tgt = bytearray(eprom); tgt[0x06ED57] = 0x20
bps = exporters.build_bps(eprom, bytes(tgt))
assert bps[:4] == b"BPS1"
back = exporters.apply_bps(eprom, bps)
assert back == bytes(tgt), "BPS round-trip mismatch"
print("STEP 5    BPS build + CRC footer + apply round-trip  OK")

# MRA
mra = exporters.build_mra(changes, src_md5="none")
xml.dom.minidom.parseString(mra)  # raises if malformed
assert "UNVERIFIED" in mra and 'offset="0x6ED57"'.lower() in mra.lower()
print("STEP 6    MRA well-formed XML; patch offset 0x6ED57; UNVERIFIED labeled  OK")

print("ALL SELF-TESTS PASSED")
