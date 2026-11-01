#!/bin/bash
# Capture new Ken's crazy kicks (and the held Inazuma version) in headless MAME,
# plus the same inputs on old Ken to confirm he lacks them. 2 MAME instances.
# Ken is grid slot 0 on the second row (P1_TAPS=0, P1_DOWNS=1).
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
L=$(cd "$(dirname "$0")/.." && pwd)
ONLY="Kama Barai Geri|LK,Kama Barai Geri|MK,Kama Barai Geri|HK,Nata Otoshi Geri|LK,Nata Otoshi Geri|MK,Nata Otoshi Geri|HK,Oosoto Mawashi Geri|LK,Oosoto Mawashi Geri|MK,Oosoto Mawashi Geri|HK,Inazuma Kakato Wari|MK"
run_one() {
  local tag=$1 oldflag=$2 d=$S/mrun_ck_$1
  mkdir -p "$d"
  OUT=$S/ck_$tag.txt STEPSET=moves MOVES_FILE=$L/st_moves.lua MOVE_ONLY="$ONLY" OLD=$oldflag \
  P1_TAPS=0 P1_DOWNS=1 \
  mame ssf2t -rompath "${SSF2T_ROM_DIR:-$(cd "$(dirname "$0")/../../.." && pwd)}" -video none -sound none -nothrottle -skip_gameinfo \
    -seconds_to_run 200 -autoboot_script $L/mame_states.lua \
    -cfg_directory "$d" -nvram_directory "$d" -inipath "$d" >"$d/log" 2>&1
  echo "finished $tag"
}
run_one new 0 &
run_one old 1 &
wait
