#!/usr/bin/env python3
"""setup.py -- prepare a ROM folder for the editor (run once).

    python3 setup.py [rom_folder]

rom_folder (default: SSF2T_ROM_DIR, else the folder that contains the editor)
must hold your MAME `ssf2t` set as ssf2t.zip (Super Street Fighter II Turbo,
World 940223, with ssf2t.key inside, as in current MAME sets). This script:

  1. checks the zip's program ROMs and key against the MAME CRCs (the editor
     treats the images it builds as the unmodified game, so build them from an
     unpatched zip);
  2. extracts the files the editor reads loose (key, program and graphics ROMs)
     next to the zip, skipping any that are already there;
  3. builds ssf2t_data.bin (raw program image) and ssf2t_opcodes.bin
     (decrypted) with cps2_decrypt.py, unless they exist (--force rebuilds).

No game data ships with the editor; everything comes from your own ROM set.
"""
import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# MAME ssf2t (World 940223): program ROMs + key
PROGRAM_CRC = {"sfxe.03c": 0x2fa1f396, "sfxe.04a": 0xd0bc29c6, "sfxe.05": 0x65222964,
               "sfxe.06a": 0x8fe9f531, "sfxe.07": 0x8a7d0cb6, "sfxe.08": 0x74c24062,
               "sfx.09": 0x642fae3f, "ssf2t.key": 0x524d608e}
GFX = ["sfx.13m", "sfx.14m", "sfx.15m", "sfx.16m", "sfx.17m", "sfx.18m", "sfx.19m", "sfx.20m",
       "sfx.21m", "sfx.23m", "sfx.25m", "sfx.27m"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom_folder", nargs="?", help="folder with ssf2t.zip")
    ap.add_argument("--force", action="store_true", help="rebuild ssf2t_data.bin / ssf2t_opcodes.bin")
    args = ap.parse_args()
    if args.rom_folder:
        os.environ["SSF2T_ROM_DIR"] = os.path.abspath(args.rom_folder)
    import paths
    rom_dir = paths.ROM_DIR
    zpath = os.path.join(rom_dir, "ssf2t.zip")
    print("ROM folder:", rom_dir)
    if not os.path.exists(zpath):
        print("ssf2t.zip not found there. Put your MAME ssf2t set in that folder, or pass the folder.")
        return 1

    with zipfile.ZipFile(zpath) as z:
        info = {i.filename: i for i in z.infolist()}
        missing = [n for n in list(PROGRAM_CRC) + GFX if n not in info]
        if missing:
            print("ssf2t.zip is missing:", ", ".join(missing))
            print("(this editor needs the World 940223 'ssf2t' set; a set without ssf2t.key inside")
            print(" needs the key file added to the zip or put next to it)")
            if any(n != "ssf2t.key" for n in missing) or not os.path.exists(os.path.join(rom_dir, "ssf2t.key")):
                return 1
        bad = [n for n, crc in PROGRAM_CRC.items() if n in info and info[n].CRC != crc]
        if bad:
            print("WARNING: these files don't match the unmodified MAME set:", ", ".join(bad))
            print("  The editor expects images built from an unpatched ssf2t.zip (it compares edits")
            print("  against them). Restore the original zip (or a patched zip's *.orig backup) first.")
            if not args.force:
                print("  Re-run with --force to continue anyway.")
                return 1
        out = 0
        for n in list(PROGRAM_CRC) + GFX:
            dst = os.path.join(rom_dir, n)
            if n in info and not os.path.exists(dst):
                with open(dst, "wb") as fh:
                    fh.write(z.read(n))
                out += 1
        print("extracted %d file(s)" % out)

    data, opc = paths.DATA_BIN, paths.OPCODES_BIN
    if os.path.exists(data) and os.path.exists(opc) and not args.force:
        print("images already there:", os.path.basename(data), os.path.basename(opc))
    else:
        import cps2_decrypt
        rc = cps2_decrypt.auto_decrypt([rom_dir], "ssf2t", "auto")
        if rc:
            return rc
    for p in (data, opc):
        if not os.path.exists(p) or os.path.getsize(p) != 0x380000:
            print("problem: %s is missing or the wrong size" % p)
            return 1
    print("Done. Start the editor with ./restart_editor.sh and open http://127.0.0.1:8765/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
