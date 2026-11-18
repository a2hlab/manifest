import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from probe_source_app import spawn_launcher


class SpawnLauncherTest(unittest.TestCase):
    def test_listener_matches_child_environment_after_retained_relaunch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spawner = root / 'appspawn-x'
            spawner.write_text('#!/bin/sh\nprintf "%s\\n" "$1" "$2" "$WESTLAKE_SPAWN_SOCKET"\n')
            spawner.chmod(0o700)
            launcher = root / 'run.sh'
            initial = '/dev/unix/socket/A2HSource01'
            second = '/dev/unix/socket/A2HSource02'
            first = spawn_launcher(directory, {'WESTLAKE_SPAWN_SOCKET': initial})
            for path in (initial, second):
                launcher.write_text(first.replace(initial, path))
                result = subprocess.check_output(['sh', str(launcher)], text=True).splitlines()
                self.assertEqual(result, ['--socket-name', Path(path).name, path])


if __name__ == '__main__':
    unittest.main()
