# SSF2T technical notes

Addresses and findings behind the editor, in the order they were found (later sections
supersede earlier ones where they disagree).

## Rebalance inventory — static-editable vs runtime-locked

Program: `ssf2t_opcodes.bin` in project `ghd/ST.gpr`.
Data values read from the `data::` overlay (= `ssf2t_data.bin`); code from the `ram`/opcode image.
Tags: **[PROVEN]** = established from 68k code + validated byte decode. **[INFERRED]** = consistent hypothesis.
**[DISPROVEN]** = a prior hypothesis checked against real bytes and found false.

---

## How characters are set up (the hub)

`char_setup_install @ ram:0x5078` (labelled, commented, saved) runs at match start
(`caller FUN_00078286`). It is keyed by char id at `obj+0x391` with the **+0x11 old/Super-version
rule** (version flags at obj+0x3BD / 0x38E / 0x3B6; 0x10 / 0x23 for special variants).
It installs exactly **three** char-indexed tables:

| obj field | source table | stride | meaning |
|-----------|--------------|--------|---------|
| obj+0x34 | `player_hitbox_ptr_table` @ `data::0x10026C` | 4 (BE32 ptr) | per-char hitbox/hurt/attack/push box block |
| obj+0x6C / 0x6E | `char_attr_table_6c` @ `data::0x7F7BA` | 4 (2×BE16) | collision/pushbox half-width (weight) + const 0x35 |
| obj+0x38 | `char_scale_table_38` = (id<<5)+`0x24E1F4` | 0x20 | per-char scale/coord ramp (NOT balance) |

Health, super meter, stun, and movement speeds are **not** touched by this routine or its two
siblings (`0x503C` makes a sub-object for special chars; `0x5256` is the undisassembled anim
dispatcher). They are initialised elsewhere — see the gaps section.

---

## Coverage table

### A. EDITABLE NOW (static table located + byte-decoded)

| Parameter | Static addr | stride / index | obj field / move offset | decoded sample | proven? |
|-----------|-------------|----------------|--------------------------|----------------|---------|
| Per-char collision / **pushbox width** (≈ "weight" for throws/spacing) | `data::0x7F7BA` word0 | 4 B, charid×4 (+0x11 old) | obj+0x6C | Ryu 0x1D(29), Chun 0x19(25), **Zangief 0x2D(45)**, Sagat 0x20, Hawk/Dhalsim 0x23 | **PROVEN** |
| Per-char collision height (shared) | `data::0x7F7BC` word1 | 4 B | obj+0x6E | const **0x0035** all chars | **PROVEN** |
| **Hurtboxes** (vuln0/1/2 head/body/legs) per move | per-char block via `data::0x10026C`[id] | 4-B boxes, id×4 | frame+0x08/09/0A → pool | Ryu block 0x198832; vuln pools at block+0x0A/0xEE/0x16E | **PROVEN** |
| **Attack hitbox geometry** per move | attack pool = block+0x1FA (hdr word3) | **16 B**, atk id×16 | frame+0x0D → `read_attack_box`@0xBF588 | Ryu pool `data::0x198A2C`: id1{-33,85,19,8}, id6{-44,88,36,20} | **PROVEN** |
| **Pushbox** per move | push pool = block+0x5BA (hdr word4) | 4 B | hdr+0x08 channel | Ryu pool `data::0x198DEC`: {0,40,16,39},{0,57,16,33} | **PROVEN** |
| Attack hit-effect / spark+sound class per move | attack pool entry +0x06 | within 16-B entry | — | Ryu cycles 0x28–0x2B; +0x05 const 0x01 | **INFERRED** |

All of the above are already table-driven for the **whole roster** (new + old versions) through the
0x10026C pointer table — the existing hitbox editor (`app.py`) covers them.

### B. NEEDS MORE RE (located region, value not yet pinned, or in encrypted code)

| Parameter | Where it is | why not editable yet |
|-----------|-------------|----------------------|
| **Per-move DAMAGE** | applied by the hit-resolution path *after* the box-overlap cluster `0xBEAC8→0xBEC40→0xBECD2` (callers `0x7BF0A/0x7C000/0x7C05A`) | The damage *value* is NOT in the attack-box record (see DISPROVEN below). The table that supplies it is consumed in the hit-reaction code, much of which is in the undisassembled/encrypted region. Needs the hit-reaction routine traced to its damage lookup. |
| **Per-move STUN / dizzy** | same hit-reaction path | same wall as damage; stun is applied together with damage on a confirmed hit. |
| **Hitstun / blockstun / move timing** (startup/active/recovery) | frame records (`+0x00 duration`, stride 0x18) in each anim list | Frame *durations* ARE readable per anim (e.g. Ryu anim list @0x1121A2, documented in ANIM_NOTES), so active/recovery frame counts are editable PER ANIM. But reaching a given move's anim list is the per-char anim-dispatch problem (runtime-computed base) — only the idle+captured lists are mapped. Startup is partly the duration sum; hitstun on the *receiver* is set by the hit-reaction code (same wall). |
| **Projectile properties** | fireball logic in 0x06E000–0x06F4E4 (proven NOT player data by the New Legacy diff) | region identified as system/fireball logic; speed/damage constants there not yet decoded. |

### C. RUNTIME-LOCKED / COMPUTED (no clean static table)

| Parameter | status |
|-----------|--------|
| Per-character **max VITALITY / health** | Not a flat per-char byte table in the data view (no 16/17-entry run of ~144 values; `90 90 90 90` absent). Not set in `char_setup_install` or siblings. The health field is written by round-start code not yet located; may be a computed/const-per-char value in encrypted code. **GAP** — see "where I looked". |
| **Super meter gain + super cost** | No static per-char meter table located this pass. Meter logic is event-driven (gain on hit/whiff, spend on super) in the undisassembled region. **GAP**. |
| Walk / dash / **jump speeds + gravity** | No per-char speed table found adjacent to the known char tables (region around 0x7F7BA is zeros/ramps, not velocities). Movement is integrated per-frame in the player update code (encrypted region). **GAP**. |
| **Throw range / damage** | Throw range relates to the pushbox width (obj+0x6C, editable) + a throw-reach constant; throw damage shares the hit-reaction damage path. Range partly editable via 0x7F7BA; damage locked with the rest. |
| Per-char **anim-list base** (to reach each move's frames) | runtime-computed via per-char state handler `jmp (A4)` (tables 0x100088 / 0x100110 point at graphics, not anim lists). Documented dead-end for static resolution; live capture of obj+0x1A is the working path. |

---

## DISPROVEN this pass (don't chase these)

- **"The 12 trailing bytes of the 16-byte attack-box record hold damage/stun/flags."**
  Read the real data-view bytes of Ryu's attack pool (`data::0x198A2C`, 15 entries). The trailing
  bytes are: +0x04 varies (0A/05/08/00/01), +0x05 constant 0x01, +0x06 cycles 0x28–0x2B
  (hit-spark + sound effect class), remainder mostly 0x00 with an occasional 0x0C/0x13 flag.
  The supercombo damage numbers (4=0x04, 22=0x16, 26=0x1A, 28=0x1C) do **not** appear at any fixed
  offset. So damage is applied elsewhere, not stored in the box record. Labelled on
  `data::0x198A2C` in the project.

---

## Where I looked for the gaps (so the next pass doesn't repeat it)

- **Health table**: searched the data overlay for `90 90 90 90` (no hit); scanned the regions around
  the three proven char tables (0x7F700–0x7F8E0 is zeros/ramps, not health); checked `char_setup_install`
  and its two siblings (`0x503C`, `0x5256`) — none write a health field. Not yet traced: the round-start
  routine that writes the live health field (P1 base ≈ 0xFF844E per the FBNeo lua) — that write site is
  the next place to find the health source.
- **Speeds**: looked immediately before/after `char_attr_table_6c`; no velocity-magnitude table.
- **Damage**: traced the box-reader cluster callers (`0xBEAC8` → `0xBEC40` → `0xBECD2`, up to
  `0x7BF0A`/`0x7C000`/`0x7C05A`). These are box-overlap *detection*; the damage lookup is one hop
  past them in the hit-reaction code, which is in the undisassembled region.

---

## Highest-value next step for the rebalance utility

**Locate the per-move DAMAGE/STUN table by tracing the hit-reaction routine.** Hitbox geometry,
pushbox/weight, and frame timing are already table-driven and editable for the whole roster — the one
rebalance lever still missing is damage/stun, and it's the lever players care about most. The reliable
way in, given the encrypted-code wall, is a **live FBNeo trace**: break/log when a confirmed hit
decrements P2 health, capture the address the damage value is read from, then read that table in the
data overlay (same dual-image method already used for every other table here). That single table would
move DAMAGE (and almost certainly STUN, applied alongside) from "runtime-locked" to "editable now".

Second-highest: the health-field write site at round start (find where ~0xFF844E health is initialised)
to confirm whether max vitality is a static per-char table or a computed constant.

---

## Ghidra labels committed + saved this pass (namespace SSF2T)

- `char_attr_table_6c` @ `data::0x7F7BA` + PLATE decode (16 chars) + `[DUAL-IMAGE]` note on ram copy.
- `ryu_attack_pool` @ `data::0x198A2C` + PLATE (geometry proven, damage disproven).
- `char_scale_table_38` @ `data::0x24E1F4` + PLATE (scale ramp, low rebalance value).
- PLATE on `char_setup_install` @ `ram:0x5078` documenting the three per-char tables + the health/
  meter/speed negative result.
- Program saved.

---

## Special-move inputs (editable, inputs.py, MAME-verified 2026-11-01)

- Player input: 0x001C12 reads 0x804000/0x804010 into $FF8086/$FF808A; 0x002CD4 copies to
  obj+0x3E0 (P1 obj 0xFF844E); 0x002DDC builds the facing-relative word at obj+0x3A6
  (&0xF: 1 back, 2 forward, 4 down, 8 up). Buttons: punches 0x70, kicks 0x700.
- 0x07B08E picks the character's checker from the pointer table 0x7B0B4 (0-15 new, 16 Akuma,
  17-32 old; old Ken = old Ryu's checker 0x983EE). The checker bsr's one routine per move;
  call order = priority, first match wins (flag obj+0x16D).
- Motion routine = state machine on a byte $ST (timer $ST+1): handler k compares the stick to
  an immediate (`cmpi.w #dir,d0`, encrypted code), +2 and random 8-15 frame reload on match,
  clear on timeout; the last direction opens the button window (12 minus 0/2/4 by strength).
- Editor: same length = immediates in place; other lengths = a 56-byte direction-list engine
  written over the move's own direction handlers (states 0 / 0x80+2i, `ble.w` in the dispatch),
  falling into the game's button code. Priority = the checker's bsr displacements.
- 53 motion routines editable (49 distinct); charge, 360, mash, Fei Long's super not yet.
- Verified (verify_inputs.py + lua/captures/inputs_test_moves.lua): Ryu Hadouken -> pretzel
  1632143 (engine) and moved to first priority; Cammy Spiral Arrow -> 41236 (engine), Cannon
  Spike -> 421 (in place); untouched SRK/Tatsu/Shakunetsu/Spinning Knuckle still work.
- ST quirk found: the Shakunetsu's startup animation is chosen from the Hadouken's strength
  byte (0x0806A4 reads obj+0x97), so it follows the last Hadouken's strength. Cosmetic.
- The pretzel contains a whole DP (6, 2, 3), so a pretzel Hadouken must sit above Shoryuken.

### Charge / 360 / mash / other inputs (inputs.py, MAME-verified 2026-11-01)

- Every non-motion checker is rewritable by the same engine through its "anchor": the last
  handler that checks the stick before the button code (charge release, 360's last direction,
  Hooligan/Rekku's up-forward). Everything before it is replaced; the engine falls into the
  game's button code. Timer byte comes from the anchor's `subq.b #1`; moves without a random
  reload get a fixed 12-tick window per direction.
- Charge time: raw byte per move (0x981D6.. new, 0x983B2.. old), loaded with
  `movea.l #tbl,a0 ; move.b k(a0),$x(a6)`; counted in game ticks (60 = ~48 frames at Turbo).
  Sonic Boom: 48 frames needed on the stock ROM; set to 10 ticks, 12 frames works, 8 doesn't.
- Mash: per strength `move.w #button,d0 ; move.b #window,d1 ; bsr count`, then
  `cmpi.b #presses,$n(a6)` (Honda 4 presses, Blanka/Chun 5; windows 15/12/9 ticks). Encrypted
  immediates. Each press restarts the window; the count clears when it runs out.
- Guile's super has an `rts` between its jmp and the table: kept; the rewritten dispatch hops it.
- Fei Long's super: handlers out of order and one shared twice; region = lowest..last handler.
- Engine fix: when the button code checks the button before advancing (Cammy-style tails), the
  last-direction state can persist (button pressed while the move can't start yet) and the
  dispatch ran a blanked table entry -> address error -> game reset. Those moves get a 4-byte
  re-check entry (moveq #2(n-1),d0 ; bra into the engine's compare) and the engine routes
  state L to the button code. Cammy's 3 motion specials and Fei Long's Rekka Ken / Shien
  Kyaku have no room for it: same-length (in place) edits only.
- Original quirks seen: the Rekku Kyaku (and other Cammy-style tails) compare the strength
  window against a stale timer when the button lands on the same frame as the last direction;
  the stored "Flash Kick (Strong Kick)" capture in attack_anims.json is actually Guile's stand HK
  (the real Flash Kick HK animation starts at 0x12A3B0).
- Not editable: button-only moves (lariats, Condor Dive, Claw's dives, Blanka's 082152),
  Dhalsim's teleports, Boxer's Turn Punch.
- Checks: lua/captures/run_input_suites.sh (basic, snk, ss, charge) and charge_probe_moves.lua.

### Shortcuts and input timing (inputs.py, MAME-verified 2026-11-01)

- Shortcut = a step checked with its own bit as the mask (`andi #bit ; cmpi #bit`): 2* takes
  1/2/3, 6* takes 3/6/9, 4* takes 1/4/7, 8* takes 7/8/9. Motion notation: `2*36`.
  In place: the step's `andi.w #$f` immediate becomes the bit. Engine: a (mask, value) word per
  direction (`move.w LIST(pc,d0.w),d1 ; ror ; and.b ; ror ; cmp.b`), used only when a motion
  has shortcuts (exact motions keep the byte list, so maximum lengths are unchanged).
- Charge releases that are `andi #$f ; cmpi #dir` (26 moves) can take a shortcut in place.
  Stock Sonic Boom release is exact forward (MAME: B-charge then DF gives nothing; with the
  shortcut it gives a Sonic Boom). Charge *holds* are already any-of masks.
- Direction window: `jsr $2e96 ; andi #$1f ; move.b TABLE(pc,d0.w),$t(a6)` -> 32 bytes per move
  (stock 8-15, 360s +8). Edits map the stock spread linearly onto min..max. Charge moves keep
  their release table inside the replaceable bytes (editable while the stock checker is in).
  Rewritten moves without a table: the engine's fixed window (default 12), kept across edits.
- Button window: last direction sets the button timer (`move.b #12,$b(a6)`, in the kept tail);
  a press counts while timer >= threshold (`move.w THR(pc,d1.w),d0 ; cmp.b $b(a6),d0`: 0/2/4),
  so 12/10/8. 69 moves have per-strength thresholds, 22 one value (supers, some charges).
- Global (Global tab, /api/inputs/global): shortcuts on/off everywhere, one direction window
  for every move, shift every button window, reset all timing.
- Checks: run_input_suites.sh leniency (Ryu: 2*36 in place, 4*6 engine, 4-tick direction
  window, 40-tick button window; Guile: Sonic Boom release shortcut).
