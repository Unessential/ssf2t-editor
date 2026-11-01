#!/bin/bash
# Capture moving specials (light + heavy) with the per-frame movement pointer
# (obj+0x30) and 16.16 position in the log, plus a write tap on obj+0x30 that
# logs the code setting it. 3 MAME instances. Grid: taps + 8*downs.
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
L=$(cd "$(dirname "$0")/.." && pwd)
run_one() {
  local tag=$1 taps=$2 downs=$3 only=$4 d=$S/mrun_mv_$1
  mkdir -p "$d"
  OUT=$S/${PREFIX:-mv}_$tag.txt STEPSET=moves MOVES_FILE=$L/st_moves.lua MOVE_ONLY="$only" \
  P1_TAPS=$taps P1_DOWNS=$downs RTLO=${RTLO:-0xFF848A} RTHI=${RTHI:-0xFF8491} RT_LATE=1 RTMODE=${RTMODE:-W} \
  mame ssf2t -rompath "${ROMPATH:-${SSF2T_ROM_DIR:-$(cd "$(dirname "$0")/../../.." && pwd)}}" -video none -sound none -nothrottle -skip_gameinfo \
    -seconds_to_run 120 -autoboot_script $L/mame_states.lua \
    -cfg_directory "$d" -nvram_directory "$d" -inipath "$d" >"$d/log" 2>&1
  echo "finished $tag"
}
run_one honda 1 0 "Sumo Headbutt|LP,Sumo Headbutt|HP" &
run_one cammy 4 1 "Spiral Arrow|LK,Spiral Arrow|HK" &
run_one feilong 5 0 "Rekka Ken|LP,Rekka Ken|HP" &
wait
