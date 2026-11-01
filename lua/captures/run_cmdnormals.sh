#!/bin/bash
# Capture command / diagonal-jump / close normals (STEPSET=cmdnormals) per character,
# new or old version (OLD=1). Output: <pfx>_c_<char>.txt.
# Usage: OLD=0|1 PFX=nw|od run_cmdnormals.sh [char ...]   (3 MAME at a time)
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
L=$(cd "$(dirname "$0")/.." && pwd)
export S L OLDV=${OLD:-0} PFX=${PFX:-nw}
job() {
  local c=$1 g
  case $c in ryu) g=0;; honda) g=1;; blanka) g=2;; guile) g=3;; thawk) g=4;; feilong) g=5;; boxer) g=6;; sagat) g=7;;
             ken) g=8;; chunli) g=9;; zangief) g=10;; dhalsim) g=11;; cammy) g=12;; deejay) g=13;; claw) g=14;; dictator) g=15;; esac
  local d=$S/mrun_${PFX}_c_$c
  mkdir -p "$d"
  OUT=$S/${PFX}_c_$c.txt STEPSET=cmdnormals OLD=$OLDV P1_TAPS=$((g % 8)) P1_DOWNS=$((g / 8)) \
  mame ssf2t -rompath "${SSF2T_ROM_DIR:-$(cd "$(dirname "$0")/../../.." && pwd)}" -video none -sound none -nothrottle -skip_gameinfo \
    -seconds_to_run 320 -autoboot_script $L/mame_states.lua \
    -cfg_directory "$d" -nvram_directory "$d" -inipath "$d" >"$d/log" 2>&1
  grep -q '^DONE' "$S/${PFX}_c_$c.txt" && echo "ok $c" || echo "INCOMPLETE $c"
}
export -f job
CHARS=("$@"); [ ${#CHARS[@]} -eq 0 ] && CHARS=(ryu honda blanka guile ken chunli zangief dhalsim dictator sagat boxer claw cammy thawk feilong deejay)
printf '%s\n' "${CHARS[@]}" | xargs -P 3 -I{} bash -c 'job {} 2>/dev/null'
