-- Speak Selection: tap Ctrl+Option (no other key) to speak the selected text
-- with Kokoro, a local neural text-to-speech model. Fully offline.
-- Tap again while speaking to stop.

hs.autoLaunch(true)
hs.dockIcon(false)
hs.menuIcon(true)

require("hs.ipc")
hs.ipc.cliInstall("/opt/homebrew")

local speakScript = os.getenv("HOME") .. "/.local/bin/speak-selection"

-- Speech speed: Ctrl+Option+minus slower, Ctrl+Option+equals faster.
-- Writes ~/.config/speak-selection/speed; applies from the next utterance.
local speedFile = os.getenv("HOME") .. "/.config/speak-selection/speed"

local function bumpSpeed(delta)
  local f = io.open(speedFile, "r")
  local v = (f and tonumber((f:read("*a") or ""):match("[%d.]+"))) or 1.2
  if f then f:close() end
  v = math.max(0.5, math.min(2.5, v + delta))
  v = math.floor(v * 100 + 0.5) / 100
  f = io.open(speedFile, "w")
  if f then f:write(tostring(v)); f:close() end
  hs.alert.show(string.format("Speech speed: %.2f", v), 0.8)
end

hs.hotkey.bind({ "ctrl", "alt" }, "-", function() bumpSpeed(-0.05) end)
hs.hotkey.bind({ "ctrl", "alt" }, "=", function() bumpSpeed(0.05) end)

-- Caption overlay: shows the sentence currently being spoken, bottom-center.
-- Driven by speak-selection via the hs CLI: captionShow('<textfile>') per
-- sentence, captionHide() when speech ends or is stopped.
local CAPTION_W = 720
captionCanvas = nil

function captionShow(path)
  local f = io.open(path, "r")
  if f == nil then return end
  local text = (f:read("*a") or ""):gsub("^%s+", ""):gsub("%s+$", "")
  f:close()
  if text == "" then return end
  local styled = hs.styledtext.new(text, {
    font = { size = 20 },
    color = { white = 1 },
    paragraphStyle = { alignment = "center", lineBreak = "wordWrap" },
  })
  -- Rebuild the canvas each time: mutating a shown canvas's text does not
  -- reliably repaint, so a fresh canvas per sentence forces a real redraw.
  captionHide()
  captionCanvas = hs.canvas.new({ x = 0, y = 0, w = CAPTION_W, h = 100 })
  captionCanvas:level(hs.canvas.windowLevels.overlay)
  captionCanvas:behavior({ "canJoinAllSpaces", "stationary" })
  captionCanvas[1] = {
    type = "rectangle", action = "fill",
    fillColor = { alpha = 0.85, red = 0.08, green = 0.08, blue = 0.10 },
    roundedRectRadii = { xRadius = 14, yRadius = 14 },
  }
  captionCanvas[2] = {
    type = "text", text = styled,
    frame = { x = 22, y = 14, w = CAPTION_W - 44, h = 72 },
  }
  -- minimumTextSize measures one unconstrained line; derive the wrapped
  -- height from the single-line width vs the box's usable width.
  local size = captionCanvas:minimumTextSize(2, styled)
  local usableW = CAPTION_W - 44
  local lines = math.max(1, math.ceil((size.w * 1.08) / usableW))
  local textH = math.min(lines * size.h + 6, 220)
  local h = textH + 28
  captionCanvas[2].frame = { x = 22, y = 14, w = CAPTION_W - 44, h = textH }
  local screen = hs.screen.mainScreen():frame()
  captionCanvas:frame({
    x = screen.x + (screen.w - CAPTION_W) / 2,
    y = screen.y + screen.h - h - 24,
    w = CAPTION_W, h = h,
  })
  captionCanvas:show()
end

function captionHide()
  if captionCanvas ~= nil then
    captionCanvas:delete()
    captionCanvas = nil
  end
end

local function isSpeaking()
  local out = hs.execute("pgrep -f 'speak-selection' 2>/dev/null")
  return out ~= nil and out ~= ""
end

local function stopSpeaking()
  -- afplay's argument contains "speak-selection-<uid>", so one pattern kills
  -- both the script and its player.
  -- CONT first: a paused (SIGSTOPped) process won't act on TERM until resumed.
  hs.execute("pkill -CONT -f 'speak-selection' 2>/dev/null; pkill -f 'speak-selection' 2>/dev/null")
  captionHide()
end

-- Playback transport, all global hotkeys:
--   Ctrl+Option+Space  pause / resume
--   Ctrl+Option+Left   previous sentence
--   Ctrl+Option+Right  next sentence
--   Ctrl+Option+1/2/3  switch voice (Onyx / Michael / Fenrir)
local cacheDir = os.getenv("HOME") .. "/.cache/speak-selection"

function speechPauseToggle()
  -- Derive paused/playing from real process state (T = SIGSTOPped) rather
  -- than a flag, so the toggle can never drift out of sync.
  local procs = hs.execute("pgrep -f 'speak-selection' 2>/dev/null")
  if procs == nil or procs == "" then return end
  local stopped = hs.execute(
    "pgrep -f 'speak-selection' | xargs ps -o state= -p 2>/dev/null | grep -c '^T'")
  if tonumber(stopped) ~= nil and tonumber(stopped) > 0 then
    hs.execute("pkill -CONT -f 'speak-selection' 2>/dev/null")
    hs.alert.show("Resumed", 0.6)
  else
    hs.execute("pkill -STOP -f 'speak-selection' 2>/dev/null")
    hs.alert.show("Paused", 0.6)
  end
end

local function speechNav(dir)
  hs.execute("pkill -CONT -f 'speak-selection' 2>/dev/null")
  hs.execute("mkdir -p '" .. cacheDir .. "'; echo " .. dir .. " > '" .. cacheDir
    .. "/cmd'; pkill -f 'afplay .*speak-selection' 2>/dev/null")
end

hs.hotkey.bind({ "ctrl", "alt" }, "space", speechPauseToggle)
hs.hotkey.bind({ "ctrl", "alt" }, "left", function() speechNav("back") end)
hs.hotkey.bind({ "ctrl", "alt" }, "right", function() speechNav("fwd") end)

local VOICES = {
  { key = "1", id = "am_onyx", name = "Onyx" },
  { key = "2", id = "am_michael", name = "Michael" },
  { key = "3", id = "am_fenrir", name = "Fenrir" },
}
for _, v in ipairs(VOICES) do
  hs.hotkey.bind({ "ctrl", "alt" }, v.key, function()
    hs.execute("echo " .. v.id .. " > '" .. os.getenv("HOME") .. "/.config/speak-selection/voice'")
    hs.alert.show("Voice: " .. v.name, 0.8)
    hs.task.new("/bin/zsh", nil, { "-c", "echo 'This is " .. v.name .. ".' | '" .. speakScript .. "'" }):start()
  end)
end

local function speakText(text)
  local tmp = os.tmpname()
  local fh = io.open(tmp, "w")
  if fh == nil then return end
  fh:write(text)
  fh:close()
  hs.task.new("/bin/zsh", function() os.remove(tmp) end,
    { "-c", "'" .. speakScript .. "' < " .. tmp }):start()
end

local copyPoll = nil

local function speakSelection()
  if isSpeaking() then
    stopSpeaking()
    return
  end
  if copyPoll ~= nil then copyPoll:stop(); copyPoll = nil end
  local app = hs.application.frontmostApplication()
  print(string.format("[speak] tap detected, frontmost=%s", app and app:name() or "?"))
  -- cmux (Ghostty) copies on select, and ignores synthetic Cmd+C anyway:
  -- the clipboard already holds the selection, so speak it directly.
  if app ~= nil and app:bundleID() == "com.cmuxterm.app" then
    local text = hs.pasteboard.getContents()
    print(string.format("[speak] cmux path, clipboard chars=%d", text and #text or 0))
    if text ~= nil and text ~= "" then
      speakText(text)
    else
      hs.alert.show("Clipboard empty", 0.7)
    end
    return
  end
  local before = hs.pasteboard.changeCount()
  hs.eventtap.keyStroke({ "cmd" }, "c")
  local waited = 0
  copyPoll = hs.timer.doEvery(0.05, function()
    waited = waited + 0.05
    if hs.pasteboard.changeCount() ~= before then
      copyPoll:stop(); copyPoll = nil
      local text = hs.pasteboard.getContents()
      print(string.format("[speak] copy OK, %d chars", text and #text or 0))
      if text ~= nil and text ~= "" then speakText(text) end
    elseif waited >= 0.8 then
      copyPoll:stop(); copyPoll = nil
      print(string.format("[speak] no clipboard change (count still %d)", before))
      hs.alert.show("No selection", 0.7)
    end
  end)
end

-- Detect a bare Ctrl+Option tap: both modifiers down, then all released,
-- with no regular key pressed in between and no extra modifiers involved.
local armed = false
local armedAt = 0

-- Global on purpose: a local-only eventtap gets garbage-collected, which
-- silently kills the hotkey minutes after startup.
tapWatcher = hs.eventtap.new(
  { hs.eventtap.event.types.flagsChanged, hs.eventtap.event.types.keyDown },
  function(event)
    if event:getType() == hs.eventtap.event.types.keyDown then
      armed = false -- it was a chord like Ctrl+Option+<key>, not a bare tap
      return false
    end
    local flags = event:getFlags()
    local exactlyCtrlOpt = flags.ctrl and flags.alt
      and not flags.cmd and not flags.shift and not flags.fn
    if exactlyCtrlOpt then
      armed = true
      armedAt = hs.timer.secondsSinceEpoch()
    elseif armed and not (flags.ctrl or flags.alt or flags.cmd or flags.shift) then
      armed = false
      if hs.timer.secondsSinceEpoch() - armedAt < 0.6 then
        -- Run outside the event callback: shelling out (pgrep etc.) in here
        -- can stall the tap long enough that macOS disables it silently —
        -- the "hotkey dies after one run" failure.
        hs.timer.doAfter(0, speakSelection)
      end
    elseif flags.cmd or flags.shift then
      armed = false
    end
    return false
  end)
tapWatcher:start()

hs.alert.show("Speak Selection loaded: tap Ctrl+Option", 1.5)
