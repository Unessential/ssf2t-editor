-- mame_states.lua -- headless state capture for ssf2t (MAME 0.242).
-- Boots, coins up, starts a 2P game, confirms both players' default picks
-- (P1 cursor taps Right P1_TAPS times first), waits for the round, then
-- drives P1 through named states while P2 idles or attacks on cue.
-- Every frame logs: state label, P1 char id, P1 anim_ptr, P1/P2 x.
-- Env: OUT (log path), P1_TAPS (cursor Right taps, default 0)
local OUT   = os.getenv("OUT") or "mame_states.txt"
local TAPS  = tonumber(os.getenv("P1_TAPS") or "0")
local DOWNS = tonumber(os.getenv("P1_DOWNS") or "0")   -- select grid has 2 rows of 8
local downs = 0
local OLD   = os.getenv("OLD") == "1"   -- P1 plays the old (SSF2) version
local P1, P2 = 0xFF844E, 0xFF884E
local mem   = manager.machine.devices[":maincpu"].spaces["program"]
local f     = assert(io.open(OUT, "w"))

-- ---- input helpers ------------------------------------------------------
local fields = {}
for _, port in pairs(manager.machine.ioport.ports) do
  for name, fld in pairs(port.fields) do fields[name] = fld end
end
local held = {}
local function press(list) held = {}; for _, n in ipairs(list) do held[n] = true end end
local function apply()
  for name, fld in pairs(fields) do
    if name:match("^P[12] ") or name:match("Start") or name:match("^Coin") then
      fld:set_value(held[name] and 1 or 0)
    end
  end
end
local B = {LP="Button 1", MP="Button 2", HP="Button 3", LK="Button 4", MK="Button 5", HK="Button 6"}
local function p(pl, k) return pl .. " " .. (B[k] or k) end

local function in_match() return mem:read_u32(0xFF8004) == 0x40000 and mem:read_u32(0xFF8008) == 0x40000 end
local function x(base) return mem:read_i16(base + 0x06) end

-- ---- script: list of steps {label, frames, fn(t)->keys} ------------------
-- P1 starts on the left facing right, so forward = Right, back = Left.
local function hold(keys) return function() return keys end end
local function approach(gap) -- P2 walks toward P1 until within gap px
  return function() if x(P2) - x(P1) > gap then return {"P2 Left"} end return {} end
end
local function p2_attack(btn, extra, gap, p1keys)
  -- P2 closes to `gap`, then presses btn (with extra dirs) for 4f every 40f;
  -- P1 holds p1keys throughout.
  return function(t)
    local k = {}
    for _, v in ipairs(p1keys or {}) do k[#k+1] = v end
    if x(P2) - x(P1) > gap then k[#k+1] = "P2 Left"
    elseif t % 40 < 4 then
      k[#k+1] = p("P2", btn); for _, v in ipairs(extra or {}) do k[#k+1] = v end
    end
    return k
  end
end
local STEPS = {
  {"stand",        90, hold({})},
  {"walk_fwd",     60, hold({"P1 Right"})},
  {"stand",        30, hold({})},
  {"walk_back",    60, hold({"P1 Left"})},
  {"stand",        30, hold({})},
  {"crouch",       60, hold({"P1 Down"})},
  {"stand_up",     30, hold({})},
  {"jump_neutral", 70, function(t) return t < 6 and {"P1 Up"} or {} end},
  {"jump_fwd",     70, function(t) return t < 6 and {"P1 Up", "P1 Right"} or {} end},
  {"jump_back",    70, function(t) return t < 6 and {"P1 Up", "P1 Left"} or {} end},
  {"close_in",    240, approach(70)},
  {"block_stand", 160, p2_attack("MP", {}, 70, {"P1 Left"})},
  {"block_crouch",160, p2_attack("MK", {"P2 Down"}, 70, {"P1 Left", "P1 Down"})},
  {"hit_stand",   160, p2_attack("MP", {}, 70, {})},
  {"hit_crouch",  160, p2_attack("LK", {"P2 Down"}, 70, {"P1 Down"})},
  {"knockdown",   300, p2_attack("HK", {"P2 Down"}, 70, {})},
}

-- STEPSET=hits: one P2 hit per button on a standing (then crouching) P1, plus a
-- fireball (QCF+P toward P1; P2 faces left, so forward = Left). One press per
-- step keeps P1 from getting dizzied.
local function p2_once(btn, extra, gap, p1keys)
  local fired = false
  return function(t)
    local k = {}
    for _, v in ipairs(p1keys or {}) do k[#k+1] = v end
    if t == 0 then fired = false end
    if not fired then
      if x(P2) - x(P1) > gap then k[#k+1] = "P2 Left"
      else
        k[#k+1] = p("P2", btn); for _, v in ipairs(extra or {}) do k[#k+1] = v end
        if t > 0 then fired = true end
      end
    end
    return k
  end
end
-- HITPOSE=st|cr|all limits the hits set to one pose, so a character with low
-- health/stun isn't KO'd or dizzied partway through.
local HITPOSE = os.getenv("HITPOSE") or "all"
local function p2_fireball(p1keys)
  return function(t)
    local k = {}
    for _, v in ipairs(p1keys or {}) do k[#k+1] = v end
    if t < 4 then k[#k+1] = "P2 Down"
    elseif t < 8 then k[#k+1] = "P2 Down"; k[#k+1] = "P2 Left"
    elseif t < 12 then k[#k+1] = "P2 Left"; k[#k+1] = p("P2", "HP") end
    return k
  end
end
if os.getenv("STEPSET") == "hits" then
  local S2 = {{"stand", 60, hold({})}}
  for _, pose in ipairs({{"st", {}}, {"cr", {"P1 Down"}}}) do
    if HITPOSE ~= "all" and HITPOSE ~= pose[1] then goto nextpose end
    for _, b in ipairs({"LP", "MP", "HP", "LK", "MK", "HK"}) do
      S2[#S2+1] = {"gap_"..pose[1].."_"..b, 70, function() local k = {}
        for _, v in ipairs(pose[2]) do k[#k+1] = v end
        if x(P2) - x(P1) < 120 then k[#k+1] = "P2 Right" end; return k end}
      S2[#S2+1] = {"hit_"..pose[1].."_"..b, 110, p2_once(b, {}, 64, pose[2])}
    end
    ::nextpose::
  end
  for i = 1, (HITPOSE == "cr" and 0 or 2) do
    S2[#S2+1] = {"gap_far", 140, function() if x(P2) - x(P1) < 220 then return {"P2 Right"} end return {} end}
    S2[#S2+1] = {"hit_st_fireball", 150, p2_fireball({})}
  end
  STEPS = S2
end

-- STEPSET=normals: P1 does every stand/crouch/jump normal with P2 parked at the
-- far side, so P1 can never be in hit-stun. Attack frames live OUTSIDE the
-- character's anim list, so post-processing keeps only those frame addresses.
local BTN_NAME = {LP="Weak Punch", MP="Medium Punch", HP="Strong Punch",
                  LK="Weak Kick", MK="Medium Kick", HK="Strong Kick"}
if os.getenv("STEPSET") == "normals" then
  local S2 = {{"separate", 200, hold({"P1 Left", "P2 Right"})}, {"stand", 30, hold({})}}
  for _, b in ipairs({"LP", "MP", "HP", "LK", "MK", "HK"}) do
    S2[#S2+1] = {"n_stand_"..b, 75, function(t) return t < 4 and {p("P1", b)} or {} end}
  end
  for _, b in ipairs({"LP", "MP", "HP", "LK", "MK", "HK"}) do
    S2[#S2+1] = {"n_crouch_"..b, 75, function(t)
      if t < 8 then return {"P1 Down"} elseif t < 12 then return {"P1 Down", p("P1", b)} elseif t < 40 then return {"P1 Down"} end
      return {} end}
    S2[#S2+1] = {"stand", 20, hold({})}
  end
  for _, b in ipairs({"LP", "MP", "HP", "LK", "MK", "HK"}) do
    S2[#S2+1] = {"n_jump_"..b, 90, function(t)
      if t < 6 then return {"P1 Up"} elseif t >= 14 and t < 18 then return {p("P1", b)} end
      return {} end}
    S2[#S2+1] = {"stand", 20, hold({})}
  end
  STEPS = S2
end

-- STEPSET=cmdnormals: the normals the plain set misses -- direction + button
-- (command normals: forward/back standing, down-forward/down-back crouching,
-- down in the air), diagonal-jump normals, and close (proximity) normals with
-- P2 walked in until the pushboxes touch. Labels c_<kind>_<BTN>. The builder
-- drops any that turn out identical to the plain normal.
if os.getenv("STEPSET") == "cmdnormals" then
  local BTNS = {"LP", "MP", "HP", "LK", "MK", "HK"}
  local function join(a, b) local o = {} for _, v in ipairs(a) do o[#o+1] = v end for _, v in ipairs(b) do o[#o+1] = v end return o end
  local function refill() mem:write_u16(P2 + 0x2A, 0x90); mem:write_u16(P2 + 0x2C, 0x90); mem:write_u16(P2 + 0x5E, 0) end
  local S2 = {{"separate", 200, hold({"P1 Left", "P2 Right"})}, {"stand", 30, hold({})}}
  local function ground(kind, dirs)
    for _, b in ipairs(BTNS) do
      S2[#S2+1] = {"c_"..kind.."_"..b, 75, function(t)
        if t < 6 then return dirs elseif t < 10 then return join(dirs, {p("P1", b)})
        elseif t < 40 and dirs[1] == "P1 Down" then return dirs end
        return {} end}
      S2[#S2+1] = {"stand", 20, hold({})}
    end
  end
  ground("f", {"P1 Right"}); ground("b", {"P1 Left"})
  ground("df", {"P1 Down", "P1 Right"}); ground("db", {"P1 Down", "P1 Left"})
  local function air(kind, jump, extra)
    for _, b in ipairs(BTNS) do
      S2[#S2+1] = {"c_"..kind.."_"..b, 90, function(t)
        if t < 6 then return jump elseif t >= 14 and t < 18 then return join(extra, {p("P1", b)})
        elseif t >= 14 and t < 30 then return extra end
        return {} end}
      S2[#S2+1] = {"back", 50, function() return x(P1) > (START_X or x(P1)) + 6 and {"P1 Left"} or {} end}
    end
  end
  S2[#S2+1] = {"save", 2, function() START_X = x(P1); return {} end}
  air("jd", {"P1 Up"}, {"P1 Down"})                       -- neutral jump, down + button
  air("jf", {"P1 Up", "P1 Right"}, {})                    -- diagonal jump
  air("jfd", {"P1 Up", "P1 Right"}, {"P1 Down"})          -- diagonal jump, down + button
  -- close normals: P2 walks in until the gap stops shrinking, P1 presses the
  -- button with no direction (no throw); P2's health/stun refilled every time
  local function close(kind, dirs)
    for _, b in ipairs(BTNS) do
      S2[#S2+1] = {"apart", 70, function() refill(); return x(P2) - x(P1) < 140 and {"P2 Right"} or {} end}
      S2[#S2+1] = {"approach", 200, (function()
        local last, still = nil, 0
        return function(t)
          if t == 0 then last, still = nil, 0 end
          local g = x(P2) - x(P1)
          if last and g >= last then still = still + 1 else still = 0 end
          last = g
          if still < 3 then return {"P2 Left"} end
          return {} end end)()}
      S2[#S2+1] = {"c_"..kind.."_"..b, 75, function(t)
        if dirs[1] then
          if t < 6 then return dirs elseif t < 10 then return join(dirs, {p("P1", b)}) elseif t < 40 then return dirs end
          return {}
        end
        return t < 4 and {p("P1", b)} or {} end}
    end
  end
  close("close", {}); close("cclose", {"P1 Down"})
  STEPS = S2
end

-- STEPSET=specials: dizzy first (stun is easiest to build early in a round,
-- ~3 fireballs), then P1 thrown, P1 throws, then hits until KO.
-- Throw helper: the thrower walks in until the gap stops shrinking (pushboxes
-- touching -- wide characters like Honda/Zangief can't get within a fixed px
-- distance), then presses forward+HP once.
local function throw_by(pl, fwd)
  local done, last, still = false, nil, 0
  return function(t)
    if t == 0 then done, last, still = false, nil, 0 end
    if done then return {} end
    local g = x(P2) - x(P1)
    if last and g >= last then still = still + 1 else still = 0 end
    last = g
    if still < 3 and g > 30 then return {pl .. " " .. fwd} end
    done = true
    return {pl .. " " .. fwd, p(pl, "HP")}
  end
end
-- Fireball that keeps P2 within ~150px afterwards, so the next one lands soon
-- enough to build stun (pushback otherwise spreads them out and stun decays).
local function p2_fb_adv()
  local fb = p2_fireball({})
  return function(t)
    if t < 12 then return fb(t) end
    if x(P2) - x(P1) > 150 then return {"P2 Left"} end
    return {}
  end
end
if os.getenv("STEPSET") == "specials" or os.getenv("STEPSET") == "reactions" then
  -- Stun builds fastest from heavy hits landing close together, so P2 stays
  -- point-blank and alternates HP / HK about every 30 frames.
  local STUN_LEVEL = tonumber(os.getenv("STUN_LEVEL") or "30")
  local function p2_rush()
    local last, n = -100, 0
    return function(t)
      if t == 0 then last, n = -100, 0 end
      if x(P2) - x(P1) > 60 then
        -- Pre-load P1's stun just under the dizzy point (meter byte obj+0x5F,
        -- decay timer word obj+0x5D -- addresses from pof's training lua) so
        -- the first clean heavy hit dizzies. Capture-only RAM poke.
        mem:write_u8(P1 + 0x5F, STUN_LEVEL)
        mem:write_u8(P1 + 0x5D, 0xF0); mem:write_u8(P1 + 0x5E, 0x00)   -- odd address: bytes, not a word
      end
      if x(P2) - x(P1) > 50 then return {"P2 Left"} end
      if t - last >= 30 then last = t; n = n + 1 end
      if t - last < 4 then return {p("P2", (n % 2 == 1) and "HP" or "HK")} end
      return {}
    end
  end
  STEPS = {{"rush", 240, p2_rush()}}
  for _, s in ipairs({
    {"dizzy_watch", 300, hold({})},
    {"recover", 60, hold({"P2 Right"})},
    {"thrown", 420, throw_by("P2", "Left")},
    {"recover", 60, hold({"P2 Right"})},
    {"p1_throw", 420, throw_by("P1", "Right")},
  }) do STEPS[#STEPS+1] = s end
end

-- STEPSET=moves: special moves + supers from st_moves.lua (MOVES_FILE). Steps
-- are built once the match starts, from the character the game actually
-- loaded. A savestate taken with P2 parked far away is reloaded before every
-- move, so each one starts from the same spot (dashes can't swap sides).
local DIRK = {F = {"P1 Right"}, B = {"P1 Left"}, D = {"P1 Down"}, U = {"P1 Up"},
  DF = {"P1 Down", "P1 Right"}, DB = {"P1 Down", "P1 Left"},
  UF = {"P1 Up", "P1 Right"}, UB = {"P1 Up", "P1 Left"}}
local function join(a, b) local o = {} for _, v in ipairs(a or {}) do o[#o+1] = v end for _, v in ipairs(b or {}) do o[#o+1] = v end return o end
local function move_inputs(mv, b)
  local s = {}
  local function add(keys, n) for _ = 1, n do s[#s+1] = keys end end
  local btns
  if b == "PPP" then btns = {p("P1","LP"), p("P1","MP"), p("P1","HP")}
  elseif b == "KKK" then btns = {p("P1","LK"), p("P1","MK"), p("P1","HK")}
  else btns = {p("P1", b)} end
  local DF_ = mv.dirf or tonumber(os.getenv("DIRF") or "2")   -- frames per motion direction
  if mv.kind == "motion" then
    local d = mv.dirs
    for i = 1, #d - 1 do add(DIRK[d[i]], DF_) end
    -- late = N: hold the last direction N frames before the button joins it
    if mv.late then add(DIRK[d[#d]], mv.late) end
    add(join(DIRK[d[#d]], btns), 3)
    -- holdbtn = N: keep the button held N more frames (Ken's Inazuma Kick)
    if mv.holdbtn then add(btns, mv.holdbtn) end
  elseif mv.kind == "charge" then
    add(DIRK[mv.dirs[1]], mv.hold or 64)       -- hold = charge frames (default 64)
    for i = 2, #mv.dirs - 1 do add(DIRK[mv.dirs[i]], 2) end
    add(join(DIRK[mv.dirs[#mv.dirs]], btns), 3)
  elseif mv.kind == "mash" then
    local n, gap = mv.taps or tonumber(os.getenv("MASHN") or "6"), tonumber(os.getenv("MASHGAP") or "2")
    for _ = 1, n do add(btns, gap); add({}, gap) end
  elseif mv.kind == "hold3" then
    add(btns, 70); add({}, 2)
  elseif mv.kind == "air" then
    add(join(DIRK[mv.jump[1]], DIRK[mv.jump[2]]), 6); add({}, 8)
    for _, d in ipairs(mv.air) do add(DIRK[d], 2) end
    add(btns, 3)
  end
  return s
end
START_X, START_X2 = nil, nil          -- P1/P2 X when the move set starts (set by the "save" step)
local function build_moves(cname)
  local tbl = dofile(os.getenv("MOVES_FILE"))[cname]
  if not tbl then return {} end
  local S = {}
  for _, mv in ipairs(tbl) do
    local strengths = (mv.btn == "P") and {"LP","MP","HP"} or (mv.btn == "K") and {"LK","MK","HK"} or {mv.btn}
    for _, b in ipairs(strengths) do
      -- MOVE_ONLY="Name|BTN,Name|BTN" reruns just those (e.g. after a timing miss)
      local only = os.getenv("MOVE_ONLY")
      if only == "" then only = nil end
      if only and not (("," .. only .. ","):find("," .. mv.name .. "|" .. b .. ",", 1, true)) then goto skip end
      local seq = move_inputs(mv, b)
      local label = "mv|" .. mv.name:gsub("%s", "_") .. "|" .. b
      -- Reset by walking (machine:load() never applied inside this script):
      -- P1 back to the start X once standing, P2 parked at the far right.
      S[#S+1] = {"reset", 300, function(t)
        local k = {}
        if t > 40 then                      -- let the previous move finish first
          -- both players walk back to their own start X (they can't be more than
          -- one screen apart, so pinning P2 in the corner traps P1 forward)
          local d1 = x(P1) - (START_X or x(P1))
          if d1 > 6 then k[#k+1] = "P1 Left" elseif d1 < -6 then k[#k+1] = "P1 Right" end
          local d2 = x(P2) - (START_X2 or x(P2))
          if d2 > 6 then k[#k+1] = "P2 Left" elseif d2 < -6 then k[#k+1] = "P2 Right" end
        end
        return k
      end}
      S[#S+1] = {"settle", 90, hold({})}  -- long enough to drop charge built while walking back
      if mv.grab then S[#S+1] = {"approach", 260, (function()
        local last, still = nil, 0
        return function(t)
          if t == 0 then last, still = nil, 0 end
          local g = x(P2) - x(P1)
          if last and g >= last then still = still + 1 else still = 0 end
          last = g
          if still < 3 then return {"P2 Left"} end
          return {}
        end end)()} end
      S[#S+1] = {label, #seq + 160, function(t)
        if mv.super then mem:write_u8(0xFF8702, 0x30) end
        return seq[t + 1] or {}
      end}
      ::skip::
    end
  end
  S[#S+1] = {"end", 2, hold({})}
  return S
end
if os.getenv("STEPSET") == "moves" then
  STEPS = {{"separate", 200, hold({"P2 Right"})},
           {"save", 4, function(t) START_X = x(P1); START_X2 = x(P2); return {} end},
           {"build", 1, hold({})}}
end

-- STEPSET=trace: write taps on P1 health (obj+0x2A/0x2C), stun (obj+0x5D..0x60)
-- and X position (obj+0x06) while P1 walks and gets hit. Each tap logs the 68k
-- PC of the writing instruction, so Ghidra can show where the value came from.
local TAPHANDLES = {}   -- keep write-tap handles alive
local cpu = manager.machine.devices[":maincpu"]
local cur_label = "?"
local tapseen = {}
local function tap_range(name, a, b)
  TAPHANDLES[#TAPHANDLES+1] = mem:install_write_tap(a, b, name, function(offset, data, mask)
    local pc = cpu.state["PC"].value
    local key = name .. pc .. cur_label .. data
    if not tapseen[key] then
      tapseen[key] = true
      f:write(string.format("TAP %-12s %-6s pc=0x%06X addr=0x%06X data=0x%04X mask=0x%04X\n",
        cur_label, name, pc, offset, data, mask))
    end
  end)
end
-- TRACE2: taps from power-on (so round-start init is caught), on the pending
-- damage word (obj+0x78), the movement-table pointer (obj+0x30) and health.
-- Stun-meter taps also log the victim's hit-type bytes (obj+0x1FC/0x1FD).
if os.getenv("STEPSET") == "trace" and os.getenv("TRACE2") then
  tap_range("health", P1 + 0x2A, P1 + 0x2D)
  tap_range("damage", P1 + 0x78, P1 + 0x79)
  tap_range("movptr", P1 + 0x30, P1 + 0x33)
  -- every write of P1's X by the movement step (add.l at 0x004398), as hi:lo of
  -- the 16.16 long, plus the direction (+11) and facing (+12) bytes it indexes by
  local xhi = 0
  TAPHANDLES[#TAPHANDLES+1] = mem:install_write_tap(P1 + 0x06, P1 + 0x09, "xlong", function(offset, data, mask)
    if cpu.state["PC"].value ~= 0x00439C then return end
    if offset == P1 + 0x06 then xhi = data
    else f:write(string.format("XT %-12s %d %d d11=%d d12=%d\n", cur_label, xhi, data, mem:read_u8(P1 + 0x11), mem:read_u8(P1 + 0x12))) end
  end)
  TAPHANDLES[#TAPHANDLES+1] = mem:install_write_tap(P1 + 0x5E, P1 + 0x5F, "stunmeter", function(offset, data, mask)
    f:write(string.format("TAP %-12s stunm  pc=0x%06X data=0x%04X type1FC=0x%02X type1FD=0x%02X\n",
      cur_label, cpu.state["PC"].value, data, mem:read_u8(P1 + 0x1FC), mem:read_u8(P1 + 0x1FD)))
  end)
end
if os.getenv("STEPSET") == "trace" then
  STEPS = {
    {"taps_on", 2, function(t)
      if #TAPHANDLES == 0 then   -- steps never see t == 0 (t is bumped before the call)
        tap_range("health", P1 + 0x2A, P1 + 0x2D)
        tap_range("stun", P1 + 0x5C, P1 + 0x61)
        tap_range("posx", P1 + 0x06, P1 + 0x07)
      end
      return {} end},
    {"stand", 60, hold({})},
    {"walk_fwd", 90, hold({"P1 Right"})},
    {"walk_back", 90, hold({"P1 Left"})},
    {"close_in", 200, approach(64)},
    {"hit_mp", 120, p2_once("MP", {}, 64, {})},
    {"gap", 60, hold({"P2 Right"})},
    {"hit_sweep", 240, p2_once("HK", {"P2 Down"}, 64, {})},
    {"gap", 60, hold({"P2 Right"})},
    {"hit_hp", 120, p2_once("HP", {}, 64, {})},
  }
end

-- STEPSET=verify: checks a patched ROM. Logs both players' health at round
-- start, then P2 lands one light, medium and heavy punch on a standing and a
-- crouching P1. Each write of P1's stun meter (+0x5E) logs old/new value,
-- attack strength (+0x1FD) and hit reaction (+0x55), so stun-table edits show
-- up as a shifted gain (base + random spread of 0x07F324).
if os.getenv("STEPSET") == "verify" then
  local function health_line(tag)
    f:write(string.format("HEALTH %s p1=%d/%d bar=%d p2=%d/%d bar=%d\n", tag,
      mem:read_i16(P1 + 0x2A), mem:read_i16(P1 + 0x2C), mem:read_i16(P1 + 0x1BC),
      mem:read_i16(P2 + 0x2A), mem:read_i16(P2 + 0x2C), mem:read_i16(P2 + 0x1BC)))
  end
  STEPS = {
    {"taps_on", 2, function()
      if #TAPHANDLES == 0 then
        health_line("start")
        TAPHANDLES[#TAPHANDLES+1] = mem:install_write_tap(P1 + 0x5E, P1 + 0x5F, "vstun", function(offset, data, mask)
          if offset ~= P1 + 0x5E then return end
          f:write(string.format("STUN %-10s old=%d new=%d gain=%d str=%d react=0x%02X pc=0x%06X\n", cur_label,
            mem:read_u16(P1 + 0x5E), data, data - mem:read_u16(P1 + 0x5E),
            mem:read_u8(P1 + 0x1FD), mem:read_u8(P1 + 0x55), cpu.state["PC"].value))
        end)
      end
      return {} end},
  }
  for _, pose in ipairs({{"st", {}}, {"cr", {"P1 Down"}}}) do
    for _, b in ipairs({"LP", "MP", "HP"}) do
      STEPS[#STEPS+1] = {"gap_"..pose[1].."_"..b, 70, function() local k = {}
        for _, v in ipairs(pose[2]) do k[#k+1] = v end
        if x(P2) - x(P1) < 120 then k[#k+1] = "P2 Right" end; return k end}
      STEPS[#STEPS+1] = {pose[1].."_"..b, 110, p2_once(b, {}, 64, pose[2])}
      -- let the stun meter drain between hits so one hit never dizzies
      STEPS[#STEPS+1] = {"rest", 200, function() return {"P2 Right"} end}
    end
  end
  -- other reactions: P1 hit out of a neutral jump, and swept
  STEPS[#STEPS+1] = {"gap_air", 90, function() if x(P2) - x(P1) > 70 then return {"P2 Left"} end
    if x(P2) - x(P1) < 50 then return {"P2 Right"} end return {} end}
  STEPS[#STEPS+1] = {"air_HP", 80, function(t) local k = {}
    if t < 6 then k[#k+1] = "P1 Up" end
    if t >= 10 and t < 14 then k[#k+1] = p("P2", "HP") end
    if t >= 30 and t < 34 then k[#k+1] = p("P2", "HK") end
    return k end}
  STEPS[#STEPS+1] = {"rest", 200, function() return {"P2 Right"} end}
  STEPS[#STEPS+1] = {"sweep", 160, p2_once("HK", {"P2 Down"}, 64, {})}
  STEPS[#STEPS+1] = {"end", 2, function() health_line("end"); return {} end}
end

-- STEPSET=dmg: P2 lands each normal 3 times on a standing P1 (health reset to
-- full before each hit so nothing scales with low health). A write tap on P1's
-- health (obj+0x2A) logs every hit: damage, P2's frame record (-> attack box ->
-- damage class) and both damage levels (obj+0x58, the damage table column).
if os.getenv("STEPSET") == "dmg" then
  local function hit_once(btn)
    local fired = false
    return function(t)
      if t == 1 then fired = false; mem:write_u16(P1 + 0x2A, 0x90); mem:write_u16(P1 + 0x2C, 0x90) end
      if fired then return {} end
      if x(P2) - x(P1) > 64 then return {"P2 Left"} end
      fired = true
      return {p("P2", btn)}
    end
  end
  STEPS = {
    {"taps_on", 2, function()
      if #TAPHANDLES == 0 then
        TAPHANDLES[#TAPHANDLES+1] = mem:install_write_tap(P1 + 0x2A, P1 + 0x2B, "dmgtap", function(offset, data, mask)
          local old = mem:read_i16(P1 + 0x2A)
          local new = data >= 0x8000 and data - 0x10000 or data
          if new < old then
            local dptr = mem:read_u32(P1 + 0x38) & 0xFFFFFF       -- defender's defense table
            f:write(string.format("DMG %-10s dmg=%d old=%d p2frame=0x%06X dl1=%d dl2=%d def=0x%06X defv=%d pc=0x%06X\n", cur_label, old - new, old,
              mem:read_u32(P2 + 0x1A) & 0xFFFFFF, mem:read_i16(P1 + 0x58), mem:read_i16(P2 + 0x58),
              dptr, mem:read_i8(dptr + mem:read_i16(P1 + 0x58)), cpu.state["PC"].value))
          end
        end)
      end
      return {} end},
  }
  for _, b in ipairs({"LP", "MP", "HP", "LK", "MK", "HK"}) do
    for rep = 1, 3 do
      STEPS[#STEPS+1] = {"gap_" .. b, 70, function() if x(P2) - x(P1) < 110 then return {"P2 Right"} end return {} end}
      STEPS[#STEPS+1] = {"hit_" .. b, 120, hit_once(b)}
    end
  end
end

-- STEPSET=fbdump: P1 throws a fireball (QCF + FB_BTN, default HP; P1 faces
-- right) and work RAM 0xFF0000-0xFFFFFF is dumped every frame for 40 frames
-- from the button press, to DUMPDIR/ram_NN.bin. Finds the projectile object.
if os.getenv("STEPSET") == "fbdump" then
  local DUMPDIR = os.getenv("DUMPDIR") or "."
  local BTN = os.getenv("FB_BTN") or "HP"
  local MOT = os.getenv("FB_MOTION") or "qcf"   -- qcf (Down, Down-Right, Right)
  STEPS = {
    {"stand", 60, hold({})},
    {"fireball", 70, function(t)
      local k = {}
      if MOT == "qcf" then
        if t < 4 then k = {"P1 Down"} elseif t < 8 then k = {"P1 Down", "P1 Right"}
        elseif t < 12 then k = {"P1 Right", p("P1", BTN)} end
      end
      if t >= 10 and t < 50 then
        local fh = assert(io.open(string.format("%s/ram_%02d.bin", DUMPDIR, t - 10), "wb"))
        local parts = {}
        for a = 0xFF0000, 0xFFFFFE, 2 do
          local w = mem:read_u16(a); parts[#parts+1] = string.char(w >> 8, w & 0xFF)
        end
        fh:write(table.concat(parts)); fh:close()
      end
      return k end},
  }
end

-- STEPSET=ticks: game logic ticks per video frame (Turbo speed / frame skip).
-- Counts writes to P1's anim timer (obj+0x18, decremented once per logic tick)
-- in each frame while P1 stands still, and logs the PCs doing the writing.
local tickcount, tickpcs = 0, {}
if os.getenv("STEPSET") == "ticks" then
  STEPS = {
    {"taps_on", 2, function()
      if #TAPHANDLES == 0 then
        TAPHANDLES[#TAPHANDLES+1] = mem:install_write_tap(P1 + 0x18, P1 + 0x19, "tick", function(offset, data, mask)
          local pc = cpu.state["PC"].value; tickpcs[pc] = (tickpcs[pc] or 0) + 1
          if pc == 0x002EE6 then tickcount = tickcount + 1 end   -- the per-tick decrement only
        end)
      end
      return {} end},
    {"count", 600, function(t)
      -- DUMPDIR set: also dump work RAM for the first 120 frames
      local dd = os.getenv("DUMPDIR")
      if dd and t <= 120 then
        local fh = assert(io.open(string.format("%s/tk_%03d.bin", dd, t), "wb"))
        local parts = {}
        for a = 0xFF0000, 0xFFFFFE, 2 do local w = mem:read_u16(a); parts[#parts+1] = string.char(w >> 8, w & 0xFF) end
        fh:write(table.concat(parts)); fh:close()
      end
      return {} end},
    {"report", 2, function()
      for pc, n in pairs(tickpcs) do f:write(string.format("TICKPC 0x%06X %d\n", pc, n)) end
      return {} end},
  }
end

-- RTLO/RTHI (hex): from power-on, log each distinct PC that reads or writes the
-- range (skips the boot RAM test at PC < 0x1000).
if os.getenv("RTLO") then
  local lo, hi, seen = tonumber(os.getenv("RTLO")), tonumber(os.getenv("RTHI")), {}
  local function note(kind) return function(offset, data, mask)
    local pc = cpu.state["PC"].value
    if pc < 0x1000 then return end
    local key = kind .. pc .. offset .. cur_label
    if not seen[key] then seen[key] = true
      f:write(string.format("RT %s pc=0x%06X addr=0x%06X data=0x%04X mask=0x%04X frame=%d label=%s\n",
        kind, pc, offset, data, mask, manager.machine.screens[":screen"]:frame_number(), cur_label)) end
  end end
  local rt_handles = {}
  function RT_INSTALL()
    -- RTMODE=W / R: only one kind of tap (a read tap on the same range seemed to
    -- shadow the write tap in moves runs)
    local mode = os.getenv("RTMODE") or "RW"
    for _, h in ipairs(rt_handles) do pcall(function() h:remove() end) end
    rt_handles = {}
    if mode:find("R") then rt_handles[#rt_handles+1] = mem:install_read_tap(lo, hi, "rtr", note("R")) end
    if mode:find("W") then rt_handles[#rt_handles+1] = mem:install_write_tap(lo, hi, "rtw", note("W")) end
    for _, h in ipairs(rt_handles) do TAPHANDLES[#TAPHANDLES+1] = h end
    f:write(string.format("RT installed 0x%06X-0x%06X\n", lo, hi))
  end
  -- taps were found to stop firing partway through long runs; RT_REFRESH=1
  -- reinstalls them at the start of every move step
  RT_REFRESH_FN = (os.getenv("RT_REFRESH") == "1") and RT_INSTALL or nil
  -- RT_LATE=1: install on the first scripted frame instead of at load (taps
  -- installed before the machine starts were not firing in some runs)
  if os.getenv("RT_LATE") ~= "1" then RT_INSTALL(); RT_INSTALL = nil end
end

-- VECTAP=1: log every read of the 68000 exception vectors 0x08-0x2F (bus /
-- address error, illegal instruction, zero divide, CHK, TRAPV, privilege,
-- trace, line A/F) with the CPU registers, to catch what crashed.
if os.getenv("VECTAP") == "1" then
  local vt = mem:install_read_tap(0x000008, 0x00002F, "vectap", function(offset, data, mask)
    local s = cpu.state
    f:write(string.format("VECTOR off=0x%02X pc=0x%06X sr=0x%04X a6=0x%08X a7=0x%08X d0=0x%08X d1=0x%08X frame=%d label=%s\n",
      offset, s["PC"].value, s["SR"].value, s["A6"].value, s["A7"].value, s["D0"].value, s["D1"].value,
      manager.machine.screens[":screen"]:frame_number(), cur_label or "?"))
  end)
  TAPHANDLES[#TAPHANDLES+1] = vt
end

-- TRACE_LABEL=<step label prefix> TRACE_FILE=<path>: with -debug, trace every
-- instruction while that step runs (MAME debugger "trace" command).
TRACE_LABEL, TRACE_ON = os.getenv("TRACE_LABEL"), false
function TRACE_CHECK(label)
  if not TRACE_LABEL or not manager.machine.debugger then return end
  local want = label:sub(1, #TRACE_LABEL) == TRACE_LABEL
  if want and not TRACE_ON then
    manager.machine.debugger:command("trace " .. (os.getenv("TRACE_FILE") or "trace.log") .. ",maincpu")
    TRACE_ON = true
  elseif not want and TRACE_ON then
    manager.machine.debugger:command("trace off,maincpu"); TRACE_ON = false
  end
end

-- ---- main state machine --------------------------------------------------
local frame, phase, t, step, taps = 0, "boot", 0, 1, 0
-- Projectile slots (pof's ssf2t profile): 8 objects of 0xC0 from 0xFF97A2,
-- active when the first word is 0x0101. Same layout as a player: x +0x06,
-- y +0x0A, anim +0x1A, owner +0x26, speed-entry ptr +0x30, hitbox block +0x34.
local PROJ, PROJ_N, PROJ_SZ = 0xFF97A2, 8, 0xC0
local function proj_info()
  local s = ""
  for i = 0, PROJ_N - 1 do
    local b = PROJ + i * PROJ_SZ
    if mem:read_u16(b) == 0x0101 and mem:read_u16(b + 0x26) == (P1 & 0xFFFF) then
      s = s .. string.format(" pj%d=x%d,y%d,an%06X,hb%06X,vel%06X", i, mem:read_i16(b + 6),
        mem:read_i16(b + 0x0A), mem:read_u32(b + 0x1A) & 0xFFFFFF,
        mem:read_u32(b + 0x34) & 0xFFFFFF, mem:read_u32(b + 0x30) & 0xFFFFFF)
    end
  end
  return s
end
local function log(label)
  -- mp = movement pointer (obj+0x30); xl/yl = full 16.16 position longs (obj+0x06/+0x0A);
  -- v/a = velocity x,y (obj+0x3C/+0x3E) and deceleration x,y (obj+0x40/+0x42), 1/256 px per tick
  f:write(string.format("%6d %-13s cid=%2d anim=0x%06X x1=%4d x2=%4d p2cid=%2d h2=%d old=%d hb=0x%06X mp=0x%08X xl=0x%08X yl=0x%08X v=%d,%d a=%d,%d%s\n", frame, label,
    mem:read_u8(P1 + 0x391), mem:read_u32(P1 + 0x1A) & 0xFFFFFF, x(P1), x(P2),
    mem:read_u8(P2 + 0x391), mem:read_i16(P2 + 0x2A), mem:read_u8(P1 + 0x3B6),
    mem:read_u32(P1 + 0x34) & 0xFFFFFF, mem:read_u32(P1 + 0x30), mem:read_u32(P1 + 0x06),
    mem:read_u32(P1 + 0x0A), mem:read_i16(P1 + 0x3C), mem:read_i16(P1 + 0x3E),
    mem:read_i16(P1 + 0x40), mem:read_i16(P1 + 0x42), proj_info()
      .. string.format(" dl=%d,%d", mem:read_i16(P1 + 0x58), mem:read_i16(P2 + 0x58))   -- damage level (table column)
      .. (os.getenv("STEPSET") == "ticks"
      and string.format(" ticks=%d", tickcount) or "")))
  tickcount = 0
end

-- OBJDUMP_ANIM=0x132228: the first time P1's anim pointer equals it (plus
-- OBJDUMP_DELAY frames, default 2, so the sprite list is built), dump CPS-2 object
-- RAM (0x700000-0x701FFF, 0x708000-0x709FFF) and P1's x/y to DUMPDIR.
local OBJDUMP_ANIM = tonumber(os.getenv("OBJDUMP_ANIM") or "")
local objdump_wait
local function objdump_check()
  if not OBJDUMP_ANIM then return end
  if not objdump_wait and (mem:read_u32(P1 + 0x1A) & 0xFFFFFF) == OBJDUMP_ANIM then
    objdump_wait = tonumber(os.getenv("OBJDUMP_DELAY") or "2")
  end
  if objdump_wait then
    objdump_wait = objdump_wait - 1
    if objdump_wait == 0 then
      local dd = os.getenv("DUMPDIR") or "."
      for _, r in ipairs({{0x700000, "obj700"}, {0x708000, "obj708"}}) do
        local fh = assert(io.open(dd .. "/" .. r[2] .. ".bin", "wb")); local parts = {}
        for a = r[1], r[1] + 0x1FFE, 2 do local w = mem:read_u16(a); parts[#parts+1] = string.char(w >> 8, w & 0xFF) end
        fh:write(table.concat(parts)); fh:close()
      end
      f:write(string.format("OBJDUMP anim=0x%06X x=%d y=%d facing=%d\n", OBJDUMP_ANIM, x(P1),
        mem:read_i16(P1 + 0x0A), mem:read_u8(P1 + 0x12)))
      OBJDUMP_ANIM = nil
    end
  end
end

-- POKE="0xFF8344=1,0xFF82DA=0": force bytes every frame from power-on
local POKES = {}
for a, v in (os.getenv("POKE") or ""):gmatch("(0x%x+)=(%d+)") do POKES[#POKES+1] = {tonumber(a), tonumber(v)} end
emu.register_frame_done(function()
  for _, pv in ipairs(POKES) do mem:write_u8(pv[1], pv[2]) end
  objdump_check()
  frame = frame + 1; t = t + 1
  local k = {}
  if phase == "boot" then
    if t > 1400 then phase = "coin"; t = 0 end   -- coins/starts are ignored during the region warning
  elseif phase == "coin" then          -- two coins, then both starts
    if t < 6 then k = {"Coin 1"} elseif t >= 20 and t < 26 then k = {"Coin 1"}
    elseif t >= 60 and t < 66 then k = {"1 Player Start"}
    elseif t >= 120 and t < 126 then k = {"2 Players Start"}
    elseif t > 300 then phase = "select"; t = 0 end
  elseif phase == "select" then        -- P1 Down x DOWNS, Right x TAPS, then confirm both
    local cyc = 12
    if downs < DOWNS then
      if t % cyc == 0 then downs = downs + 1 end
      if t % cyc < 1 then k = {"P1 Down"} end
    elseif taps < TAPS then
      if t % cyc == 0 then taps = taps + 1 end
      if t % cyc < 1 then k = {"P1 Right"} end
    elseif t % cyc >= 6 then
      phase = "confirm"; t = 0
    end
  elseif phase == "confirm" then
    if t < 6 then k = {p("P1","LP"), p("P2","LP")} end
    if t > 30 then phase = "wait_match"; t = 0 end
  elseif phase == "wait_match" and OLD then
    -- OLD=1: hold P1's old-version flag (obj+0x3B6, read by the round setup at
    -- 0x078324 to pick the id+0x11 tables) set until the round starts
    mem:write_u8(P1 + 0x3B6, 1)
    if t % 40 < 4 then k = {p("P1","LP"), p("P2","LP")} end
    if in_match() then phase = "settle"; t = 0
    elseif t > 1800 then f:write("ERROR: match never started\n"); manager.machine:exit() end
  elseif phase == "wait_match" then
    -- keep pulsing confirm: the first press can land before the grid is live
    if t % 40 < 4 then k = {p("P1","LP"), p("P2","LP")} end
    if in_match() then phase = "settle"; t = 0
    elseif t > 1800 then f:write("ERROR: match never started\n"); manager.machine:exit() end
    if t % 60 == 0 then f:write(string.format("%6d waiting  4=%08X 8=%08X\n", frame,
      mem:read_u32(0xFF8004), mem:read_u32(0xFF8008))) end
  elseif phase == "settle" then        -- let round intro finish
    if t > 300 then phase = "run"; t = 0; step = 1 end
  elseif phase == "run" then
    if RT_INSTALL then RT_INSTALL(); RT_INSTALL = nil end
    -- Long move lists outlast the 99s round: freeze the timer the way pof's
    -- training lua does (timer byte 0xFF8DCE; rewrite 0x9928 when it drops).
    if (os.getenv("STEPSET") == "moves" or os.getenv("STEPSET") == "cmdnormals") and mem:read_u8(0xFF8DCE) < 0x98 then
      mem:write_u16(0xFF8DCE, 0x9928)
    end
    if STEPS[step] and STEPS[step][1] == "build" then
      -- STEPSET=moves: append this character's moves now that we know who loaded
      local NM = {[0]="ryu","honda","blanka","guile","ken","chunli","zangief","dhalsim",
                  "dictator","sagat","boxer","claw","cammy","thawk","feilong","deejay"}
      for _, s2 in ipairs(build_moves(NM[mem:read_u8(P1 + 0x391)] or "")) do STEPS[#STEPS+1] = s2 end
    end
    local s = STEPS[step]
    if not s then f:write("DONE\n"); f:close(); manager.machine:exit(); return end
    if RT_REFRESH_FN and t == 1 and s[1]:sub(1, 3) == "mv|" then RT_REFRESH_FN() end
    cur_label = s[1]
    if TRACE_LABEL then TRACE_CHECK(s[1]) end
    k = s[3](t) or {}
    log(s[1])
    if t >= s[2] then step = step + 1; t = 0 end
  end
  press(k); apply()
end)
