import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from probe_source_app import read_host_window


class HostWindowTest(unittest.TestCase):
    def test_process_bound_record(self):
        for pid, window, expected in ((72, 31, 31), (71, 31, None), (72, 16, None), (72, 0, None)):
            with self.subTest(pid=pid, window=window):
                def shell(command):
                    if command.startswith('cat /proc/72/'):
                        return json.dumps({'ownerPid': pid, 'mainWindowId': window})
                    self.assertIn('WindowManagerService', command)
                    return 'previous 0 71 16 1\ncurrent 0 72 31 1'
                self.assertEqual(read_host_window(shell, 72), expected)

    def test_old_host_lifecycle_and_replacement(self):
        rows = 'oldHost 0 71 16 1\nhost 0 72 31 1\nchild 0 72 32 1001'
        cases = [
            ({'event': 'foreground', 'details': {}}, rows, 31),
            ({'details': {'id': 16}}, rows, 31),
            ({'details': {'id': 16}}, 'oldHost 0 71 16 1', None),
            ({'details': {'window': {'id': 31}}}, rows + '\nhost2 0 72 33 1', 31),
            ({'details': {}}, rows + '\nhost2 0 72 33 1', None),
        ]
        for state, table, expected in cases:
            with self.subTest(state=state, table=table):
                def shell(command):
                    if command.startswith('cat '):
                        return json.dumps(state)
                    self.assertIn('WindowManagerService', command)
                    return table
                self.assertEqual(read_host_window(shell, 72), expected)
