import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from probe_source_app import spawner_start_script, stage_dir  # noqa: E402

SUFFIX = 'a' * 32
INSPECTOR = (Path(__file__).resolve().parents[1] / 'tools/inspect_source_app.py').read_text()
INSPECTED = re.search(r"re\.fullmatch\(r'([^']+)', state\['stage'\]\)", INSPECTOR).group(1)


class StageRoot(unittest.TestCase):
    def test_default_and_installed_roots(self):
        self.assertEqual(stage_dir('/data/local/tmp', SUFFIX), '/data/local/tmp/a2hlab-app-' + SUFFIX)
        self.assertEqual(stage_dir('/data/local/tmp/', SUFFIX), '/data/local/tmp/a2hlab-app-' + SUFFIX)
        self.assertEqual(stage_dir('/data/local/tmp/a2hlab-installed', SUFFIX),
                         '/data/local/tmp/a2hlab-installed/a2hlab-app-' + SUFFIX)

    def test_other_places_are_refused(self):
        for root in ('/data/local', '/data/local/tmp/a/b', '/data/local/tmp/..', '/data/local/tmp/.hidden',
                     'relative', '/data/local/tmp/a b', '/system/tmp'):
            with self.assertRaises(ValueError, msg=root):
                stage_dir(root, SUFFIX)
        with self.assertRaises(ValueError):
            stage_dir('/data/local/tmp', 'not-a-suffix')

    def test_inspector_accepts_every_stage_the_launcher_makes(self):
        for root in ('/data/local/tmp', '/data/local/tmp/a2hlab-installed'):
            self.assertTrue(re.fullmatch(INSPECTED, stage_dir(root, SUFFIX)), root)
        self.assertFalse(re.fullmatch(INSPECTED, '/data/local/tmp/../a2hlab-app-' + SUFFIX))


class SpawnerStart(unittest.TestCase):
    COMMAND = ('nohup /data/local/tmp/a2hlab-installed/a2hlab-app-' + SUFFIX + '/source_app_namespace '
               '/data/app/el2/100/base/org.example/files/a2hlab-source-' + SUFFIX + ' 10123 /system/bin/sh '
               '/data/local/tmp/asx/run.sh >>/data/local/tmp/a2hlab-installed/a2hlab-app-' + SUFFIX +
               '/parent.log 2>&1 </dev/null &')

    def test_script_runs_the_launch_start_in_the_background(self):
        text = spawner_start_script('org.example', '/dev/unix/socket/A2HSourceabc', self.COMMAND)
        lines = text.splitlines()
        self.assertEqual(lines[0], '#!/system/bin/sh')
        self.assertTrue(lines[1].startswith('# org.example: starts its spawner on /dev/unix/socket/A2HSourceabc'))
        self.assertEqual(lines[2], self.COMMAND)
        self.assertEqual(len(lines), 3)

    def test_only_one_background_command(self):
        with self.assertRaises(ValueError):
            spawner_start_script('org.example', '/dev/unix/socket/x', self.COMMAND.rstrip(' &'))
        with self.assertRaises(ValueError):
            spawner_start_script('org.example', '/dev/unix/socket/x', 'rm -rf /\n' + self.COMMAND)


if __name__ == '__main__':
    unittest.main()
