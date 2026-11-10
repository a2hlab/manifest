import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import probe_source_app  # noqa: E402


class NonElfStagingTest(unittest.TestCase):
    NOT_ELF = ['lib/arm64-v8a/libc++.so', 'lib/arm64-v8a/libsgmain.so', 'lib/arm64-v8a/libkernelu4_uc_7z.so']

    def test_only_a_board_librarys_name_is_held_back(self):
        """StarMaker's ld-script libc++.so would shadow the board's libc++.so; SecurityGuard's and UC's
        data files shadow nothing and are staged as Android's installer extracts them."""
        board = {'libc++.so', 'libz.so', 'libOpenSLES.so'}
        self.assertEqual(probe_source_app.non_elf_not_staged(self.NOT_ELF, board), ['lib/arm64-v8a/libc++.so'])

    def test_the_names_are_read_from_the_workspace(self):
        with tempfile.TemporaryDirectory() as workspace:
            self.assertIsNone(probe_source_app.board_library_names(Path(workspace)))
            (Path(workspace) / 'board-library-names.txt').write_text('libc++.so\nlibz.so\n')
            self.assertEqual(probe_source_app.board_library_names(Path(workspace)), {'libc++.so', 'libz.so'})

    def test_without_the_boards_names_none_is_staged(self):
        self.assertEqual(probe_source_app.non_elf_not_staged(self.NOT_ELF, None), self.NOT_ELF)


if __name__ == '__main__':
    unittest.main()
