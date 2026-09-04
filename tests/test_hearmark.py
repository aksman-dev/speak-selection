"""Exercise the real zsh pipeline without a model, audio device, or Hammerspoon."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
ZSH = shutil.which("zsh")


@unittest.skipUnless(ZSH, "zsh is required")
class HearmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="speech-regression-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "Home with spaces"
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.cache = self.home / ".cache/hearmark"
        self.play_log = self.home / "played.txt"
        self.marker = self.home / "played-first"
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        TEST_PLAY_LOG=str(self.play_log),
                        TEST_PLAY_MARKER=str(self.marker),
                        HEARMARK_HS=str(self.bin / "hs"))
        self.write_script("pkill", "exit 0\n")
        self.write_script("hs", "exit 0\n")
        self.write_script("afplay", 'print -r -- "$1" >> "$TEST_PLAY_LOG"\n'
                          'touch "$TEST_PLAY_MARKER"\n')

    def write_script(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/zsh\nunsetopt BG_NICE\n" + body)
        path.chmod(0o755)
        return path

    def segment(self, name="first"):
        return (f'touch "$1/{name}.wav"\n'
                f'print -r -- "{name} sentence" > "$1/{name}.txt"\n'
                f'printf "%s\\t%s\\n" "$1/{name}.wav" "$1/{name}.txt"\n')

    def run_speech(self, text="Hello world."):
        return subprocess.run([ZSH, str(ROOT / "bin/hearmark")],
                              input=text, text=True, capture_output=True,
                              env=self.env, timeout=10)

    def assert_cleaned(self):
        self.assertFalse((self.cache / "speaker.pid").exists())
        self.assertEqual(list(self.cache.glob("run.*")), [])

    def test_missing_synthesizer_reports_failure(self):
        result = self.run_speech()
        self.assertEqual(result.returncode, 127, result.stderr)
        self.assertIn("last-run.log", result.stderr)
        self.assertIn("kokoro-stream", (self.cache / "last-run.log").read_text())
        self.assert_cleaned()

    def test_broken_interpreter_is_logged(self):
        path = self.bin / "kokoro-stream"
        path.write_text("#!/nonexistent/speech-test-python\n")
        path.chmod(0o755)
        result = self.run_speech()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bad interpreter", (self.cache / "last-run.log").read_text())
        self.assert_cleaned()

    def test_synthesis_error_preserves_exit_status_and_stderr(self):
        self.write_script("kokoro-stream", 'print -u2 -- "model unavailable"\nexit 23\n')
        result = self.run_speech()
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertIn("model unavailable", (self.cache / "last-run.log").read_text())
        self.assertIn("exit 23", result.stderr)
        self.assert_cleaned()

    def test_success_with_no_audio_is_an_error(self):
        self.write_script("kokoro-stream", "exit 0\n")
        result = self.run_speech()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no playable audio", result.stderr)
        self.assert_cleaned()

    def test_failure_after_first_segment_is_still_reported(self):
        self.write_script("kokoro-stream", self.segment() +
                          'print -u2 -- "later segment failed"\nexit 9\n')
        result = self.run_speech()
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertEqual(len(self.play_log.read_text().splitlines()), 1)
        self.assertIn("later segment failed", (self.cache / "last-run.log").read_text())
        self.assert_cleaned()

    def test_playback_starts_before_synthesis_finishes(self):
        self.write_script("kokoro-stream", self.segment() +
                          'for attempt in {1..100}; do\n'
                          '  [[ -e "$TEST_PLAY_MARKER" ]] && break\n'
                          '  sleep 0.02\n'
                          'done\n'
                          '[[ -e "$TEST_PLAY_MARKER" ]] || exit 42\n' +
                          self.segment("second"))
        result = self.run_speech()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([Path(p).name for p in self.play_log.read_text().splitlines()],
                         ["first.wav", "second.wav"])
        self.assert_cleaned()

    def test_synthesizer_receives_complete_stdin_and_eof(self):
        self.write_script("kokoro-stream", 'cat > "$HOME/received.txt"\n' +
                          self.segment())
        text = "First sentence.\nSecond sentence with 'quotes' and $dollars."
        result = self.run_speech(text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / "received.txt").read_text(), text + "\n")
        self.assertEqual(len(self.play_log.read_text().splitlines()), 1)
        self.assert_cleaned()

    def test_log_is_retained_and_replaced_on_next_run(self):
        for message in ("old diagnostic", "new diagnostic"):
            self.write_script("kokoro-stream", f'print -u2 -- "{message}"\n' + self.segment())
            result = self.run_speech()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.cache / "last-run.log").read_text(), message + "\n")
            self.assert_cleaned()

    def test_empty_input_does_not_start_synthesis(self):
        result = self.run_speech("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.cache.exists())

    def test_signal_like_synthesis_exit_codes_are_preserved(self):
        for code in (19, 127, 145):
            with self.subTest(code=code):
                self.write_script("kokoro-stream", f"exit {code}\n")
                result = self.run_speech()
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertNotIn("not a child", result.stderr)
                self.assert_cleaned()

    def test_repeated_pause_resume_preserves_final_synthesis_status(self):
        producer_pid = self.home / "producer.pid"
        player_pid = self.home / "player.pid"
        release = self.home / "release"
        for code in (0, 19, 127, 145):
            with self.subTest(code=code):
                for path in (producer_pid, player_pid, release, self.play_log):
                    path.unlink(missing_ok=True)
                self.write_script("kokoro-stream", 'print $$ > "$HOME/producer.pid"\n' +
                                  self.segment() + self.segment("second") +
                                  'while [[ ! -e "$HOME/release" ]]; do sleep 0.02; done\n'
                                  f"exit {code}\n")
                self.write_script("afplay", 'print $$ > "$HOME/player.pid"\n'
                                  'print -r -- "$1 start" >> "$TEST_PLAY_LOG"\n'
                                  'while [[ ! -e "$HOME/release" ]]; do sleep 0.02; done\n'
                                  'print -r -- "$1 end" >> "$TEST_PLAY_LOG"\n')
                proc = subprocess.Popen([ZSH, str(ROOT / "bin/hearmark")],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, env=self.env,
                                        start_new_session=True)
                children = []
                try:
                    proc.stdin.write("Hello. Second sentence.")
                    proc.stdin.close()
                    proc.stdin = None
                    deadline = time.monotonic() + 5
                    while not player_pid.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(player_pid.exists(), "playback never started")
                    children = [int(p.read_text()) for p in (producer_pid, player_pid)]
                    for _ in range(2):
                        # Match the hotkey: pause the synthesizer, player, and
                        # parent. Keep both children alive until both resumes.
                        for pid in [*children, proc.pid]:
                            os.kill(pid, signal.SIGSTOP)
                        time.sleep(0.05)
                        self.assertEqual(len(self.play_log.read_text().splitlines()), 1)
                        for pid in [proc.pid, *children]:
                            os.kill(pid, signal.SIGCONT)
                        time.sleep(0.05)
                    release.touch()
                    _, stderr = proc.communicate(timeout=5)
                    self.assertEqual(proc.returncode, code, stderr)
                    self.assertNotIn("not a child", stderr)
                    self.assertEqual(
                        [line.rsplit("/", 1)[-1] for line in self.play_log.read_text().splitlines()],
                        ["first.wav start", "first.wav end", "second.wav start", "second.wav end"])
                    self.assert_cleaned()
                finally:
                    if proc.poll() is None:
                        for pid in [proc.pid, *children]:
                            try:
                                os.kill(pid, signal.SIGCONT)
                            except ProcessLookupError:
                                pass
                        proc.terminate()
                        proc.communicate(timeout=5)

    def test_back_and_forward_commands_work_when_player_is_terminated(self):
        self.write_script("kokoro-stream", self.segment() + self.segment("second") +
                          self.segment("third"))
        self.write_script("afplay", 'print -r -- "$1" >> "$TEST_PLAY_LOG"\n'
                          'count=$(wc -l < "$TEST_PLAY_LOG")\n'
                          'case "$((count))" in\n'
                          '  1) print fwd > "$HOME/.cache/hearmark/cmd"; kill -TERM $$ ;;\n'
                          '  2) print back > "$HOME/.cache/hearmark/cmd"; kill -TERM $$ ;;\n'
                          'esac\n')
        result = self.run_speech()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([Path(p).name for p in self.play_log.read_text().splitlines()],
                         ["first.wav", "second.wav", "first.wav", "second.wav", "third.wav"])
        self.assert_cleaned()

    def test_termination_cleans_up_running_synthesizer_and_player(self):
        producer_pid = self.home / "producer.pid"
        player_pid = self.home / "player.pid"
        self.write_script("kokoro-stream", 'print $$ > "$HOME/producer.pid"\n' +
                          self.segment() + "exec sleep 10\n")
        self.write_script("afplay", 'print $$ > "$HOME/player.pid"\nexec sleep 10\n')
        proc = subprocess.Popen([ZSH, str(ROOT / "bin/hearmark")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.env,
                                start_new_session=True)
        try:
            proc.stdin.write("Hello world.")
            proc.stdin.close()
            proc.stdin = None
            deadline = time.monotonic() + 5
            while not player_pid.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(player_pid.exists(), "playback never started")
            children = [int(p.read_text()) for p in (producer_pid, player_pid)]
            proc.send_signal(signal.SIGTERM)
            _, stderr = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 143, stderr)
            for pid in children:
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            self.assert_cleaned()
        finally:
            # Clean up the isolated test process group, including any children
            # left behind if a regression makes an assertion fail.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
