"""verify_leniency.py -- MAME check of shortcuts and input timing.

  python verify_leniency.py patch <rom_dir>
      Ryu: Hadouken -> 2*36 (in place), Shakunetsu -> 4*6 (engine), Tatsumaki
      direction window fixed at 4 ticks, Shoryuken button window 40 ticks;
      Guile: Sonic Boom release shortcut on.
Then lua/captures/run_input_suites.sh leniency.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(rom_dir):
    os.environ["SSF2T_DATA"] = os.path.join(rom_dir, "ssf2t_data.bin")
    sys.path.insert(0, HERE)
    import app
    from fastapi.testclient import TestClient
    c = TestClient(app.app)

    def mv(char, name):
        return [m for m in c.get("/api/inputs", params={"char": char}).json()["moves"] if m["name"] == name][0]["sub"]
    steps = [("/api/inputs", {"sub": mv("ryu", "Hadouken"), "motion": "2*36"}),
             ("/api/inputs", {"sub": mv("ryu", "Shakunetsu Hadouken"), "motion": "4*6"}),
             ("/api/inputs/timing", {"sub": mv("ryu", "Tatsumaki"), "dir_min": 4, "dir_max": 4}),
             ("/api/inputs/timing", {"sub": mv("ryu", "Shoryuken"), "light": 40, "medium": 40, "heavy": 40}),
             ("/api/inputs/release", {"sub": mv("guile", "Sonic Boom"), "shortcut": True})]
    for url, body in steps:
        r = c.post(url, json=body).json()
        print(url, body, "->", r.get("motion"), r.get("timing"), r.get("release_shortcut"), r.get("error", ""))
    print("patch_rom:", c.post("/api/patch_rom", json={"confirm": True}).json().get("rom_files"))


if __name__ == "__main__":
    main(sys.argv[2])
