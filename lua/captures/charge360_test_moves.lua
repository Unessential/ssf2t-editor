-- Charge / 360 / mash / Fei Long super check (verify_inputs2.py patch, then
-- verify_inputs.py check). Names "role:Move:input" as in inputs_test_moves.lua.
local QCF, HCF = {"D", "DF", "F"}, {"B", "DB", "D", "DF", "F"}
return {
  guile = {
    {name = "old:Sonic_Boom:charge",      kind = "charge", dirs = {"B", "F"}, btn = "HP"},
    {name = "new:Sonic_Boom:236",         kind = "motion", dirs = QCF, btn = "HP"},
    -- Flash Kick charge time: see charge_probe_moves.lua (its stored capture is a stand HK)
    {name = "new:Double_Somersault:236236", kind = "motion", dirs = {"D", "DF", "F", "D", "DF", "F"}, btn = "HK", super = true},
  },
  zangief = {
    {name = "old:Spinning_Piledriver:360",                kind = "motion", dirs = {"F", "DF", "D", "DB", "B", "UB", "U"}, btn = "HP", grab = true},
    {name = "new:Spinning_Piledriver:41236",              kind = "motion", dirs = HCF, btn = "HP", grab = true},
    {name = "kept:Running_Bear_Grab:360",         kind = "motion", dirs = {"F", "DF", "D", "DB", "B", "UB", "U"}, btn = "HK", grab = true},
  },
  feilong = {
    {name = "old:Rekka_Shinken:236236",   kind = "motion", dirs = {"D", "DF", "F", "D", "DF", "F"}, btn = "HP", super = true},
    {name = "new:Rekka_Shinken:41236",    kind = "motion", dirs = HCF, btn = "HP", super = true},
    {name = "new:Rekku_Kyaku:236",        kind = "motion", dirs = QCF, btn = "HK", late = 1},  -- see verify notes
  },
  honda = {
    {name = "kept:Hundred_Hand_Slap:6taps", kind = "mash", btn = "LP"},
    {name = "new:Hundred_Hand_Slap:2taps", kind = "mash", btn = "LP", taps = 2},
    {name = "kept:Sumo_Headbutt:charge",   kind = "charge", dirs = {"B", "F"}, btn = "HP"},
  },
}
