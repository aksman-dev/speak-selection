# Hearmark

**Highlight. Tap. Listen.**

## Agent quick install

Paste this into your coding agent (Claude Code, Cursor, etc.) to set everything up:

> Clone `https://github.com/aksman-dev/hearmark.git` and install it on this
> Mac by following its README exactly. Concretely: (1) `brew install hammerspoon
> python@3.12 portaudio jq` — skip anything already installed. (2) Create the
> Kokoro venv at `~/.local/venvs/kokoro` with python3.12 and
> `pip install kokoro soundfile`. (3) Copy everything in `bin/` to
> `~/.local/bin/` and `chmod +x` them; confirm `~/.local/bin` is on PATH.
> (4) Install `hammerspoon/init.lua` to `~/.hammerspoon/init.lua` — if one
> already exists, merge rather than overwrite, and keep every variable that the
> file marks as intentionally global exactly as-is (a local eventtap gets
> garbage-collected and the hotkey dies). (5) Copy
> `macos/Hearmark.workflow` to `~/Library/Services/` and run
> `/System/Library/CoreServices/pbs -update`. (6) Optional Claude Code
> narration: copy `claude/commands/narrate.md` to `~/.claude/commands/` and
> merge the Stop hook from the README's install section into
> `~/.claude/settings.json` without clobbering existing hooks. (7) Launch
> Hammerspoon with `open -a Hammerspoon`, then tell me to grant it
> Accessibility permission — you cannot do that step. (8) Verify end-to-end:
> `echo "install test one. install test two." | ~/.local/bin/hearmark`
> must play audio (first run downloads the ~330MB Kokoro model) and show a
> caption overlay, and a second run must also work. Check
> `~/.cache/hearmark/last-run.log` for download progress or errors if
> speech does not start. Then tell me the hotkeys from the README table.

Select text anywhere on macOS, tap **Ctrl+Option**, and hear it read aloud by a
local neural voice (Kokoro-82M) — with a live caption overlay, pause/skip
transport controls, and optional per-session narration of Claude Code
responses. Everything runs on-device; no text ever leaves the machine.

## Hotkeys (global, via Hammerspoon)

| Keys | Action |
|---|---|
| Ctrl+Option (tap) | speak the selected text / stop |
| Ctrl+Option+Space | pause / resume |
| Ctrl+Option+Left / Right | previous / next sentence |
| Ctrl+Option+1 / 2 / 3 | voice: Onyx / Michael / Fenrir |
| Ctrl+Option+4 / 5 / 6 | voice: Heart (default) / Bella / Nicole |
| Ctrl+Option+`-` / `=` | slower / faster |

A dark caption bar at the bottom of the screen shows the sentence currently
being spoken. Pausing while idle shows “Nothing speaking”. Voice and speed
changes are saved for the next utterance; selecting a voice also plays a preview.

## Components

- `bin/hearmark` — core pipeline: reads text on stdin, synthesizes with
  Kokoro sentence-by-sentence, plays via `afplay`, drives the caption overlay,
  and supports pause/skip via a command file.
- `bin/kokoro-stream` — Python: text in, one wav + txt per sentence out
  (streamed, so playback starts before synthesis finishes).
- `bin/hearmark-speed` — set/show speaking speed from the terminal.
- `hammerspoon/init.lua` — hotkeys, caption overlay, transport controls.
- `macos/Hearmark.workflow` — right-click → Services → Hearmark
  fallback for apps that support macOS Services.
- Claude Code narration (optional):
  - `bin/claude-speak-hook` — Stop hook: speaks each finished response when
    narration is enabled for that session.
  - `bin/narrate-session`, `bin/claude-session-key` — per-session toggle,
    keyed by the session UUID from the `claude` process command line.
  - `claude/commands/narrate.md` — the `/narrate on|off|status` slash command.

## Install

Clone over HTTPS (no GitHub SSH key required), then run the steps below from
the checkout:

```sh
git clone https://github.com/aksman-dev/hearmark.git
cd hearmark
```

1. Prereqs: Homebrew, `brew install hammerspoon python@3.12 portaudio jq`.
2. Kokoro venv:
   ```sh
   "$(brew --prefix python@3.12)/bin/python3.12" -m venv ~/.local/venvs/kokoro
   ~/.local/venvs/kokoro/bin/pip install kokoro soundfile
   ```
   (First speech run downloads the ~330MB model from Hugging Face.)
3. Scripts:
   ```sh
   mkdir -p ~/.local/bin
   install -m 755 bin/* ~/.local/bin/
   ```
   Ensure `~/.local/bin` and a `python3` command are on PATH. `kokoro-stream`
   automatically uses the current user's `~/.local/venvs/kokoro/bin/python`;
   no shebang edits are needed.
4. Hammerspoon: copy `hammerspoon/init.lua` to `~/.hammerspoon/init.lua`
   (or merge if you already have config), launch Hammerspoon, grant
   Accessibility permission. `hs.ipc` must be installed
   (`hs.ipc.cliInstall("/opt/homebrew")` is in the config) — the scripts talk
   to Hammerspoon through `/opt/homebrew/bin/hs`.
5. Services menu (optional): copy `macos/Hearmark.workflow` to
   `~/Library/Services/`.
6. Claude Code narration (optional): copy `claude/commands/narrate.md` to
   `~/.claude/commands/`, and add a Stop hook to `~/.claude/settings.json`:
   ```json
   "Stop": [{ "hooks": [{ "type": "command", "command": "~/.local/bin/claude-speak-hook", "timeout": 10 }] }]
   ```
7. Verify speech and captions, then repeat the same command to check a second run:
   ```sh
   echo "Install test one. Install test two." | ~/.local/bin/hearmark
   ```

When upgrading an existing installation, reinstall the scripts and Hammerspoon
configuration together, and replace the older Services action with
`Hearmark.workflow`. Copy any saved `voice`, `speed`, and `narrate-sessions`
settings into `~/.config/hearmark/` to retain your preferences.

## Configuration

Plain files under `~/.config/hearmark/`, re-read on every run:

| File | Meaning | Default |
|---|---|---|
| `voice` | Kokoro voice id (`am_onyx`, `am_michael`, …) | `af_heart` |
| `speed` | 0.5–2.5, 1.0 = natural | 1.2 |

The voice and speed hotkeys create this directory when needed, including on
a fresh install.

## Troubleshooting

If speech does not start, inspect the latest run's diagnostics:

```sh
tail -n 50 ~/.cache/hearmark/last-run.log
```

The first run can take time while Kokoro downloads its model. In another
terminal, use `tail -f ~/.cache/hearmark/last-run.log` to follow download
progress and errors. Each new speech run replaces this log. A synthesis failure
or a run with no usable audio exits with a nonzero status.

## Tests

Run the regression checks from the checkout:

```sh
python3 -m unittest discover -s tests -v
```

These checks use temporary homes and stub synthesis/playback, so they need no
model download or audio device. The shell tests require zsh. The hotkey tests
use Lua 5.2+ or the Lua runtime bundled with Hammerspoon on macOS, and are
reported as skipped if neither is installed. Live hotkeys, audio, and captions
can be checked with the install verification above.

## Notes and gotchas (hard-won)

- The Hammerspoon eventtap **must** live in a global variable — a `local`
  eventtap is garbage-collected and the hotkey silently dies minutes later.
- The `hs` CLI consumes stdin: every `hs -c` call inside a `while read` loop
  needs `</dev/null` or it eats the loop's remaining input.
- Kokoro splits on newlines by default; the sentence-level captions rely on
  `split_pattern=r"(?<=[.!?])\s+|\n+"`.
- Pause is `SIGSTOP`/`SIGCONT` on everything matching `hearmark`;
  a stopped process ignores `SIGTERM` until continued, so stop paths send
  `-CONT` first.
