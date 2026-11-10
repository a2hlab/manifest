import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import probe_source_app  # noqa: E402

DT_INIT, DT_INIT_ARRAY, DT_INIT_ARRAYSZ = 12, 25, 27


def elf(tags):
    """A minimal ELF64 shared object: one PT_DYNAMIC program header over the given dynamic tags."""
    dynamic = b''.join(struct.pack('<qQ', tag, value) for tag, value in tags) + struct.pack('<qQ', 0, 0)
    at = 64 + 56
    phdr = struct.pack('<IIQQQQQQ', 2, 6, at, at, at, len(dynamic), len(dynamic), 8)
    ident = b'\x7fELF' + bytes([2, 1, 1]) + bytes(9)
    header = ident + struct.pack('<HHIQQQIHHHHHH', 3, 183, 1, 0, 64, 0, 0, 64, 56, 1, 64, 0, 0)
    return header + phdr + dynamic


def tags_of(data):
    at = 64 + 56
    found = []
    while True:
        tag, value = struct.unpack_from('<qQ', data, at)
        if tag == 0:
            return found
        found.append((tag, value))
        at += 16


class LegacyInitTest(unittest.TestCase):
    def test_both_renames_the_array(self):
        """libmsaoaidsec.so: DT_INIT and six array entries."""
        data = elf([(DT_INIT, 0x151b0), (DT_INIT_ARRAY, 0x2d588), (DT_INIT_ARRAYSZ, 48)])
        staged = probe_source_app.legacy_init_staged(data)
        self.assertEqual(tags_of(staged), [(DT_INIT, 0x151b0), (probe_source_app.WL_DT_INIT_ARRAY, 0x2d588),
                                           (probe_source_app.WL_DT_INIT_ARRAYSZ, 48)])

    def test_dt_init_alone_is_left(self):
        """The shim calls a DT_INIT-only library's DT_INIT itself; nothing to rename."""
        self.assertIsNone(probe_source_app.legacy_init_staged(elf([(DT_INIT, 0x48bcf8)])))

    def test_array_alone_is_left(self):
        data = elf([(DT_INIT_ARRAY, 0x2d588), (DT_INIT_ARRAYSZ, 16)])
        self.assertIsNone(probe_source_app.legacy_init_staged(data))

    def test_empty_array_is_left(self):
        data = elf([(DT_INIT, 0x15640), (DT_INIT_ARRAY, 0), (DT_INIT_ARRAYSZ, 0)])
        self.assertIsNone(probe_source_app.legacy_init_staged(data))

    def test_only_with_a_shim_that_runs_the_arrays(self):
        data = elf([(DT_INIT, 0x151b0), (DT_INIT_ARRAY, 0x2d588), (DT_INIT_ARRAYSZ, 48)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'libmsaoaidsec.so'
            path.write_bytes(data)
            self.assertEqual(probe_source_app.loader_compat_bytes(path), (None, []))
            fixed, changes = probe_source_app.loader_compat_bytes(path, legacy_init=True)
            self.assertEqual(changes, ['init array behind DT_INIT'])
            self.assertIn((probe_source_app.WL_DT_INIT_ARRAYSZ, 48), tags_of(fixed))


if __name__ == '__main__':
    unittest.main()
