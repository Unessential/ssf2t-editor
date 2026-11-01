"""verify_inputs2.py -- MAME check of charge / 360 / mash / Fei Long super edits.

  python verify_inputs2.py patch <rom_dir>
      Guile: Sonic Boom -> 236, Flash Kick charge 60 -> 10 ticks, Double
      Somersault -> 236236; Zangief: SPD -> 41236; Fei Long: Rekka Shinken ->
      41236, Rekku Kyaku -> 236; Honda: Hundred Hand Slap -> 2 presses.
Then run lua/captures/run_inputs.sh with MOVES_FILE=lua/captures/charge360_test_moves.lua
on the pristine ROM and on <rom_dir>, and compare with verify_inputs.py check.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOTIONS = {("guile", "Sonic Boom"): "236", ("guile", "Double Somersault (super)"): "236236",
           ("zangief", "Spinning Piledriver"): "41236", ("feilong", "Rekka Shinken (super)"): "41236",
           ("feilong", "Rekku Kyaku"): "236"}
CHARGE = {("guile", "Flash Kick"): 10}
MASH = {("honda", "Hundred Hand Slap"): 2}


def main(rom_dir):
    os.environ["SSF2T_DATA"] = os.path.join(rom_dir, "ssf2t_data.bin")
    sys.path.insert(0, HERE)
    import app
    from fastapi.testclient import TestClient
    c = TestClient(app.app)

    def mv(char, name):
        return [m for m in c.get("/api/inputs", params={"char": char}).json()["moves"] if m["name"] == name][0]
    for (ch, n), mot in MOTIONS.items():
        r = c.post("/api/inputs", json={"sub": mv(ch, n)["sub"], "motion": mot}).json()
        print(ch, n, "->", r.get("motion"), r.get("mode"), r.get("error", ""))
    for (ch, n), fr in CHARGE.items():
        r = c.post("/api/inputs/charge", json={"sub": mv(ch, n)["sub"], "frames": fr}).json()
        print(ch, n, "charge ->", r.get("charge"), r.get("error", ""))
    for (ch, n), k in MASH.items():
        r = c.post("/api/inputs/mash", json={"sub": mv(ch, n)["sub"], "strength": "all", "presses": k}).json()
        print(ch, n, "presses ->", [f["count"] for f in r.get("mash", [])], r.get("error", ""))
    r = c.post("/api/patch_rom", json={"confirm": True}).json()
    print("patch_rom:", r.get("rom_files"), r.get("error"))


if __name__ == "__main__":
    main(sys.argv[2])
