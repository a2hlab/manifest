#!/usr/bin/env python3
"""Capture an isolated source app's logs and mappings, or stop that exact build."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
from bootstrap_sdk import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--hdc', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--view-tree', action='store_true')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists():
        parser.error('--out must be new')
    state = json.loads(args.report.read_text())
    runtime = state['runtime']
    if not re.fullmatch(r'/data/app/el2/100/base/[\w.]+/files/a2hlab-source-[a-f0-9]{32}', runtime):
        raise ValueError('Not an isolated source app runtime')
    if not re.fullmatch(r'/data/local/tmp/a2hlab-app-[a-f0-9]{32}', state['stage']):
        raise ValueError('Invalid probe stage')
    output.mkdir(parents=True)
    transport = [args.hdc, '-t', args.serial]

    def shell(command):
        result = subprocess.run(transport + ['shell', 'sh -c ' + shlex.quote(command) +
                                '; a2h_rc=$?; printf "\\n__A2H_RC__%s\\n" "$a2h_rc"'],
                                capture_output=True, timeout=30)
        text = (result.stdout + result.stderr).decode(errors='replace').replace('\r', '')
        marker = re.search(r'\n__A2H_RC__(\d+)\n?$', text)
        if result.returncode or not marker or int(marker[1]):
            raise RuntimeError(text)
        return text[:marker.start()]

    if args.serial not in subprocess.check_output([args.hdc, 'list', 'targets'], text=True).split():
        raise ValueError('Device disconnected')
    if shell('uname -m').strip() != 'aarch64':
        raise ValueError('Wrong device architecture')
    expected_inode = shell('stat -c "%d:%i" ' + runtime + '/appspawn-x').strip()
    result = {'spawn_report_sha256': digest(args.report), 'processes': {}, 'stopped': [],
              'full_source_ui_accepted': False}
    for role in ['parent', 'child']:
        pid = state[role]
        if not isinstance(pid, int) or pid < 2:
            continue
        live = shell(f'if [ -d /proc/{pid} ]; then echo LIVE; fi').strip() == 'LIVE'
        result['processes'][role] = {'pid': pid, 'alive': live}
        if not live:
            continue
        actual_inode = shell(f'stat -Lc "%d:%i" /proc/{pid}/exe').strip()
        if actual_inode != expected_inode:
            raise ValueError('PID now belongs to a different executable')
        status = shell(f'cat /proc/{pid}/status')
        if role == 'child' and int(re.search(r'^Uid:\s+(\d+)', status, re.M)[1]) != state['uid']:
            raise ValueError('Child ownership differs')
        (output / (role + '-status.txt')).write_text(status)
        (output / (role + '-maps.txt')).write_text(shell(f'cat /proc/{pid}/maps'))
        result['processes'][role]['executable_inode'] = actual_inode
    child = state.get('child')
    if child:
        log = f'/data/service/el1/public/appspawnx/adapter_child_{child}.stderr'
        if args.view_tree and result['processes'].get('child', {}).get('alive'):
            box = f'/proc/{child}/root/data/local/tmp/noice_tap.{child}'
            offset = int(shell('wc -c < ' + log).strip()) + 1
            tree = ''
            try:
                shell('touch ' + box + ' && chown ' + str(state['uid']) + ':' + str(state['uid']) +
                      ' ' + box + ' && chmod 600 ' + box + ' && echo v > ' + box)
                for _ in range(20):
                    # Filter on-device so unrelated service retries cannot
                    # swamp the transport and hide the structural response.
                    tree = shell(f'tail -c +{offset} {log} | grep -aE ' + shlex.quote(
                        'VT |dumpViewTree:') + ' || true')
                    if 'VT ==== end ====' in tree:
                        break
                    time.sleep(0.25)
            except RuntimeError as error:
                # A dying child can lose its namespace after the identity
                # check. Keep its startup/crash log even if this probe fails.
                result['view_tree_error'] = str(error)
            (output / 'view-tree.txt').write_text(tree)
            result['view_tree_complete'] = 'VT ==== end ====' in tree
            result['decor_view'] = bool(re.search(r'\bVT [^\n]*DecorView[^\n]* rect=\[', tree))
        for label, command in [('child-head.log', 'head -n 1500 ' + log),
                               ('child-tail.log', 'tail -n 1500 ' + log)]:
            (output / label).write_text(shell('if [ -f ' + log + ' ]; then ' + command + '; fi'))
        # Repeated service retries can hide the startup failure between head
        # and tail. Preserve matching lines from the whole log as well.
        events = shell('if [ -f ' + log + ' ]; then grep -E ' + shlex.quote(
            'SOURCE-|UNCAUGHT|THROWABLE|handleBindApplication|doLaunchActivity|'
            'Exception|FATAL|signal [0-9]|symbol not found') + ' ' + log + ' || true; fi')
        (output / 'child-events.log').write_text(events)
    (output / 'parent.log').write_text(shell('tail -n 200 ' + state['stage'] + '/parent.log'))
    if args.stop:
        for role in ['child', 'parent']:
            entry = result['processes'].get(role, {})
            if not entry.get('alive'):
                continue
            pid = entry['pid']
            # Recheck immediately before signaling to reject PID reuse.
            if shell(f'stat -Lc "%d:%i" /proc/{pid}/exe').strip() != expected_inode:
                raise ValueError('PID changed before stop')
            shell(f'kill -TERM {pid}')
            result['stopped'].append(pid)
    result['artifacts'] = {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()}
    (output / 'inspection.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
