"""exporters.py -- turn edits to the flat SSF2T data image into patches.

Pipeline: diff(working vs original flat image) -> per-EPROM byte changes
(via the PROVEN cps2_map) -> IPS / BPS patch files targeting the real ROM
files, plus a MiSTer MRA.

Confidence:
  * IPS  -- VERIFIED. Targets the EPROM files directly via flat[F]=eprom[F^1].
  * BPS  -- VERIFIED (structural): correct CRC32 footer, applies cleanly.
  * MRA  -- UNVERIFIED. The MiSTer <patch> offset is into the ROM as the
            jtcps2 core ASSEMBLES it (own decryption + gfx interleave). We
            could not confirm that transform, so offsets use the raw-EPROM
            concatenation assumption and are labelled UNVERIFIED in the file.
"""
import struct
import zlib
import cps2_map


# ---------------------------------------------------------------- diff / group
def diff_flat(original: bytes, working: bytes):
    """Return [(flat_off, new_byte), ...] where working differs from original."""
    if len(original) != len(working):
        raise ValueError("length mismatch")
    out = []
    for i, (a, b) in enumerate(zip(original, working)):
        if a != b:
            out.append((i, b))
    return out


def group_changes_by_eprom(changes):
    """flat changes -> {eprom_name: [(eprom_off, new_byte), ...]} using cps2_map."""
    groups = {}
    for flat_off, new_byte in changes:
        name, eoff = cps2_map.flat_to_eprom(flat_off)
        groups.setdefault(name, []).append((eoff, new_byte))
    for name in groups:
        groups[name].sort()
    return groups


# ------------------------------------------------------------------------- IPS
def build_ips(eprom_changes):
    """eprom_changes: [(off, byte), ...] for ONE EPROM -> IPS bytes.

    Standard IPS: 'PATCH' + records(3-byte big-endian offset, 2-byte big-endian
    length, data) + 'EOF'. Consecutive offsets are coalesced into one record.
    """
    recs = []
    cur_off = None
    cur = bytearray()
    for off, byte in sorted(eprom_changes):
        if cur_off is not None and off == cur_off + len(cur) and len(cur) < 0xFFFF:
            cur.append(byte)
        else:
            if cur_off is not None:
                recs.append((cur_off, bytes(cur)))
            cur_off = off
            cur = bytearray([byte])
    if cur_off is not None:
        recs.append((cur_off, bytes(cur)))

    out = bytearray(b"PATCH")
    for off, data in recs:
        if off > 0xFFFFFF:
            raise ValueError("IPS cannot address offset > 0xFFFFFF")
        out += struct.pack(">I", off)[1:]          # 3-byte offset
        out += struct.pack(">H", len(data))        # 2-byte length
        out += data
    out += b"EOF"
    return bytes(out)


def apply_ips(original: bytes, ips: bytes) -> bytes:
    """Apply an IPS patch to `original`, returning the patched bytes (verifier)."""
    assert ips[:5] == b"PATCH"
    buf = bytearray(original)
    i = 5
    while True:
        if ips[i:i + 3] == b"EOF":
            break
        off = struct.unpack(">I", b"\x00" + ips[i:i + 3])[0]; i += 3
        length = struct.unpack(">H", ips[i:i + 2])[0]; i += 2
        if length == 0:   # RLE record
            rle = struct.unpack(">H", ips[i:i + 2])[0]; i += 2
            val = ips[i]; i += 1
            buf[off:off + rle] = bytes([val]) * rle
        else:
            buf[off:off + length] = ips[i:i + length]; i += length
    return bytes(buf)


# ------------------------------------------------------------------------- BPS
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            break
        out.append(x)
        n -= 1
    return bytes(out)


def build_bps(source: bytes, target: bytes) -> bytes:
    """Minimal linear BPS (source/target same length). Correct CRC32 footer.

    Encodes a single TargetRead over the whole file -- simple and always valid;
    size is dominated by the (small) changed regions only in smarter encoders,
    but correctness is the point for v0.
    """
    out = bytearray(b"BPS1")
    out += _varint(len(source))
    out += _varint(len(target))
    out += _varint(0)  # metadata length
    # One TargetRead command covering the entire target.
    # command = (length-1)<<2 | 1  (1 = TargetRead)
    out += _varint(((len(target) - 1) << 2) | 1)
    out += target
    out += struct.pack("<I", zlib.crc32(source) & 0xFFFFFFFF)
    out += struct.pack("<I", zlib.crc32(target) & 0xFFFFFFFF)
    out += struct.pack("<I", zlib.crc32(bytes(out)) & 0xFFFFFFFF)
    return bytes(out)


def apply_bps(source: bytes, bps: bytes) -> bytes:
    """Apply a linear BPS (verifier for the subset build_bps emits)."""
    assert bps[:4] == b"BPS1"
    i = 4

    def rd():
        nonlocal i
        res = 0; shift = 0
        while True:
            b = bps[i]; i += 1
            res += (b & 0x7F) << shift
            if b & 0x80:
                break
            shift += 7
            res += 1 << shift
        return res

    src_len = rd(); tgt_len = rd(); meta = rd(); i += meta
    out = bytearray()
    end = len(bps) - 12
    while i < end:
        cmd = rd()
        action = cmd & 3
        length = (cmd >> 2) + 1
        if action == 1:        # TargetRead
            out += bps[i:i + length]; i += length
        elif action == 0:      # SourceRead
            out += source[len(out):len(out) + length]
        else:
            raise NotImplementedError("relative-mode BPS not emitted by build_bps")
    assert len(out) == tgt_len
    return bytes(out)


# ------------------------------------------------------------------------- MRA
def raw_concat_offset(flat_off: int) -> int:
    """DOCUMENTED ASSUMPTION for the MRA patch offset: the raw-EPROM
    concatenation offset = slot_base + (flat_off ^ 1). This is NOT confirmed to
    equal the jtcps2 assembled-rom offset; MRA export is labelled UNVERIFIED."""
    name, eoff = cps2_map.flat_to_eprom(flat_off)
    base = cps2_map.LOAD_ORDER.index(name) * cps2_map.EPROM_SIZE
    return base + eoff


def build_mra(changes, src_md5="none") -> str:
    """Emit a syntactically valid ssf2t MRA with <patch> elements.

    changes: [(flat_off, new_byte), ...]. Patches are coalesced into runs.
    The <rom index="0"> here lists the stock ssf2t program parts and the
    patch(es); it is a demonstration skeleton, not a full production manifest.
    """
    # coalesce into runs by assembled offset
    pts = sorted((raw_concat_offset(f), b) for f, b in changes)
    runs = []
    for off, byte in pts:
        if runs and off == runs[-1][0] + len(runs[-1][1]):
            runs[-1][1].append(byte)
        else:
            runs.append([off, bytearray([byte])])

    patch_xml = []
    for off, data in runs:
        hexs = " ".join("%02X" % b for b in data)
        patch_xml.append('    <patch offset="0x%X">%s</patch>' % (off, hexs))
    patches = "\n".join(patch_xml) if patch_xml else "    <!-- no changes -->"

    # NOTE: no literal double-hyphen inside XML comments (illegal in XML).
    return """<misterromdescription>
  <name>Super Street Fighter II Turbo (hitbox edit)</name>
  <setname>ssf2t</setname>
  <rbf>jtcps2</rbf>
  <mameversion>0245</mameversion>
  <year>1994</year>
  <manufacturer>Capcom</manufacturer>
  <players>2</players>
  <!-- ============================================================= -->
  <!-- HITBOX EDITOR PATCH. CONFIDENCE: UNVERIFIED.                   -->
  <!-- The patch offset values below use the RAW-EPROM concatenation  -->
  <!-- assumption: slot_base + (flat XOR 1). The MiSTer jtcps2 core    -->
  <!-- assembles and decrypts the ROM itself and interleaves gfx, so  -->
  <!-- the true assembled-rom offset may differ. TEST ON HARDWARE.    -->
  <!-- The IPS / BPS exports target the EPROM files directly and ARE   -->
  <!-- verified; prefer them until this MRA is confirmed.             -->
  <!-- ============================================================= -->
  <rom index="0" zip="ssf2t.zip" md5="%s" type="merged">
    <part name="sfxe.03c"/>
    <part name="sfxe.04a"/>
    <part name="sfxe.05"/>
    <part name="sfxe.06a"/>
    <part name="sfxe.07"/>
    <part name="sfxe.08"/>
%s
  </rom>
</misterromdescription>
""" % (src_md5, patches)
