import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import probe_source_app  # noqa: E402


def elf(soname, needed=(), defines=(), imports=()):
    """A minimal ELF64 shared object: section headers for .dynstr, .dynsym and .dynamic only, which
    is all dynamic_symbol_names and dynamic_needed read."""
    strings = bytearray(b'\0')

    def string(text):
        at = len(strings)
        strings.extend(text.encode() + b'\0')
        return at

    symbols = bytearray(24)  # the null symbol
    for name, defined in [(n, True) for n in defines] + [(n, False) for n in imports]:
        symbols += struct.pack('<IBBHQQ', string(name), (1 << 4) | 2, 0, 1 if defined else 0, 0x1000, 8)
    dynamic = bytearray()
    for name in needed:
        dynamic += struct.pack('<qQ', 1, string(name))
    if soname:
        dynamic += struct.pack('<qQ', 14, string(soname))
    dynamic += struct.pack('<qQ', 0, 0)
    header_size = 64
    dynstr_at = header_size
    dynsym_at = dynstr_at + len(strings)
    dynamic_at = dynsym_at + len(symbols)
    sections_at = dynamic_at + len(dynamic)

    def section(kind, offset, size, link):
        return struct.pack('<IIQQQQIIQQ', 0, kind, 0, 0, offset, size, link, 0, 8, 0)

    sections = (section(0, 0, 0, 0) + section(3, dynstr_at, len(strings), 0)
                + section(11, dynsym_at, len(symbols), 1) + section(6, dynamic_at, len(dynamic), 1))
    ident = b'\x7fELF' + bytes([2, 1, 1]) + bytes(9)
    header = ident + struct.pack('<HHIQQQIHHHHHH', 3, 183, 1, 0, 0, sections_at, 0, 64, 56, 0, 64, 4, 1)
    return bytes(header + strings + symbols + dynamic + sections)


class BindOwnTest(unittest.TestCase):
    def setUp(self):
        probe_source_app._board_exports = {b'deflateReset', b'SSL_new', b'CRYPTO_malloc'}

    def tearDown(self):
        probe_source_app._board_exports = None

    def test_needed_and_soname_are_read(self):
        data = elf('libgame.so', needed=['libc.so', 'libm.so'])
        self.assertEqual(probe_source_app.dynamic_needed(data), (b'libgame.so', {b'libc.so', b'libm.so'}))

    def test_an_importer_that_cannot_reach_the_definer_does_not_share(self):
        """Billiards Hero: libMyGame bundles zlib; Crashlytics takes zlib from the system's libz.so."""
        libraries = {'libMyGame.so': elf('libMyGame.so', needed=['libc.so'], defines=['deflateReset']),
                     'libcrashlytics-common.so': elf('libcrashlytics-common.so', needed=['libz.so'],
                                                     imports=['deflateReset'])}
        self.assertIn('libMyGame.so', probe_source_app.libraries_bound_locally(libraries))

    def test_a_split_library_still_shares(self):
        """OpenSSL over two libraries: libssl needs libcrypto and takes its names from it."""
        libraries = {'libcrypto.so': elf('libcrypto.so', defines=['CRYPTO_malloc']),
                     'libssl.so': elf('libssl.so', needed=['libcrypto.so'], defines=['SSL_new'],
                                      imports=['CRYPTO_malloc'])}
        chosen = probe_source_app.libraries_bound_locally(libraries)
        self.assertNotIn('libcrypto.so', chosen)
        self.assertNotIn('libssl.so', chosen)

    def test_an_importer_without_a_dynamic_section_reaches_every_library(self):
        """Its imports are readable but not its dependencies: it may bind to any app library."""
        importer = elf('libother.so', imports=['deflateReset'])
        # The .dynamic section header's type, SHT_DYNAMIC (6), becomes SHT_NOTE (7).
        importer = importer.replace(struct.pack('<IIQQ', 0, 6, 0, 0), struct.pack('<IIQQ', 0, 7, 0, 0))
        self.assertIsNone(probe_source_app.dynamic_needed(importer))
        libraries = {'libMyGame.so': elf('libMyGame.so', defines=['deflateReset']), 'libother.so': importer}
        self.assertNotIn('libMyGame.so', probe_source_app.libraries_bound_locally(libraries))


if __name__ == '__main__':
    unittest.main()


class ExecutableExportsTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.directory = Path(tempfile.mkdtemp())
        (self.directory / 'board.txt').write_text('deflateReset\n_ZTISt9exception\n')
        (self.directory / 'executable.txt').write_text(
            '_ZTISt9exception\n_ZTSSt9exception\n_ZN7_JNIEnv9NewObjectEP7_jclassP10_jmethodIDz\n_init\n')
        self.saved = (probe_source_app.BOARD_GLOBAL_EXPORTS, probe_source_app.EXECUTABLE_EXPORTS)
        probe_source_app.BOARD_GLOBAL_EXPORTS = self.directory / 'board.txt'
        probe_source_app.EXECUTABLE_EXPORTS = self.directory / 'executable.txt'
        probe_source_app._board_exports = None

    def tearDown(self):
        probe_source_app.BOARD_GLOBAL_EXPORTS, probe_source_app.EXECUTABLE_EXPORTS = self.saved
        probe_source_app._board_exports = None

    def test_the_executables_type_infos_are_bound_and_its_jni_wrappers_are_not(self):
        names = probe_source_app.board_exports()
        # The board's copy of a C++ runtime name stays the board's; the executable's is bound.
        self.assertIn(b'_ZTISt9exception', names)
        self.assertIn(b'_ZTSSt9exception', names)
        self.assertIn(b'deflateReset', names)
        self.assertNotIn(b'_ZN7_JNIEnv9NewObjectEP7_jclassP10_jmethodIDz', names)
        self.assertNotIn(b'_init', names)

    def test_without_the_executable_list_runtime_names_stay_with_the_board(self):
        probe_source_app.EXECUTABLE_EXPORTS = self.directory / 'absent.txt'
        probe_source_app._board_exports = None
        self.assertNotIn(b'_ZTISt9exception', probe_source_app.board_exports())
