import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import make_managed_bundle  # noqa: E402
from sign_development_host import check_signable  # noqa: E402

HOST_MODULE = {
    'app': {'bundleName': 'org.westlake.playhost', 'minAPIVersion': 12},
    'module': {
        'name': 'entry', 'srcEntry': './ets/entry/EntryStage.ets', 'mainElement': 'EntryAbility',
        'abilities': [{'name': 'EntryAbility', 'srcEntry': './ets/entry/EntryAbility.ets',
                       'metadata': [{'name': 'enable.remove.starting.window', 'value': 'true'},
                                    {'name': 'kept', 'value': 'x'}]}],
        'requestPermissions': [
            {'name': 'ohos.permission.INTERNET', 'usedScene': {'abilities': ['EntryAbility'], 'when': 'always'}},
            {'name': 'ohos.permission.GET_NETWORK_INFO'},
            {'name': 'ohos.permission.MICROPHONE', 'usedScene': {'abilities': ['EntryAbility'], 'when': 'inuse'}},
        ],
    },
}
PACKAGE = 'org.thunderdog.challegram'
ACTIVITY = 'org.thunderdog.challegram.MainActivity'


class ManagedBundleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.host = self.root / 'host'
        self.host.mkdir()
        self.write_host(HOST_MODULE)

    def tearDown(self):
        self.directory.cleanup()

    def write_host(self, module):
        hap = self.host / make_managed_bundle.HAP
        with zipfile.ZipFile(hap, 'w') as archive:
            archive.writestr('module.json', json.dumps(module))
            archive.writestr('ets/modules.abc', b'program')
            archive.writestr('resources.index', b'resources')
        sha = hashlib.sha256(hap.read_bytes()).hexdigest()
        (self.host / 'artifacts.json').write_text(json.dumps(
            {'artifacts': {make_managed_bundle.HAP: {'sha256': sha}}, 'errors': []}))

    def make(self, name='out', package=PACKAGE, activity=ACTIVITY, android_permissions=()):
        out = self.root / name
        report = make_managed_bundle.make_bundle(self.host, out, package, activity, android_permissions)
        with zipfile.ZipFile(out / make_managed_bundle.HAP) as archive:
            files = {n: archive.read(n) for n in archive.namelist()}
        return report, files

    def test_only_module_json_changes(self):
        report, files = self.make()
        self.assertEqual(files['ets/modules.abc'], b'program')
        self.assertEqual(files['resources.index'], b'resources')
        module = json.loads(files['module.json'])
        self.assertEqual(module['app']['bundleName'], PACKAGE)
        entry = module['module']
        self.assertEqual(entry['srcEntry'], PACKAGE + '.MainAbilityStage')
        self.assertEqual(entry['mainElement'], ACTIVITY)
        self.assertEqual(entry['description'], make_managed_bundle.MANAGED_DESCRIPTION)
        ability = entry['abilities'][0]
        self.assertEqual((ability['name'], ability['srcEntry']), (ACTIVITY, PACKAGE + '.MainAbility'))
        self.assertEqual(ability['metadata'], [{'name': 'kept', 'value': 'x'}])
        self.assertEqual([p['name'] for p in entry['requestPermissions']],
                         ['ohos.permission.INTERNET', 'ohos.permission.GET_NETWORK_INFO'])
        self.assertEqual(entry['requestPermissions'][0]['usedScene']['abilities'], [ACTIVITY])
        record = report['managed_bundle']
        self.assertEqual((record['package'], record['activity'], record['changed']),
                         (PACKAGE, ACTIVITY, ['module.json']))
        check_signable(module, report, managed=True)
        with self.assertRaises(ValueError):
            check_signable(module, report)

    def test_user_grant_permissions_follow_the_apk(self):
        module = json.loads(json.dumps(HOST_MODULE))
        module['module']['requestPermissions'] += [
            {'name': 'ohos.permission.CAMERA', 'usedScene': {'abilities': ['EntryAbility'], 'when': 'inuse'}},
            {'name': 'ohos.permission.APPROXIMATELY_LOCATION'},
            {'name': 'ohos.permission.LOCATION'},
        ]
        self.write_host(module)
        _, files = self.make(android_permissions=['android.permission.CAMERA',
                                                  'android.permission.ACCESS_COARSE_LOCATION',
                                                  'android.permission.INTERNET'])
        entry = json.loads(files['module.json'])['module']
        self.assertEqual([p['name'] for p in entry['requestPermissions']],
                         ['ohos.permission.INTERNET', 'ohos.permission.GET_NETWORK_INFO',
                          'ohos.permission.CAMERA', 'ohos.permission.APPROXIMATELY_LOCATION'])
        camera = [p for p in entry['requestPermissions'] if p['name'] == 'ohos.permission.CAMERA'][0]
        self.assertEqual(camera['usedScene']['abilities'], [ACTIVITY])
        _, files = self.make('fine', android_permissions=['android.permission.ACCESS_FINE_LOCATION',
                                                          'android.permission.RECORD_AUDIO'])
        names = [p['name'] for p in json.loads(files['module.json'])['module']['requestPermissions']]
        self.assertEqual(names, ['ohos.permission.INTERNET', 'ohos.permission.GET_NETWORK_INFO',
                                 'ohos.permission.MICROPHONE', 'ohos.permission.APPROXIMATELY_LOCATION',
                                 'ohos.permission.LOCATION'])

    def test_signer_still_refuses_other_bundles(self):
        check_signable(HOST_MODULE, {})
        other = json.loads(json.dumps(HOST_MODULE))
        other['app']['bundleName'] = PACKAGE
        for report in [{}, {'managed_bundle': {'package': 'com.example.other', 'changed': ['module.json']}},
                       {'managed_bundle': {'package': PACKAGE, 'changed': ['module.json', 'ets/modules.abc']}}]:
            with self.assertRaises(ValueError):
                check_signable(other, report, managed=True)

    def test_refused_inputs(self):
        with self.assertRaisesRegex(ValueError, 'bundle name'):
            self.make('a', package='nodots')
        with self.assertRaisesRegex(ValueError, 'activity'):
            self.make('b', activity='MainActivity')
        foreign = json.loads(json.dumps(HOST_MODULE))
        foreign['app']['bundleName'] = 'com.example.app'
        self.write_host(foreign)
        with self.assertRaisesRegex(ValueError, 'Westlake host'):
            self.make('c')
        self.write_host(HOST_MODULE)
        (self.host / 'artifacts.json').write_text(json.dumps(
            {'artifacts': {make_managed_bundle.HAP: {'sha256': '0' * 64}}, 'errors': []}))
        with self.assertRaisesRegex(ValueError, 'build report'):
            self.make('d')
        self.write_host(HOST_MODULE)
        self.make('e')
        with self.assertRaisesRegex(ValueError, 'must be new'):
            self.make('e')


if __name__ == '__main__':
    unittest.main()
