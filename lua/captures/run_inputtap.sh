#!/bin/bash
# Read-tap a RAM range while P1 performs moves, to find the code that reads it
# (used to locate the special-move input checker).
# Usage: run_inputtap.sh <char> <slot> <RTLO> <RTHI> [MOVE_ONLY] [outtag]
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
L=$(cd "$(dirname "$0")/.." && pwd)
c=$1 g=$2 lo=$3 hi=$4 only=${5:-} tag=${6:-it}
d=$S/mrun_${tag}_$c
mkdir -p "$d"
OUT=$S/${tag}_$c.txt STEPSET=moves MOVES_FILE=$L/st_moves.lua MOVE_ONLY="$only" \
P1_TAPS=$((g % 8)) P1_DOWNS=$((g / 8)) RTLO=$lo RTHI=$hi RT_LATE=1 RTMODE=${RTMODE:-R} RT_REFRESH=1 \
mame ssf2t -rompath "${ROMPATH:-${SSF2T_ROM_DIR:-$(cd "$(dirname "$0")/../../.." && pwd)}}" -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run ${SECS:-200} -autoboot_script $L/mame_states.lua \
  -cfg_directory "$d" -nvram_directory "$d" -inipath "$d" >"$d/log" 2>&1
if grep -q '^DONE' "$S/${tag}_$c.txt"; then echo "ok $c"; else echo "INCOMPLETE $c"; fi
