import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from probe_source_app import default_store_activity_route, spawn_launcher


class SpawnLauncherTest(unittest.TestCase):
    def test_play_store_account_ui_uses_the_configured_official_service(self):
        store = 'google-two-path-store'
        pin = '1' * 64
        paired = {'WESTLAKE_PLAY_STORE_SERVE': 'store', 'WESTLAKE_PLAY_SERVICES_CONNECT': 'gms',
                  'WESTLAKE_CHANNEL_IDENTITY': 'enforce', 'WESTLAKE_PLAY_CODE_SPAWNER': '/test/spawner',
                  'WESTLAKE_PLAY_CODE_APK_SHA256': pin}
        route = 'WESTLAKE_REMOTE_ACTIVITIES'
        configured = dict(paired)
        self.assertTrue(default_store_activity_route(store, configured, pin))
        self.assertEqual(configured, {**paired, route: '1'})

        for app, env in [(store, {**paired, route: '0'}), ('another-app', paired),
                         (store, {**paired, 'WESTLAKE_PLAY_CODE_APK_SHA256': '2' * 64}),
                         (store, {**paired, 'WESTLAKE_CHANNEL_IDENTITY': 'observe'})]:
            before = dict(env)
            self.assertFalse(default_store_activity_route(app, env, pin))
            self.assertEqual(env, before)
        for key in paired:
            partial = {k: v for k, v in paired.items() if k != key}
            self.assertFalse(default_store_activity_route(store, partial, pin))
            self.assertNotIn(route, partial)

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
