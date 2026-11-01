-- Charge-time probe: Sonic Boom and Flash Kick with different hold lengths
-- (frames). Run on the pristine ROM and on one with the charge bytes changed.
-- Flash Kick: up is held 2 frames before up + kick (D then U+HK on the same
-- frame never gave a Flash Kick).
local t = {}
for _, h in ipairs({4, 8, 12, 16, 24, 32, 40, 48, 64}) do
  t[#t+1] = {name = "probe:Sonic_Boom:" .. h, kind = "charge", dirs = {"B", "F"}, btn = "HP", hold = h}
end
for _, h in ipairs({8, 16, 40, 64}) do
  t[#t+1] = {name = "probe:Flash_Kick:" .. h, kind = "charge", dirs = {"D", "U", "U"}, btn = "HK", hold = h}
  t[#t+1] = {name = "probe:Flash_Kick_UB:" .. h, kind = "charge", dirs = {"DB", "UB", "UB"}, btn = "HK", hold = h}
end
return {guile = t}
