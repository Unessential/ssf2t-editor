#!/bin/bash
# Like run_inputs.sh, but under the MAME debugger (no UI) and with an
# instruction trace of the steps whose label starts with TRACE_LABEL.
# Usage: TRACE_LABEL='mv|new:Rekku' run_trace.sh <char> <slot> <rom_dir> <outtag>
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
L=$(cd "$(dirname "$0")/.." && pwd)
c=$1 g=$2 rp=$3 tag=$4
d=$S/mrun_${tag}_$c
mkdir -p "$d"
echo "go" > "$d/dbg.txt"
OUT=$S/${tag}_$c.txt STEPSET=moves MOVES_FILE=${MOVES_FILE:-$L/captures/inputs_test_moves.lua} MOVE_ONLY="" \
TRACE_FILE=$S/${tag}_$c.trace P1_TAPS=$((g % 8)) P1_DOWNS=$((g / 8)) \
mame ssf2t -rompath "$rp" -video none -sound none -nothrottle -skip_gameinfo -debug -debugger none \
  -debugscript "$d/dbg.txt" -seconds_to_run ${SECS:-200} -autoboot_script $L/mame_states.lua \
  -cfg_directory "$d" -nvram_directory "$d" -inipath "$d" >"$d/log" 2>&1
if grep -q '^DONE' "$S/${tag}_$c.txt"; then echo "ok $tag $c"; else echo "INCOMPLETE $tag $c"; fi
