#!/usr/bin/env python3
"""Make an APK's own OH bundle for an ADR-0008 managed launch, from the source Westlake host HAP.

The bundle keeps the host's program and resources unchanged; only module.json changes:
- The bundle name is the Android package, so OH installs the app under its own uid, data and token.
- The entry module's srcEntry is a dotted class name: <package>.MainAbilityStage, and
  <package>.MainAbility for the ability. OH 6.1's application manager treats such an entry as
  Cangjie (AppMgrServiceInner's IsCjApplication) and asks the CJAppSpawn spawner for the process.
  The launcher's spawn router (appspawn-x --route) serves that socket and passes the request to the
  app's own appspawn-x.
- The ability is named after the app's launcher activity, which the launcher starts with aa. A
  manifest may name it relative to the package (".ui.Main", or "Main" without a dot); like
  Android and probe_source_app.py, the name is resolved against the package first.
- The ability drops the enable.remove.starting.window metadata. With it, SceneBoard would also wait
  up to 5 s for the app to remove the starting window. It goes at the app's first frame anyway.
- Only the network permissions stay requested (INTERNET, GET_NETWORK_INFO). A development-signed
  bundle gets no restricted ACLs, and Android permissions are not mapped to OH ones yet (ADR-0004).
- --orientation gives the ability the launcher activity's android:screenOrientation in OH's terms,
  so SceneBoard turns the screen before the app's window is made: a landscape game gets a landscape
  window (2280x1080 on the OnePlus 6) instead of drawing a landscape layout into a portrait one
  (Hungry Shark Evolution's terms dialog ran off both sides of the screen).

The output directory holds imehost-unsigned.hap and artifacts.json. sign_development_host.py signs
them with --managed.
"""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

MANAGED_DESCRIPTION = 'Westlake managed launch (ADR-0008)'
NETWORK_PERMISSIONS = ('ohos.permission.INTERNET', 'ohos.permission.GET_NETWORK_INFO')
HAP = 'imehost-unsigned.hap'
# Android's ActivityInfo.screenOrientation values (and their manifest names) -> OH's ability
# orientation. UNSPECIFIED (-1) and NOSENSOR (5) leave the system's choice: no field.
ORIENTATIONS = {
    0: 'landscape',                                 # landscape
    1: 'portrait',                                  # portrait
    2: 'auto_rotation_restricted',                  # user
    3: 'follow_recent',                             # behind
    4: 'auto_rotation',                             # sensor
    6: 'auto_rotation_landscape',                   # sensorLandscape
    7: 'auto_rotation_portrait',                    # sensorPortrait
    8: 'landscape_inverted',                        # reverseLandscape
    9: 'portrait_inverted',                         # reversePortrait
    10: 'auto_rotation',                            # fullSensor
    11: 'auto_rotation_landscape_restricted',       # userLandscape
    12: 'auto_rotation_portrait_restricted',        # userPortrait
    13: 'auto_rotation_restricted',                 # fullUser
    14: 'locked',                                   # locked
}
ORIENTATION_NAMES = {
    'unspecified': -1, 'landscape': 0, 'portrait': 1, 'user': 2, 'behind': 3, 'sensor': 4, 'nosensor': 5,
    'sensorLandscape': 6, 'sensorPortrait': 7, 'reverseLandscape': 8, 'reversePortrait': 9, 'fullSensor': 10,
    'userLandscape': 11, 'userPortrait': 12, 'fullUser': 13, 'locked': 14,
}
# OH bundle names: 7 to 128 characters, a letter first, at least one dot. Android package names are
# stricter, so every Android package fits.
BUNDLE_NAME = re.compile(r'[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+')
CLASS_NAME = re.compile(r'[a-zA-Z_][a-zA-Z0-9_$]*(\.[a-zA-Z_][a-zA-Z0-9_$]*)+')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def class_name(package, name):
    """An activity name as Android resolves it (PackageParser.buildClassName): relative to the package
    when it starts with a dot or has no dot at all."""
    if name.startswith('.'):
        return package + name
    if '.' not in name:
        return package + '.' + name
    return name


def oh_orientation(orientation):
    """OH's ability orientation for an Android screenOrientation (its number or manifest name), or None."""
    if orientation is None or orientation == '':
        return None
    value = ORIENTATION_NAMES.get(orientation)
    if value is None:
        try:
            value = int(orientation)
        except ValueError:
            raise ValueError('Not an Android screenOrientation: ' + str(orientation)) from None
    if value not in ORIENTATIONS and value not in (-1, 5):
        raise ValueError('Not an Android screenOrientation: ' + str(orientation))
    return ORIENTATIONS.get(value)


def managed_module(module, package, activity, orientation=None):
    """The host HAP's module.json, changed into the app's own managed bundle."""
    if not BUNDLE_NAME.fullmatch(package) or not 7 <= len(package) <= 128:
        raise ValueError('Not an OH bundle name: ' + package)
    activity = class_name(package, activity)
    if not CLASS_NAME.fullmatch(activity) or len(activity) > 127:
        raise ValueError('Not an activity class name usable as an OH ability name: ' + activity)
    if not module['app']['bundleName'].startswith('org.westlake.'):
        raise ValueError('Only a source Westlake host HAP can become a managed bundle')
    result = json.loads(json.dumps(module))
    result['app']['bundleName'] = package
    entry = result['module']
    abilities = entry.get('abilities', [])
    if len(abilities) != 1:
        raise ValueError('The host HAP must declare exactly one ability, not ' + str(len(abilities)))
    ability = abilities[0]
    entry['srcEntry'] = package + '.MainAbilityStage'
    entry['description'] = MANAGED_DESCRIPTION
    ability['srcEntry'] = package + '.MainAbility'
    metadata = [m for m in ability.get('metadata', []) if m.get('name') != 'enable.remove.starting.window']
    if metadata:
        ability['metadata'] = metadata
    else:
        ability.pop('metadata', None)
    old_name, ability['name'] = ability['name'], activity
    oh = oh_orientation(orientation)
    if oh is not None:
        ability['orientation'] = oh
    entry['mainElement'] = activity
    permissions = [p for p in entry.get('requestPermissions', []) if p['name'] in NETWORK_PERMISSIONS]
    for permission in permissions:
        used = permission.get('usedScene', {}).get('abilities')
        if used:
            permission['usedScene']['abilities'] = [activity if name == old_name else name for name in used]
    entry['requestPermissions'] = permissions
    return result


def make_bundle(host_build, out, package, activity, orientation=None):
    host_build, out = Path(host_build), Path(out)
    if out.exists():
        raise ValueError('--out must be new')
    report = json.loads((host_build / 'artifacts.json').read_text())
    source = host_build / HAP
    if report.get('errors') or digest(source) != report['artifacts'][HAP]['sha256']:
        raise ValueError('Source host HAP differs from its build report')
    out.mkdir(parents=True)
    activity = class_name(package, activity)
    hap = out / HAP
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(hap, 'w') as bundle:
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename == 'module.json':
                data = json.dumps(managed_module(json.loads(data), package, activity, orientation),
                                  indent=4).encode()
            bundle.writestr(info, data)
    record = {'artifacts': {HAP: {'sha256': digest(hap)}}, 'errors': [],
              'managed_bundle': {'package': package, 'activity': activity, 'changed': ['module.json'],
                                 'orientation': oh_orientation(orientation),
                                 'source_host_hap_sha256': digest(source),
                                 'source_host_build_sha256': digest(host_build / 'artifacts.json')}}
    (out / 'artifacts.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host-build', type=Path, required=True,
                        help='a source Westlake host build: imehost-unsigned.hap and its artifacts.json')
    parser.add_argument('--package', required=True, help="the Android package, the bundle's name")
    parser.add_argument('--activity', required=True, help="the app's launcher activity class, its ability name")
    parser.add_argument('--out', type=Path, required=True, help='a new directory')
    parser.add_argument('--orientation',
                        help="the launcher activity's android:screenOrientation: its number or manifest name")
    args = parser.parse_args()
    record = make_bundle(args.host_build, args.out, args.package, args.activity, args.orientation)
    print('MANAGED_BUNDLE', args.package, record['artifacts'][HAP]['sha256'])


if __name__ == '__main__':
    main()
