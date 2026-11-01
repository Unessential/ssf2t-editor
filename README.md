AI assisted. I directed the logic, "steered" the AI when I saw it was going in the wrong direction or it was stuck in a loop. And provided alternative sources of information to allow for verification. But I did almost none of the actual grunt work (coding, tracing memory addresses, etc...). I was staring at it "helicopter parenting" the entire time it was doing autonomous tasks. instead of just leaving it on its own while i sleep. I don't want to "accidentally" hack the Australian government or hugging face ok? 

The setup was tested by the AI in a clean folder with only ssf2t.zip, but I haven't tested it by hand from scratch, because my own working folder holds data I can't distribute and I didn't want to disturb it. LMK if you have problems. Provide the checksum of your ROM, the patch files you generated and what happened, and I'll investigate as soon as I can. 

This is my first ever public release on GitHub! I tried to abide by all the licenses but LMK if I messed something up and I'll change it. I went through the third party notices and licenses by hand.

---

# SSF2T Editor 0.8.0.0

A rebalance editor for **Super Street Fighter II Turbo** (CPS-2, MAME set `ssf2t`,
World 940223). It runs in your browser, reads your own ROM set, and turns your
edits into IPS / BPS patches or patches the ROM zip directly.

No game data is included. Everything is read from a ROM set you supply.

## What you can edit

**Character tab** (per character, new and old versions)
- **Hitboxes**: hurtboxes, attack boxes and pushboxes, drawn over the real sprites,
  frame by frame for every normal, special, super, throw and reaction. Normals are
  grouped as far, close and command normals.
- **Frame data**: how many ticks each animation frame is held (startup / active /
  recovery shown per move).
- **Damage class** of each attack box.
- **Movement** of moving specials (starting speed and slowdown).
- **Projectiles**: fireball speed per strength, and their hitboxes.
- **Walk speed** and **defense** (damage taken).
- **Special move inputs**:
  - any motion, any length (the pretzel works), with **shortcuts**: `2*` accepts
    down-back / down / down-forward;
  - **priority**: which move the game checks first when inputs overlap;
  - **charge moves**: charge time, release shortcut, or replace the charge with any motion;
  - **360 / 720 moves**: replace with any motion;
  - **mash moves** (Hundred Hand Slap, Electricity, Lightning Legs): presses needed and
    the time allowed between presses;
  - **timing**: the window to reach each next direction, and the window to press the
    button (light / medium / heavy).

**Global tab** (the whole game)
- Health, stun, dizzy thresholds, the damage table, game speed (including turning
  frame skip off).
- **Input leniency**: shortcuts on every move, one direction window for every move,
  longer or shorter button windows for every move.

**Theory Fighter tab**: placeholder.

**Tiles tab**: browse the graphics ROMs.

## Setup

You need Python 3 (developed and tested with 3.14) and your MAME `ssf2t` set (`ssf2t.zip`, with `ssf2t.key` inside
as in current MAME sets). MAME is only needed if you want to test your patches (it also needs its `qsound.zip`
next to `ssf2t.zip`).

1. Put the editor folder next to your ROM zip:

   ```
   your_rom_folder/
     ssf2t.zip
     ssf2t-editor/      <- this folder
   ```

   (Or keep them apart and set `SSF2T_ROM_DIR=/path/to/your_rom_folder`.)

2. Install the Python packages:

   ```
   cd ssf2t-editor
   python3 -m pip install -r requirements.txt
   ```

3. Prepare the ROM folder once. This checks your zip against the MAME CRCs, extracts
   the files the editor reads (key, program and graphics ROMs) and builds the two
   program images (`ssf2t_data.bin`, `ssf2t_opcodes.bin`):

   ```
   python3 setup.py
   ```

   Run it on an **unpatched** `ssf2t.zip`: the editor compares every edit against
   these images.

4. Start the editor and open http://127.0.0.1:8765/ :

   ```
   ./restart_editor.sh          # Linux / macOS
   ```

   or, on any system:

   ```
   python3 -m uvicorn app:app --host 127.0.0.1 --port 8765
   ```

   `./restart_editor.sh stop` stops it; `PYTHON=/path/to/python ./restart_editor.sh`
   picks the interpreter.

## Using it

- Pick a character and version on the Character tab. Every card collapses to its
  title; click a title to open it.
- Turn on **Edit mode** in the Hitbox editing card to change anything. Edits stay in
  memory until you export or patch.
- **Patch** card:
  - **Export IPS / BPS**: patches for your ROM files (a zip of per-file patches when
    edits touch several files).
  - **Export MRA**: for MiSTer; not verified.
  - **Patch ROM now**: writes the edits into `ssf2t.zip` and the loose ROM files.
    The first time a file is touched it's backed up as `<file>.orig`.
    **Restore original ROM** puts those back.
  - **Discard all edits**: back to the last patched state.
- Times are in **game ticks**. At Turbo speed the game runs about 1.3 ticks per
  screen frame; with frame skip off (Global tab, game speed 255) it is exactly one.
- Motion notation is numpad, facing right: 2 down, 6 forward, 4 back, 8 up,
  3 down-forward, 1 down-back (236 = quarter circle forward, 623 = dragon punch,
  1632143 = pretzel). A `*` after 2/4/6/8 makes that step a shortcut.

## How it works (and what it doesn't do)

This is simply how the editor works. None of it is a promise of future changes.

- **Hitboxes are shared.** A box is used by every frame (and animation) that points
  to it, so editing it changes all of them. The editor tells you how many frames use
  a box.
- **Move types.** Charge moves and 360 / 720 moves can be changed into motion moves.
  Motion moves can't be changed into charge moves, and mash moves can't be changed
  into motion moves.
- **Button-only moves.** Mash moves can be edited: the number of presses and how
  fast they have to be. They can't be changed to a different button, or to a
  command input. Moves started by a button combination alone (Zangief's Double
  Lariats, T.Hawk's Condor Dive, Claw's wall dives, Blanka's button move) and
  Dhalsim's teleports and Boxer's Turn Punch keep the game's own input.
- **Five short moves keep their length.** Cammy's Spiral Arrow, Cannon Spike and
  Spinning Knuckle and Fei Long's Rekka Ken and Shien Kyaku (new and old) can be
  remapped to any other 3-direction motion, with or without shortcuts, but not
  lengthened or shortened: their checkers are too small for the rewrite plus the
  game's own safety check.
- **Shortcuts take a little more room.** A rewritten motion with shortcuts can be a
  few directions shorter than one without (about 6-7 instead of 12 on short moves).
- **Damage.** Base damage (per class), each attack box's class and each character's
  defense are editable. The random spread, the extra reduction at low health and
  throw damage are the game's own.
- **Supers** belong to the new versions only (Super SF2 has none).
- **Old and new fireballs** share their projectile object, so a projectile edit
  changes both versions.

## Known issues

- Guile's Flash Kick animations in the viewer are wrong captures (they show his
  standing kicks). The real Flash Kick starts at frame record 0x12A3B0.
- Some charge moves are named by their input instead of their move name (Boxer's
  dash punches and kicks, new Chun-Li's two charge kicks).
- MRA export is not verified.

## For developers

- `selftest.py`: patch / export round trip on the real ROM files.
- `tests/ui`: browser-side tests (`npm install && npm test`, needs Node).
- `lua/` and `lua/captures/`: headless MAME capture and verification scripts (tested with
  MAME 0.242). `lua/captures/run_input_suites.sh` re-runs every input check
  (pretzel, SNK / Samurai Shodown motions, charge / 360 / mash, shortcuts and timing)
  on a patched copy of your ROM against the original. The raw capture logs that
  the `build_*.py` scripts read aren't included (about 100 MB); the JSON files they
  produced are.
- `docs/TECHNICAL_NOTES.md`: addresses and findings (damage formula, input checkers,
  timing tables, ...).

## Acknowledgements

- **MAME** (CPS-2 decryption, by Andreas Naive and Nicola Salmoria et al.):
  `cps2_decrypt.py` is a port. See `THIRD_PARTY_NOTICES.md`.
- **Dammit, MZ and Felineki** (mame-rr hitbox scripts) and **pof** (SSF2X training
  lua): the hitbox colour convention and object layout.
- The **FBNeo / Fightcade** Super Turbo training scripts: memory addresses.
- ssf2xj-recomp (andreoka-debug), built on Tommy McLeroy's cps2recomp: memory addresses cross-checked against its notes. No code from either is included.
- **SuperCombo wiki**: system mechanics used to check the findings.

## Legal

Super Street Fighter II Turbo is © Capcom. This project includes no ROM files, graphics or game program; the technical notes quote a few short disassembled instructions and addresses for documentation. Use it only with a ROM set you legally own.
