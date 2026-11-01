#!/bin/bash
# Every input-editing MAME check: builds a fresh patched ROM copy per suite,
# runs the pristine and patched captures (3 MAME at a time) and prints the
# verify_inputs.py verdicts. Usage: run_input_suites.sh [suite ...]
#   suites: basic (Ryu/Cammy), snk (Ryu/Sagat), ss (Ryu), charge (Guile/Zangief/Fei Long/Honda),
#           leniency (Ryu/Guile)
S=${SSF2T_WORK:-$PWD/mame_work}; mkdir -p "$S"
E=$(cd "$(dirname "$0")/../.." && pwd)
R=${SSF2T_ROM_DIR:-$(dirname "$E")}
C=$E/lua/captures
PY=${PYTHON:-python3}
fresh() {   # fresh ROM copy in $S/rom_$1
  rm -rf "$S/rom_$1"; mkdir -p "$S/rom_$1"
  (cd "$R" && cp -p ssf2t.zip qsound*.zip sfx* ssf2t.key ssf2t_data.bin "$S/rom_$1/" 2>/dev/null)   # qsound.zip: MAME's QSound ROM
}
declare -A SLOT=([ryu]=0 [honda]=1 [guile]=3 [feilong]=5 [sagat]=7 [zangief]=10 [cammy]=12)
declare -A CID=([ryu]=0 [honda]=1 [guile]=3 [feilong]=14 [sagat]=9 [zangief]=6 [cammy]=12)
suite() {   # suite <name> <moves file> <patch cmd> <chars...>
  local name=$1 moves=$2 patch=$3; shift 3
  fresh "$name"
  (cd $E && eval "$patch \"$S/rom_$name\"") | tail -3
  local jobs=()
  for c in "$@"; do jobs+=("$c $R p_$name" "$c $S/rom_$name q_$name"); done
  printf '%s\n' "${jobs[@]}" | MOVES_FILE=$moves SECS=${SECS:-260} xargs -P 3 -L 1 bash -c \
    'g=$(case $0 in ryu) echo 0;; honda) echo 1;; guile) echo 3;; feilong) echo 5;; sagat) echo 7;; zangief) echo 10;; cammy) echo 12;; esac); '"$C"'/run_inputs.sh $0 $g $1 $2 2>&1 | grep -v Segm'
  for c in "$@"; do
    echo "--- $name / $c"
    if [ "$name" = charge ] || [ "$name" = leniency ]; then $PY $E/verify_inputs.py check $S/p_${name}_$c.txt $S/q_${name}_$c.txt ${CID[$c]}
    else $PY $E/verify_inputs.py check $S/p_${name}_$c.txt $S/q_${name}_$c.txt; fi
    echo "resets: $(grep -c 'anim=0x000000' $S/q_${name}_$c.txt)"
  done
}
SUITES=("$@"); [ ${#SUITES[@]} -eq 0 ] && SUITES=(basic snk ss charge)
for s in "${SUITES[@]}"; do
  case $s in
    basic)  suite basic $C/inputs_test_moves.lua "$PY verify_inputs.py patch" ryu cammy ;;
    snk)    suite snk $C/snkmode_test_moves.lua "$PY verify_snkmode.py patch" ryu sagat ;;
    ss)     suite ss $C/ssmode_test_moves.lua "$PY verify_snkmode.py patch ss" ryu ;;
    charge) suite charge $C/charge360_test_moves.lua "$PY verify_inputs2.py patch" guile zangief feilong honda ;;
    leniency) suite leniency $C/leniency_test_moves.lua "$PY verify_leniency.py patch" ryu guile ;;
  esac
done
