-- Shortcut / input-timing check (verify_leniency.py patch, then verify_inputs.py
-- check <pristine> <patched> <cid>). Names "role:Move:input" as in inputs_test_moves.lua.
return {
  ryu = {
    {name = "kept:Hadouken:236",          kind = "motion", dirs = {"D", "DF", "F"}, btn = "HP"},
    {name = "new:Hadouken:336",           kind = "motion", dirs = {"DF", "DF", "F"}, btn = "HP"},  -- 2* takes the first 3
    {name = "new:Shakunetsu_Hadouken:16", kind = "motion", dirs = {"DB", "F"}, btn = "HP"},
    {name = "kept:Tatsumaki:214",         kind = "motion", dirs = {"D", "DB", "B"}, btn = "HK"},
    {name = "old:Tatsumaki:214slow",      kind = "motion", dirs = {"D", "DB", "B"}, btn = "HK", dirf = 6},
    {name = "kept:Shoryuken:623",         kind = "motion", dirs = {"F", "D", "DF"}, btn = "HP"},
    {name = "new:Shoryuken:623late",      kind = "motion", dirs = {"F", "D", "DF"}, btn = "HP", late = 20},
  },
  guile = {
    {name = "kept:Sonic_Boom:charge46",   kind = "charge", dirs = {"B", "F"}, btn = "HP"},
    {name = "new:Sonic_Boom:charge43",    kind = "charge", dirs = {"B", "DF"}, btn = "HP"},
  },
}
