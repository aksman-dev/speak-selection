"""Run the mocked Lua checks through unittest discovery, without a live app.

Use a compatible Lua executable when available. On macOS, Hammerspoon's bundled
LuaSkin framework can supply an isolated Lua interpreter in a child process.
"""

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LUA_TEST = ROOT / "tests" / "test_hammerspoon.lua"
UNAVAILABLE = 77


def lua_executable():
    # The suite uses loadfile's environment argument, which Lua 5.1 lacks.
    probe = "assert(load('return marker', 'probe', 't', {marker=42})() == 42)"
    for name in ("lua", "lua5.4", "lua54", "lua5.3", "lua53", "lua5.2", "lua52", "luajit"):
        executable = shutil.which(name)
        if not executable:
            continue
        try:
            result = subprocess.run(
                [executable, "-e", probe], capture_output=True, timeout=5
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return executable
    return None


def run_luaskin(path):
    """Child-process entrypoint; never attaches to the running Hammerspoon app."""
    try:
        lua = ctypes.CDLL(path)
        lua.luaL_newstate.restype = ctypes.c_void_p
        lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lua.luaL_loadfilex.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lua.lua_pcallk.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_ssize_t, ctypes.c_void_p,
        ]
        lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lua.lua_tolstring.restype = ctypes.c_char_p
        lua.lua_close.argtypes = [ctypes.c_void_p]
    except (OSError, AttributeError) as error:
        print("Hammerspoon's bundled Lua runtime is unavailable: " + str(error))
        return UNAVAILABLE

    state = lua.luaL_newstate()
    if not state:
        print("Could not allocate a Lua interpreter", file=sys.stderr)
        return 1
    try:
        lua.luaL_openlibs(state)
        status = lua.luaL_loadfilex(state, os.fsencode(LUA_TEST), None)
        if status == 0:
            status = lua.lua_pcallk(state, 0, -1, 0, 0, None)
        if status:
            message = lua.lua_tolstring(state, -1, None)
            print(message.decode(errors="replace") if message else "Lua test failed", file=sys.stderr)
        return 1 if status else 0
    finally:
        lua.lua_close(state)


class HammerspoonTests(unittest.TestCase):
    def test_mocked_hotkeys_and_settings(self):
        executable = lua_executable()
        if executable:
            command = [executable, str(LUA_TEST)]
        else:
            candidates = []
            if sys.platform == "darwin":
                for applications in (Path("/Applications"), Path.home() / "Applications"):
                    candidates.append(
                        applications / "Hammerspoon.app" / "Contents" / "Frameworks"
                        / "LuaSkin.framework" / "Versions" / "A" / "LuaSkin"
                    )
            framework = next((path for path in candidates if path.is_file()), None)
            if framework is None:
                self.skipTest("Hammerspoon checks require Lua 5.2+ or Hammerspoon installed on macOS")
            command = [sys.executable, str(Path(__file__).resolve()), "--luaskin", str(framework)]

        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        if result.returncode == UNAVAILABLE:
            self.skipTest(output.strip())
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Hammerspoon tests passed", output)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--luaskin":
        raise SystemExit(run_luaskin(sys.argv[2]))
    unittest.main()
