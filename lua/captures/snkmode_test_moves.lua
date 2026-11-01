-- SNK-mode check (verify_snkmode.py patch + verify_inputs.py check): each move's
-- original motion ("old") must stop working, its SNK-style motion ("new") must
-- give the move. Names "role:Move:motion" as in inputs_test_moves.lua.
local M = {
  ["1632143"]  = {"DB", "F", "DF", "D", "DB", "B", "DF"},
  ["2363214"]  = {"D", "DF", "F", "DF", "D", "DB", "B"},
  ["2141236"]  = {"D", "DB", "B", "DB", "D", "DF", "F"},
  ["641236"]   = {"F", "B", "DB", "D", "DF", "F"},
  ["632146"]   = {"F", "DF", "D", "DB", "B", "F"},
  ["41236236"] = {"B", "DB", "D", "DF", "F", "D", "DF", "F"},
}
local QCF, DP, QCB, HCF = {"D", "DF", "F"}, {"F", "D", "DF"}, {"D", "DB", "B"}, {"B", "DB", "D", "DF", "F"}
return {
  ryu = {
    {name = "old:Hadouken:236",          kind = "motion", dirs = QCF, btn = "HP"},
    {name = "new:Hadouken:1632143",      kind = "motion", dirs = M["1632143"], btn = "HP"},
    {name = "old:Shoryuken:623",         kind = "motion", dirs = DP, btn = "HP"},
    {name = "new:Shoryuken:2141236",     kind = "motion", dirs = M["2141236"], btn = "HP"},
    {name = "old:Tatsumaki:214",         kind = "motion", dirs = QCB, btn = "HK"},
    {name = "new:Tatsumaki:2363214",     kind = "motion", dirs = M["2363214"], btn = "HK"},
    {name = "old:Shakunetsu:41236",      kind = "motion", dirs = HCF, btn = "HP"},
    {name = "new:Shakunetsu:641236",     kind = "motion", dirs = M["641236"], btn = "HP"},
    {name = "old:Shinku:236236",         kind = "motion", dirs = {"D", "DF", "F", "D", "DF", "F"}, btn = "HP", super = true},
    {name = "new:Shinku:2363214",        kind = "motion", dirs = M["2363214"], btn = "HP", super = true},
  },
  sagat = {
    {name = "old:Tiger_Shot:236",        kind = "motion", dirs = QCF, btn = "HP"},
    {name = "new:Tiger_Shot:2363214",    kind = "motion", dirs = M["2363214"], btn = "HP"},
    {name = "old:Tiger_Uppercut:623",    kind = "motion", dirs = DP, btn = "HP"},
    {name = "new:Tiger_Uppercut:41236236", kind = "motion", dirs = M["41236236"], btn = "HP"},
    {name = "old:Tiger_Knee:269",        kind = "motion", dirs = {"D", "F", "UF"}, btn = "HK"},
    {name = "new:Tiger_Knee:2363214",    kind = "motion", dirs = M["2363214"], btn = "HK"},
  },
}
