#!/bin/bash
# Capture every special/super of every new-version character with a write tap
# on P1's velocity/slowdown words (obj+0x3C..0x43), so build_move_physics.py can
# find the code that sets each move's movement. 3 MAME instances at a time.
# Usage: run_allmoves.sh [char ...]   (default: all 16)
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
L=$(cd "$(dirname "$0")/.." && pwd)
# select-grid slot (taps + 8*downs) for each character, from the OLD=1 grid survey
declare -A SLOT=([ryu]=0 [honda]=1 [blanka]=2 [guile]=3 [thawk]=4 [feilong]=5 [boxer]=6 [sagat]=7
                 [ken]=8 [chunli]=9 [zangief]=10 [dhalsim]=11 [cammy]=12 [deejay]=13 [claw]=14 [dictator]=15)
run_one() {
  local c=$1 g=${SLOT[$1]} d=$S/mrun_am_$1
  mkdir -p "$d"
  OUT=$S/${OUTPFX:-am}_$c.txt STEPSET=moves MOVES_FILE=$L/st_moves.lua MOVE_ONLY="${MOVE_ONLY:-}" \
  P1_TAPS=$((g % 8)) P1_DOWNS=$((g / 8)) RTLO=0xFF8488 RTHI=0xFF8497 RT_LATE=1 RTMODE=${RTMODE:-W} RT_REFRESH=1 \
  mame ssf2t -rompath "${ROMPATH:-${SSF2T_ROM_DIR:-$(cd "$(dirname "$0")/../../.." && pwd)}}" -video none -sound none -nothrottle -skip_gameinfo \
    -seconds_to_run 480 -autoboot_script $L/mame_states.lua \
    -cfg_directory "$d" -nvram_directory "$d" -inipath "$d" >"$d/log" 2>&1
  if grep -q '^DONE' "$S/${OUTPFX:-am}_$c.txt"; then echo "ok $c"; else echo "INCOMPLETE $c"; fi
}
export -f run_one; export S L
for k in "${!SLOT[@]}"; do export "SLOT_$k=${SLOT[$k]}"; done
CHARS=("$@"); [ ${#CHARS[@]} -eq 0 ] && CHARS=(ryu honda blanka guile ken chunli zangief dhalsim dictator sagat boxer claw cammy thawk feilong deejay)
printf '%s\n' "${CHARS[@]}" | xargs -P 3 -I{} bash -c 'declare -A SLOT; for v in $(compgen -v SLOT_); do SLOT[${v#SLOT_}]=${!v}; done; run_one {}'
