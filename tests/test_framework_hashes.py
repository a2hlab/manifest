import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import probe_framework_vm  # noqa: E402


class FakeDevice:
    """sha256sum over hdc: answers from `files`. The calls numbered in `drop` lose their output; a path in
    `flaky` is answered the first time as the phone's sha256sum wrapper answers a file openssl failed on
    (an error line, no hash), then normally."""

    def __init__(self, files, drop=(), flaky=()):
        self.files, self.drop, self.flaky, self.calls = files, set(drop), set(flaky), 0

    def shell(self, command):
        self.calls += 1
        if self.calls in self.drop:
            return 1, ''
        assert command.startswith('sha256sum ')
        out = []
        for path in command.split()[1:]:
            if path in self.flaky:
                self.flaky.discard(path)
                out.append('sha256sum: ' + path + ': No such file or directory')
            elif path in self.files:
                out.append(self.files[path] + '  ' + path)
            else:
                out.append('sha256sum: ' + path + ': No such file or directory')
        return 0, '\n'.join(out) + '\n'


def files(n):
    return {'/stage/f%03d' % i: '%064x' % i for i in range(n)}


class RemoteHashesTest(unittest.TestCase):
    def test_batches_of_32(self):
        device = FakeDevice(files(70))
        self.assertEqual(probe_framework_vm.remote_hashes(device.shell, sorted(device.files)), device.files)
        self.assertEqual(device.calls, 3)

    def test_a_dropped_batch_is_missing_when_asked_once(self):
        device = FakeDevice(files(70), drop={2})
        got = probe_framework_vm.remote_hashes(device.shell, sorted(device.files))
        self.assertEqual(len(got), 70 - 32)

    def test_a_dropped_batch_is_asked_again(self):
        device = FakeDevice(files(70), drop={2})
        got = probe_framework_vm.remote_hashes(device.shell, sorted(device.files), attempts=3)
        self.assertEqual(got, device.files)
        self.assertEqual(device.calls, 4)  # three batches, then the dropped one again

    def test_a_file_answered_without_a_hash_is_asked_again_alone(self):
        device = FakeDevice(files(40), flaky={'/stage/f007'})
        notes = []
        got = probe_framework_vm.remote_hashes(device.shell, sorted(device.files), attempts=3, note=notes.append)
        self.assertEqual(got, device.files)
        self.assertEqual(device.calls, 3)  # two batches, then that one path
        self.assertEqual(len(notes), 1)
        self.assertIn('1 of 40 paths without a hash', notes[0])
        self.assertIn('sha256sum: /stage/f007: No such file or directory', notes[0])

    def test_a_different_hash_is_not_retried_away(self):
        device = FakeDevice(files(5))
        device.files['/stage/f002'] = 'f' * 64
        got = probe_framework_vm.remote_hashes(device.shell, sorted(device.files), attempts=3)
        self.assertEqual(got['/stage/f002'], 'f' * 64)
        self.assertEqual(device.calls, 1)

    def test_a_really_missing_file_stays_missing(self):
        device = FakeDevice(files(3))
        paths = sorted(device.files) + ['/stage/gone']
        got = probe_framework_vm.remote_hashes(device.shell, paths, attempts=3)
        self.assertNotIn('/stage/gone', got)
        self.assertEqual(len(got), 3)
        self.assertEqual(device.calls, 3)  # the first call, then only the missing path, twice


if __name__ == '__main__':
    unittest.main()
