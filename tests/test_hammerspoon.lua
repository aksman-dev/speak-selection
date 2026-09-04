-- Run from the repository root: lua tests/test_hammerspoon.lua
-- The Hammerspoon APIs and filesystem are mocked; this never changes settings,
-- registers real hotkeys, or starts speech.
local configPath = (arg and arg[1]) or "hammerspoon/init.lua"
local function equal(actual, expected)
  assert(actual == expected, string.format("expected %s, got %s", tostring(expected), tostring(actual)))
end

local function boot(options)
  options = options or {}
  local home = "/Users/Test O'Brien"
  local configRoot = home .. "/.config"
  local configDir = configRoot .. "/hearmark"
  local state = { bindings = {}, alerts = {}, commands = {}, previews = 0, files = {}, dirs = { [home] = true } }
  state.configDir = configDir
  if options.existing then
    state.dirs[configRoot] = true
    state.dirs[configDir] = true
  end
  if options.speed then state.files[configDir .. "/speed"] = options.speed end
  local environment = setmetatable({}, { __index = _G })
  environment.os = { getenv = function(name) equal(name, "HOME"); return home end }
  environment.require = function(name) equal(name, "hs.ipc") end
  environment.print = function() end
  environment.io = {
    open = function(path, mode)
      if mode == "r" then
        if not state.files[path] then return nil, "No such file" end
        return { read = function() return state.files[path] end, close = function() return true end }
      end
      equal(mode, "w")
      if options.failure == "open" then return nil, "Permission denied" end
      if not state.dirs[path:match("^(.*)/[^/]+$")] then return nil, "No such directory" end
      state.files[path] = ""
      return {
        write = function(self, value)
          if options.failure == "write" then return nil, "No space left on device" end
          state.files[path] = state.files[path] .. value
          return self
        end,
        close = function()
          if options.failure == "close" then return nil, "Could not flush file" end
          return true
        end,
      }
    end,
  }
  environment.hs = {
    autoLaunch = function() end,
    dockIcon = function() end,
    menuIcon = function() end,
    ipc = { cliInstall = function() end },
    alert = { show = function(message, duration)
      table.insert(state.alerts, { message = message, duration = duration })
    end },
    fs = {
      attributes = function(path, attribute)
        equal(attribute, "mode")
        if state.dirs[path] then return "directory" end
        if state.files[path] then return "file" end
        return nil, "No such file"
      end,
      mkdir = function(path)
        if options.failure == "mkdir" then return nil, "Permission denied" end
        if not state.dirs[path:match("^(.*)/[^/]+$")] then return nil, "No such directory" end
        state.dirs[path] = true
        return true
      end,
    },
    hotkey = { bind = function(modifiers, key, callback)
      equal(table.concat(modifiers, "+"), "ctrl+alt")
      assert(not state.bindings[key], "duplicate hotkey: " .. key)
      state.bindings[key] = callback
    end },
    execute = function(command)
      table.insert(state.commands, command)
      if options.execute then return options.execute(command, #state.commands) end
      return ""
    end,
    task = { new = function()
      return { start = function() state.previews = state.previews + 1 end }
    end },
    eventtap = {
      event = { types = { flagsChanged = 1, keyDown = 2 } },
      new = function() return { start = function(self) self.started = true end } end,
    },
  }
  assert(loadfile(configPath, "t", environment))()
  state.alerts = {}
  state.environment = environment
  return state
end

local count = 0
local function test(name, callback)
  callback()
  count = count + 1
  print("ok - " .. name)
end

test("speed hotkey creates both missing config directories", function()
  local state = boot()
  state.bindings["="]()
  equal(tonumber(state.files[state.configDir .. "/speed"]), 1.25)
  equal(state.alerts[1].message, "Speech speed: 1.25")
  equal(#state.commands, 0)
end)

test("existing speed setting is adjusted and bounded", function()
  local state = boot({ existing = true, speed = "1.7\n" })
  state.bindings["-"]()
  equal(tonumber(state.files[state.configDir .. "/speed"]), 1.65)
  state.files[state.configDir .. "/speed"] = "2.5"
  state.bindings["="]()
  equal(tonumber(state.files[state.configDir .. "/speed"]), 2.5)
  state.files[state.configDir .. "/speed"] = "0.5"
  state.bindings["-"]()
  equal(tonumber(state.files[state.configDir .. "/speed"]), 0.5)
end)

local voices = {
  { "1", "am_onyx", "Onyx" }, { "2", "am_michael", "Michael" }, { "3", "am_fenrir", "Fenrir" },
  { "4", "af_heart", "Heart" }, { "5", "af_bella", "Bella" }, { "6", "af_nicole", "Nicole" },
}
for _, voice in ipairs(voices) do
  test("voice " .. voice[3] .. " persists on a fresh install and starts its preview", function()
    local state = boot()
    state.bindings[voice[1]]()
    equal(state.files[state.configDir .. "/voice"], voice[2])
    equal(state.alerts[1].message, "Voice: " .. voice[3])
    equal(state.previews, 1)
    equal(#state.commands, 0)
  end)
end

for _, failure in ipairs({ "mkdir", "open", "write", "close" }) do
  for _, setting in ipairs({ { "=", "speed" }, { "4", "voice" } }) do
    test(setting[2] .. " save failure at " .. failure .. " reports failure without a success alert or preview", function()
      local state = boot({ failure = failure })
      state.bindings[setting[1]]()
      equal(#state.alerts, 1)
      equal(state.alerts[1].message, "Could not save speech " .. setting[2])
      equal(state.previews, 0)
    end)
  end
end

for _, output in ipairs({ false, "" }) do
  test("idle pause with " .. tostring(output) .. " process output shows feedback only", function()
    local state = boot({ execute = function() if output == false then return nil end; return output end })
    state.bindings.space()
    equal(#state.commands, 1)
    equal(#state.alerts, 1)
    equal(state.alerts[1].message, "Nothing speaking")
    equal(state.alerts[1].duration, 0.6)
  end)
end

for _, playback in ipairs({ { "0\n", "STOP", "Paused" }, { "1\n", "CONT", "Resumed" } }) do
  test("active speech still " .. playback[3]:lower(), function()
    local state = boot({ execute = function(_, index)
      if index == 1 then return "123\n" end
      if index == 2 then return playback[1] end
      return ""
    end })
    state.bindings.space()
    equal(#state.commands, 3)
    assert(state.commands[3]:find("pkill -" .. playback[2], 1, true))
    equal(state.alerts[1].message, playback[3])
  end)
end

test("IPC entrypoints and the event tap retain their global lifetime", function()
  local environment = boot().environment
  equal(type(environment.captionShow), "function")
  equal(type(environment.captionHide), "function")
  equal(type(environment.speechPauseToggle), "function")
  equal(environment.tapWatcher.started, true)
end)

print(string.format("%d Hammerspoon tests passed", count))
