#!/bin/bash
# Capture projectile slot data for every projectile special (max 3 MAME at once).
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
L=$(cd "$(dirname "$0")/.." && pwd)
one() {
  IFS=';' read -r name cid only <<<"$1"
  d=$S/mrun_pj_$name; mkdir -p "$d"
  OUT=$S/proj_$name.txt STEPSET=moves MOVES_FILE=$L/st_moves.lua MOVE_ONLY="$only" \
  P1_TAPS=$((cid % 8)) P1_DOWNS=$((cid / 8)) \
  mame ssf2t -rompath "${SSF2T_ROM_DIR:-$(cd "$(dirname "$0")/../../.." && pwd)}" -video none -sound none -nothrottle -skip_gameinfo \
    -seconds_to_run 220 -autoboot_script $L/mame_states.lua \
    -cfg_directory "$d" -nvram_directory "$d" -inipath "$d" >"$d/log" 2>&1
  echo "done $name"
}
export -f one; export S L
P="Hadouken|LP,Hadouken|MP,Hadouken|HP"
printf '%s\n' \
 "ken;8;$P" \
 "chunli;9;Kikoken|LP,Kikoken|MP,Kikoken|HP" \
 "dhalsim;11;Yoga Fire|LP,Yoga Fire|MP,Yoga Fire|HP" \
 "sagat;7;Tiger Shot|LP,Tiger Shot|MP,Tiger Shot|HP,Ground Tiger Shot|LK,Ground Tiger Shot|MK,Ground Tiger Shot|HK" \
 "deejay;13;Air Slasher|LP,Air Slasher|MP,Air Slasher|HP" \
 | xargs -P 3 -d '\n' -I{} bash -c 'one "$1"' _ {}
