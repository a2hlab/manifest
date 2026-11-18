#!/usr/bin/env python3
"""Exercise the actual transformed AOSP caller guard with controlled Binder identities."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--jdk', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('--out must be new')
    args.out.mkdir(parents=True)
    original = args.source.read_text()
    ports = json.loads((ROOT / 'framework-source-ports.json').read_text())['files']
    transformed = original
    key = 'frameworks-base/core/java/android/content/AbstractThreadedSyncAdapter.java'
    for before, after in ports[key].items():
        if transformed.count(before) != 1:
            raise ValueError('AOSP source guard changed')
        transformed = transformed.replace(before, after)
    def guard(text):
        start = text.index('        private boolean isCallerSystem() {')
        end = text.index('\n        @Override', start)
        return text[start:end].strip()
    wrapper = '''
public final class GuardCheck {
 static class Binder { static int uid, pid; static int getCallingUid(){return uid;} static int getCallingPid(){return pid;} }
 static class Process { static final int SYSTEM_UID=1000; static int myUid(){return 20010060;} static int myPid(){return 4321;} }
 @@GUARD@@
 public static void main(String[] args) {
  boolean enabled="1".equals(System.getenv("WESTLAKE_LOCAL_SYNC"));
  int[][] peers={{1000,9876},{20010060,4321},{20010060,9876},{20010061,4321},{20010061,9876},{0,4321},{-1,4321}};
  boolean[] expected={true,enabled,false,false,false,false,false};
  GuardCheck test=new GuardCheck();
  for(int i=0;i<peers.length;i++) { Binder.uid=peers[i][0]; Binder.pid=peers[i][1];
   if(test.isCallerSystem()!=expected[i]) throw new AssertionError("caller case "+i); }
  System.out.println("SYNC_ADAPTER_CALLER_GUARD_PASS "+peers.length);
 }
}
'''
    stub = args.out / 'EventLog.java'
    stub.write_text('package android.util; public final class EventLog { public static void writeEvent(int tag, String issue, int uid, String text) {} }\n')
    count = 0
    for label, source in [('fixed', transformed), ('old', original)]:
        out = args.out / label
        out.mkdir()
        java = out / 'GuardCheck.java'
        java.write_text(wrapper.replace('@@GUARD@@', guard(source)))
        subprocess.run([str(args.jdk / 'bin/javac'), '-d', str(out), str(stub), str(java)], check=True)
        for value in [None, '0', 'true', '1']:
            env = dict(os.environ)
            env.pop('WESTLAKE_LOCAL_SYNC', None)
            if value is not None:
                env['WESTLAKE_LOCAL_SYNC'] = value
            result = subprocess.run([str(args.jdk / 'bin/java'), '-cp', str(out), 'GuardCheck'], env=env, capture_output=True, text=True)
            if label == 'old' and value == '1':
                if result.returncode == 0 or 'caller case 1' not in result.stderr:
                    raise AssertionError('Old-source control did not fail the same-process case')
            else:
                if result.returncode:
                    raise AssertionError(result.stderr)
                if label == 'fixed':
                    count += 7
    print('SYNC_ADAPTER_SOURCE_PORT_PASS', count, 'old source refuses the opt-in same-process case')

if __name__ == '__main__':
    main()
