"""Exercise the installed launcher without downloading Kokoro or its model."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv


LAUNCHER = Path(__file__).resolve().parents[1] / "bin" / "kokoro-stream"


class KokoroStreamLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "a new user's home"
        self.installed = self.home / ".local" / "bin" / "kokoro-stream"
        self.installed.parent.mkdir(parents=True)
        shutil.copy2(LAUNCHER, self.installed)
        self.venv = self.home / ".local" / "venvs" / "kokoro"
        self.python = self.venv / "bin" / "python"
        self.output = self.home / "audio output"
        self.output.mkdir()
        self.record = self.home / "pipeline.json"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "KOKORO_VOICE": "am_michael",
            "KOKORO_SPEED": "1.7",
            "KOKORO_TEST_RECORD": str(self.record),
        }
        # Dependencies must come from the chosen venv, even if the caller uses
        # another Python environment. Do not inherit import-path overrides.
        self.env.pop("PYTHONPATH", None)
        self.env.pop("PYTHONHOME", None)

    def install_stub_dependencies(self):
        venv.EnvBuilder(with_pip=False, symlinks=True).create(self.venv)
        site_packages = subprocess.check_output(
            [str(self.python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            env=self.env,
            text=True,
        ).strip()
        modules = Path(site_packages)
        (modules / "kokoro.py").write_text(
            "import json, os, sys\n"
            "class KPipeline:\n"
            "    def __init__(self, **kwargs):\n"
            "        self.options = kwargs\n"
            "    def __call__(self, text, **kwargs):\n"
            "        with open(os.environ['KOKORO_TEST_RECORD'], 'w') as f:\n"
            "            json.dump(dict(text=text, prefix=sys.prefix, "
            "options=self.options, **kwargs), f)\n"
            "        yield text, None, [0.0]\n",
            encoding="utf-8",
        )
        (modules / "soundfile.py").write_text(
            "def write(path, audio, sample_rate):\n"
            "    assert sample_rate == 24000\n"
            "    with open(path, 'wb') as f:\n"
            "        f.write(b'test wav')\n",
            encoding="utf-8",
        )

    def run_launcher(self, *prefix):
        return subprocess.run(
            [*prefix, str(self.installed), str(self.output)],
            input="  Hello from a different home.\nSecond sentence!  ",
            text=True,
            capture_output=True,
            env=self.env,
            timeout=10,
        )

    def assert_successful_synthesis(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        wav, transcript = result.stdout.strip().split("\t")
        self.assertEqual(Path(wav).parent, self.output)
        self.assertEqual(Path(wav).read_bytes(), b"test wav")
        expected_text = "Hello from a different home.\nSecond sentence!"
        self.assertEqual(Path(transcript).read_text(), expected_text)
        record = json.loads(self.record.read_text())
        self.assertEqual(Path(record["prefix"]).resolve(), self.venv.resolve())
        self.assertEqual(record["text"], expected_text)
        self.assertEqual(record["voice"], "am_michael")
        self.assertEqual(record["speed"], 1.7)
        self.assertEqual(record["split_pattern"], r"(?<=[.!?])\s+|\n+")
        self.assertEqual(record["options"], {"lang_code": "a", "repo_id": "hexgrad/Kokoro-82M"})

    def test_copied_launcher_uses_current_home_and_preserves_input_and_options(self):
        self.install_stub_dependencies()
        self.assertTrue(self.python.is_symlink())
        self.assert_successful_synthesis(self.run_launcher())

    def test_symlinked_launcher_uses_current_home(self):
        self.install_stub_dependencies()
        self.installed.unlink()
        self.installed.symlink_to(LAUNCHER)
        self.assert_successful_synthesis(self.run_launcher())

    def test_explicit_system_python_switches_to_venv(self):
        self.install_stub_dependencies()
        self.assert_successful_synthesis(self.run_launcher(sys.executable))

    def test_running_with_venv_python_does_not_reexecute_forever(self):
        self.install_stub_dependencies()
        self.assert_successful_synthesis(self.run_launcher(str(self.python)))

    def test_missing_venv_has_actionable_error(self):
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(str(self.python), result.stderr)
        self.assertIn("Create the virtual environment", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_nonexecutable_venv_has_actionable_error(self):
        self.python.parent.mkdir(parents=True)
        self.python.write_text("not an executable")
        self.python.chmod(0o644)
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not executable", result.stderr)
        self.assertIn(str(self.python), result.stderr)

    def test_broken_interpreter_reports_exec_failure(self):
        self.python.parent.mkdir(parents=True)
        self.python.write_text("not a valid interpreter")
        self.python.chmod(0o755)
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("could not start Kokoro Python", result.stderr)

    def test_interpreter_without_venv_configuration_does_not_loop(self):
        self.python.parent.mkdir(parents=True)
        self.python.symlink_to(sys.executable)
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("not a working virtual environment", result.stderr)


if __name__ == "__main__":
    unittest.main()
