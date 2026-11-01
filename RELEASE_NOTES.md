# 0.8.0.0

First public release.

## Editing
- Hitboxes for every normal (far, close and command normals, neutral and diagonal
  jumps), special, super, throw and reaction, new and old versions of all 16
  characters.
- Frame durations, damage class per attack box, the global damage table, defense,
  walk speed, health, stun, dizzy, game speed (frame skip on/off).
- Movement of moving specials, projectile speed and hitboxes.
- Special move inputs: any motion and length (motion moves; charge and 360 / 720
  moves can be replaced by a motion), priority order, charge time, mash presses
  and windows, shortcuts (`2*` style, per step, per move or for every move),
  direction and button windows per move or for every move.

## Output
- IPS / BPS export (verified), MRA export (unverified), patch the ROM zip in place
  with automatic `.orig` backups.

## Setup
- `setup.py` builds everything the editor needs from your own `ssf2t.zip`.

## Testing
- Every input feature was checked in headless MAME against the original ROM:
  remapped motions, the pretzel, SNK and Samurai Shodown style motions on every
  move, charge time, charge-to-motion, 360-to-motion, mash presses, Fei Long's
  super, shortcuts, and direction / button windows.

See README.md for how things work and the known issues.
