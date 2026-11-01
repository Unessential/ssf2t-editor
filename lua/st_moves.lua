-- st_moves.lua -- Super Turbo special moves + supers, as inputs for P1 facing RIGHT
-- (forward = Right, back = Left). Used by mame_states.lua STEPSET=moves.
--
-- kind:
--   motion  dirs then button (each dir held 2f, button on the last dir)
--   charge  hold dirs[1] 64f, then the remaining dirs (2f each), button on the last
--   mash    tap the button 6 times
--   hold3   hold all 3 buttons 70f, release (Boxer's Turn Punch)
--   air     jump (dirs = jump dirs) then motion `air` + button in the air
-- btn: "P" / "K" = one capture per strength; "PPP" / "KKK" = all three at once;
--      "HP"/"HK"/... = that button only (supers use the strong one)
-- grab = true: P2 walks in until the pushboxes touch before the input
-- super = true: P1's super meter is filled first (byte 0xFF8702 = 0x30)
-- Inputs written from standard ST move lists; a '?' in the name means unsure.

local QCF  = {"D", "DF", "F"}
local QCB  = {"D", "DB", "B"}
local DP   = {"F", "D", "DF"}
local RDP  = {"B", "D", "DB"}
local HCF  = {"B", "DB", "D", "DF", "F"}
local HCB  = {"F", "DF", "D", "DB", "B"}
local R360 = {"F", "DF", "D", "DB", "B", "UB", "U"}
local function cat(...) local o = {} for _, t in ipairs({...}) do for _, v in ipairs(t) do o[#o+1] = v end end return o end
local QCF2 = cat(QCF, QCF)
local R720 = cat({"F", "DF", "D", "DB", "B", "UB", "U", "UF"}, R360)
local CHB  = {"B", "F"}          -- charge back, forward
local CHD  = {"D", "U"}          -- charge down, up
local CBFBF = {"B", "F", "B", "F"}
local CDBDF = {"DB", "DF", "DB", "UF"}

return {
  ryu = {
    {name = "Hadouken",            kind = "motion", dirs = QCF, btn = "P"},
    {name = "Shoryuken",           kind = "motion", dirs = DP,  btn = "P"},
    {name = "Tatsumaki",           kind = "motion", dirs = QCB, btn = "K"},
    {name = "Air Tatsumaki",       kind = "air", jump = {"U", "F"}, air = QCB, btn = "K"},
    {name = "Shakunetsu Hadouken", kind = "motion", dirs = HCF, btn = "P"},
    {name = "Shinku Hadouken (super)", kind = "motion", dirs = QCF2, btn = "HP", super = true},
  },
  ken = {
    {name = "Hadouken",            kind = "motion", dirs = QCF, btn = "P"},
    {name = "Shoryuken",           kind = "motion", dirs = DP,  btn = "P"},
    {name = "Tatsumaki",           kind = "motion", dirs = QCB, btn = "K"},
    {name = "Air Tatsumaki",       kind = "air", jump = {"U", "F"}, air = QCB, btn = "K"},
    {name = "Shoryureppa (super)", kind = "motion", dirs = QCF2, btn = "HK", super = true},
    -- New Ken's "crazy kicks" (Roundhouse Kicks); every kick button gives the same
    -- move. Holding the kick turns any of them into the Inazuma Kick overhead.
    {name = "Kama Barai Geri",     kind = "motion", dirs = QCF, btn = "K"},
    {name = "Nata Otoshi Geri",    kind = "motion", dirs = {"F", "DF", "D"}, btn = "K"},
    {name = "Oosoto Mawashi Geri", kind = "motion", dirs = HCF, btn = "K"},
    {name = "Inazuma Kakato Wari", kind = "motion", dirs = QCF, btn = "MK", holdbtn = 45},
  },
  guile = {
    {name = "Sonic Boom",          kind = "charge", dirs = CHB, btn = "P"},
    {name = "Flash Kick",          kind = "charge", dirs = CHD, btn = "K"},
    {name = "Double Somersault (super)", kind = "charge", dirs = CDBDF, btn = "HK", super = true},
  },
  chunli = {
    {name = "Kikoken",             kind = "charge", dirs = CHB, btn = "P"},
    {name = "Spinning Bird Kick",  kind = "charge", dirs = CHD, btn = "K"},
    {name = "Hyakuretsukyaku",     kind = "mash",   btn = "K"},
    {name = "Senretsukyaku (super)", kind = "charge", dirs = CBFBF, btn = "HK", super = true},
  },
  blanka = {
    {name = "Rolling Attack",      kind = "charge", dirs = CHB, btn = "P"},
    {name = "Vertical Roll",       kind = "charge", dirs = CHD, btn = "K"},
    {name = "Backstep Roll",       kind = "charge", dirs = CHB, btn = "K"},
    {name = "Electricity",         kind = "mash",   btn = "P"},
    {name = "Ground Shave Roll (super)", kind = "charge", dirs = CBFBF, btn = "HP", super = true},
  },
  honda = {
    {name = "Hundred Hand Slap",   kind = "mash",   btn = "P"},
    {name = "Sumo Headbutt",       kind = "charge", dirs = CHB, btn = "P"},
    {name = "Sumo Smash",          kind = "charge", dirs = CHD, btn = "K"},
    {name = "Oni-Musou (super)",   kind = "charge", dirs = CBFBF, btn = "HP", super = true},
  },
  zangief = {
    {name = "Spinning Piledriver", kind = "motion", dirs = R360, btn = "P", grab = true},
    {name = "Banishing Flat",      kind = "motion", dirs = {"F", "DF", "D"}, btn = "P"},  -- F,D,DF came out as a crouch punch
    {name = "Running Bear Grab",   kind = "motion", dirs = R360, btn = "K"},
    {name = "Double Lariat",       kind = "motion", dirs = {},   btn = "PPP"},
    {name = "Quick Double Lariat", kind = "motion", dirs = {},   btn = "KKK"},
    {name = "Final Atomic Buster (super)", kind = "motion", dirs = R720, btn = "HP", grab = true, super = true},
  },
  dhalsim = {
    {name = "Yoga Fire",           kind = "motion", dirs = QCF, btn = "P"},
    {name = "Yoga Flame",          kind = "motion", dirs = HCB, btn = "P"},
    {name = "Yoga Blast",          kind = "motion", dirs = HCB, btn = "K"},
    {name = "Yoga Teleport",       kind = "motion", dirs = DP,  btn = "PPP"},
    {name = "Yoga Inferno (super)", kind = "motion", dirs = cat(HCB, HCB), btn = "HP", super = true},
  },
  boxer = {
    {name = "Dash Straight",       kind = "charge", dirs = CHB, btn = "P"},
    {name = "Dash Upper",          kind = "charge", dirs = CHB, btn = "K"},
    {name = "Buffalo Headbutt",    kind = "charge", dirs = CHD, btn = "P"},
    {name = "Turn Punch",          kind = "hold3",  btn = "PPP"},
    {name = "Crazy Buffalo (super)", kind = "charge", dirs = CBFBF, btn = "HP", super = true},
  },
  claw = {
    {name = "Rolling Crystal Flash", kind = "charge", dirs = CHB, btn = "P"},
    {name = "Sky High Claw",       kind = "charge", dirs = CHD, btn = "P"},
    {name = "Flying Barcelona Attack", kind = "charge", dirs = CHD, btn = "K"},
    {name = "Scarlet Terror",      kind = "charge", dirs = {"DB", "F"}, btn = "K"},
    {name = "Rolling Izuna Drop (super)", kind = "charge", dirs = CDBDF, btn = "HK", super = true},
  },
  sagat = {
    {name = "Tiger Shot",          kind = "motion", dirs = QCF, btn = "P"},
    {name = "Ground Tiger Shot",   kind = "motion", dirs = QCF, btn = "K"},
    {name = "Tiger Uppercut",      kind = "motion", dirs = DP,  btn = "P"},
    {name = "Tiger Knee",          kind = "motion", dirs = {"D", "DF", "F", "UF"}, btn = "K"},
    {name = "Tiger Genocide (super)", kind = "motion", dirs = QCF2, btn = "HP", super = true},  -- ST uses punch (kick in other versions)
  },
  dictator = {
    {name = "Psycho Crusher",      kind = "charge", dirs = CHB, btn = "P"},
    {name = "Double Knee Press",   kind = "charge", dirs = CHB, btn = "K"},
    {name = "Head Stomp",          kind = "charge", dirs = CHD, btn = "K"},
    {name = "Devil Reverse",       kind = "charge", dirs = CHD, btn = "P"},
    {name = "Knee Press Nightmare (super)", kind = "charge", dirs = CBFBF, btn = "HK", super = true},
  },
  cammy = {
    {name = "Spiral Arrow",        kind = "motion", dirs = QCF, btn = "K"},
    {name = "Cannon Spike",        kind = "motion", dirs = DP,  btn = "K"},
    {name = "Spinning Knuckle",    kind = "motion", dirs = HCF, btn = "P"},
    {name = "Spin Drive Smasher (super)", kind = "motion", dirs = QCF2, btn = "HK", super = true},
  },
  thawk = {
    {name = "Mexican Typhoon",     kind = "motion", dirs = R360, btn = "P", grab = true},
    {name = "Tomahawk Buster",     kind = "motion", dirs = DP,   btn = "P"},
    {name = "Condor Dive",         kind = "air", jump = {"U", "F"}, air = {}, btn = "PPP"},
    {name = "Double Typhoon (super)", kind = "motion", dirs = R720, btn = "HP", grab = true, super = true},
  },
  feilong = {
    {name = "Rekka Ken",           kind = "motion", dirs = QCF, btn = "P"},
    {name = "Shien Kyaku",         kind = "motion", dirs = RDP, btn = "K"},
    {name = "Rekku Kyaku",         kind = "motion", dirs = {"B", "DB", "D", "DF", "F", "UF"}, btn = "K"},
    {name = "Rekka Shinken (super)", kind = "motion", dirs = QCF2, btn = "HP", super = true},
  },
  deejay = {
    {name = "Air Slasher",         kind = "charge", dirs = CHB, btn = "P"},
    {name = "Double Rolling Sobat", kind = "charge", dirs = CHB, btn = "K"},
    {name = "Jackknife Maximum",   kind = "charge", dirs = CHD, btn = "K"},
    {name = "Machine Gun Upper",   kind = "charge", dirs = CHD, btn = "P"},
    {name = "Sobat Carnival (super)", kind = "charge", dirs = CBFBF, btn = "HK", super = true},
  },
}
