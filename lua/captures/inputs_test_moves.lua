-- Input-remap check (STEPSET=moves). Run on a pristine ROM and on one patched by
-- verify_inputs.py. Names are "role:Move:motion":
--   ref   the game's original motion; on the pristine ROM it defines the move's
--         signature animations
--   old   the original motion again: must stop working after the remap
--   new   the remapped motion: must give the move after the patch
--   kept  an untouched move: must work on both ROMs
-- Notation as st_moves.lua (P1 facing right): pretzel 1632143 = DB F DF D DB B DF.
local PRETZEL = {"DB", "F", "DF", "D", "DB", "B", "DF"}
local QCF, DP, QCB = {"D", "DF", "F"}, {"F", "D", "DF"}, {"D", "DB", "B"}
local HCF = {"B", "DB", "D", "DF", "F"}
return {
  ryu = {
    {name = "old:Hadouken:236",       kind = "motion", dirs = QCF, btn = "HP"},
    {name = "old:Hadouken:236",       kind = "motion", dirs = QCF, btn = "LP"},
    {name = "new:Hadouken:1632143",   kind = "motion", dirs = PRETZEL, btn = "HP"},
    {name = "new:Hadouken:1632143",   kind = "motion", dirs = PRETZEL, btn = "LP"},
    {name = "kept:Shoryuken:623",     kind = "motion", dirs = DP, btn = "HP"},
    {name = "kept:Tatsumaki:214",     kind = "motion", dirs = QCB, btn = "HK"},
    {name = "kept:Shakunetsu:41236",  kind = "motion", dirs = HCF, btn = "HP"},
  },
  cammy = {
    {name = "old:Spiral_Arrow:236",   kind = "motion", dirs = QCF, btn = "MK"},
    {name = "new:Spiral_Arrow:214",   kind = "motion", dirs = {"D", "DB", "B"}, btn = "MK"},
    {name = "old:Cannon_Spike:623",   kind = "motion", dirs = DP, btn = "HK"},
    {name = "new:Cannon_Spike:421",   kind = "motion", dirs = {"B", "D", "DB"}, btn = "HK"},
    {name = "kept:Spinning_Knuckle:416", kind = "motion", dirs = HCF, btn = "HP"},
  },
}
