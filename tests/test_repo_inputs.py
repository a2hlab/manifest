import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from bootstrap_sdk import digest, fingerprint
from fetch_sources import read_lock, fetch
from install_toolchains import extract_tar, install_package


class RepositoryInputsTests(unittest.TestCase):
    def test_all_active_dependencies_are_org_repositories(self):
        for entry in read_lock(ROOT / 'sources.lock.json'):
            self.assertRegex(entry['url'], r'^https://github\.com/a2hlab/[A-Za-z0-9_.-]+\.git$')
        lock = json.loads((ROOT / 'toolchains.lock.json').read_text())
        self.assertEqual(lock['repository_path'], 'inputs/toolchains')
        for key in ('ohos-sdk', 'platform-clang'):
            self.assertNotIn('url', lock[key])
            self.assertRegex(lock[key]['sha256'], r'^[0-9a-f]{64}$')

    def test_external_fetch_rejected_before_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'checked in under a2hlab'):
                fetch({'path': 'external', 'revision': '0' * 40, 'url': 'https://example.com/repo.git'}, Path(tmp))
            self.assertFalse((Path(tmp) / 'external').exists())

    def make_archive(self, root):
        source = root / 'source'
        (source / 'bin').mkdir(parents=True)
        (source / 'bin/tool').write_bytes(b'compiler fixture')
        (source / 'bin/tool').chmod(0o755)
        (source / 'bin/alias').symlink_to('tool')
        archive = root / 'archive.tar.gz'
        with tarfile.open(archive, 'w:gz') as packed:
            for path in sorted(source.rglob('*')):
                packed.add(path, arcname=str(path.relative_to(source)), recursive=False)
        return archive, {'bytes': archive.stat().st_size, 'sha256': digest(archive),
                         'tree_sha256': fingerprint(source)['sha256']}

    def test_install_is_content_verified_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, lock = self.make_archive(root)
            install_package(archive, root / 'out', lock)
            self.assertEqual(fingerprint(root / 'out')['sha256'], lock['tree_sha256'])
            with self.assertRaisesRegex(ValueError, 'must be new'):
                install_package(archive, root / 'out', lock)

    def test_corrupt_or_pointer_archive_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, lock = self.make_archive(root)
            archive.write_bytes(b'version https://git-lfs.github.com/spec/v1\n')
            with self.assertRaisesRegex(ValueError, 'Missing/corrupt LFS'):
                install_package(archive, root / 'out', lock)
            self.assertFalse((root / 'out').exists())

    def test_wrong_tree_digest_does_not_publish_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, lock = self.make_archive(root)
            lock['tree_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'Extracted toolchain tree'):
                install_package(archive, root / 'out', lock)
            self.assertFalse((root / 'out').exists())

    def test_tar_rejects_escape_devices_hardlinks_and_duplicates(self):
        for kind in ('escape', 'symlink', 'hardlink', 'device', 'duplicate'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive = root / 'bad.tar.gz'
                with tarfile.open(archive, 'w:gz') as packed:
                    item = tarfile.TarInfo('../escape' if kind == 'escape' else 'entry')
                    if kind == 'symlink':
                        item.type, item.linkname = tarfile.SYMTYPE, '../outside'
                    elif kind == 'hardlink':
                        item.type, item.linkname = tarfile.LNKTYPE, 'target'
                    elif kind == 'device':
                        item.type = tarfile.CHRTYPE
                    packed.addfile(item, io.BytesIO())
                    if kind == 'duplicate':
                        packed.addfile(item, io.BytesIO())
                (root / 'out').mkdir()
                with self.assertRaises(ValueError):
                    extract_tar(archive, root / 'out')


if __name__ == '__main__':
    unittest.main()
