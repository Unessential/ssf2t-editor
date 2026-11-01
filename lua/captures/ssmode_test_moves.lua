-- Samurai Shodown mode check for Ryu (verify_snkmode.py patch <dir> ss, then
-- verify_inputs.py check). Names "role:Move:motion" as in inputs_test_moves.lua.
local M = {
  ["3214623"]   = {"DF", "D", "DB", "B", "F", "D", "DF"},
  ["341236421"] = {"DF", "B", "DB", "D", "DF", "F", "B", "D", "DB"},
  ["6321464"]   = {"F", "DF", "D", "DB", "B", "F", "B"},
  ["123623"]    = {"DB", "D", "DF", "F", "D", "DF"},
}
return {
  ryu = {
    {name = "old:Hadouken:236",           kind = "motion", dirs = {"D", "DF", "F"}, btn = "HP"},
    {name = "new:Hadouken:3214623",       kind = "motion", dirs = M["3214623"], btn = "HP"},
    {name = "old:Shoryuken:623",          kind = "motion", dirs = {"F", "D", "DF"}, btn = "HP"},
    {name = "new:Shoryuken:6321464",      kind = "motion", dirs = M["6321464"], btn = "HP"},
    {name = "old:Shakunetsu:41236",       kind = "motion", dirs = {"B", "DB", "D", "DF", "F"}, btn = "HP"},
    {name = "new:Shakunetsu:123623",      kind = "motion", dirs = M["123623"], btn = "HP"},
    {name = "old:Tatsumaki:214",          kind = "motion", dirs = {"D", "DB", "B"}, btn = "HK"},
    {name = "new:Tatsumaki:3214623",      kind = "motion", dirs = M["3214623"], btn = "HK"},
    {name = "old:Shinku:236236",          kind = "motion", dirs = {"D", "DF", "F", "D", "DF", "F"}, btn = "HP", super = true},
    {name = "new:Shinku:341236421",       kind = "motion", dirs = M["341236421"], btn = "HP", super = true},
  },
}
