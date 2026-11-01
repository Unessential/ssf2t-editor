#!/bin/bash
# Dump CPS-2 object RAM while new Ken's Kama Barai Geri is on its active frame
# (frame record 0x132228, sprite 0x1354F4), for checking the sprite decoder
# against what the hardware actually draws. 1 MAME instance.
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
L=$(cd "$(dirname "$0")/.." && pwd)
D=$S/objdump; mkdir -p "$D" "$S/mrun_od"
OUT=$S/objdump.txt STEPSET=moves MOVES_FILE=$L/st_moves.lua MOVE_ONLY="Kama Barai Geri|MK" \
OBJDUMP_ANIM=${OBJDUMP_ANIM:-0x132228} DUMPDIR=$D P1_TAPS=0 P1_DOWNS=1 \
mame ssf2t -rompath "${SSF2T_ROM_DIR:-$(cd "$(dirname "$0")/../../.." && pwd)}" -video none -sound none -nothrottle -skip_gameinfo \
  -seconds_to_run 60 -autoboot_script $L/mame_states.lua \
  -cfg_directory "$S/mrun_od" -nvram_directory "$S/mrun_od" -inipath "$S/mrun_od" >"$S/mrun_od/log" 2>&1
grep OBJDUMP "$S/objdump.txt"; ls -la "$D"
