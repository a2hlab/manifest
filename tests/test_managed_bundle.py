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

    def make(self, name='out', package=PACKAGE, activity=ACTIVITY, orientation=None):
        out = self.root / name
        report = make_managed_bundle.make_bundle(self.host, out, package, activity, orientation)
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
            self.make('b', activity='Main-Activity')
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


    def test_relative_activity_names(self):
        # As Android and probe_source_app.py resolve them: Netflix names its launcher ".ui.launch.UIWebViewActivity".
        for i, (name, full) in enumerate([('.ui.launch.Main', PACKAGE + '.ui.launch.Main'),
                                          ('MainActivity', PACKAGE + '.MainActivity'),
                                          (ACTIVITY, ACTIVITY)]):
            report, files = self.make('rel%d' % i, activity=name)
            entry = json.loads(files['module.json'])['module']
            self.assertEqual((entry['mainElement'], entry['abilities'][0]['name']), (full, full))
            self.assertEqual(entry['requestPermissions'][0]['usedScene']['abilities'], [full])
            self.assertEqual(report['managed_bundle']['activity'], full)

    def test_orientation(self):
        # The launcher activity's android:screenOrientation, by number or manifest name, in OH's terms.
        for i, (android, oh) in enumerate([('11', 'auto_rotation_landscape_restricted'),
                                           ('sensorLandscape', 'auto_rotation_landscape'), ('0', 'landscape'),
                                           ('1', 'portrait'), ('reversePortrait', 'portrait_inverted')]):
            report, files = self.make('o%d' % i, orientation=android)
            module = json.loads(files['module.json'])
            self.assertEqual(module['module']['abilities'][0]['orientation'], oh)
            self.assertEqual(report['managed_bundle']['orientation'], oh)
            check_signable(module, report, managed=True)
        # unspecified, nosensor and none: the system's choice, no field.
        for i, android in enumerate(['-1', 'nosensor', None, '']):
            report, files = self.make('u%d' % i, orientation=android)
            self.assertNotIn('orientation', json.loads(files['module.json'])['module']['abilities'][0])
            self.assertIsNone(report['managed_bundle']['orientation'])
        for android in ['99', 'sideways']:
            with self.assertRaisesRegex(ValueError, 'screenOrientation'):
                self.make('bad-' + android, orientation=android)


if __name__ == '__main__':
    unittest.main()
