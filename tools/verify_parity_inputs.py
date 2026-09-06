#!/usr/bin/env python3
"""Check operator-supplied immutable reference inputs against their recorded hashes."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def verify(root,lock,categories):
    root=root.resolve()
    missing=[];different=[];verified=[]
    for entry in lock['files']:
        if entry['category'] not in categories:continue
        path=(root/entry['path'].lstrip('/')).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Input path escapes the supplied root: '+entry['path'])
        if not path.is_file():missing.append(entry['path']);continue
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=entry['sha256']:different.append(entry['path'])
        else:verified.append(entry['path'])
    if not (verified or missing or different):raise ValueError('No inputs selected')
    return dict(input_hashes_match=not missing and not different,verified_count=len(verified),
                missing=missing,different=different,complete_source_build=False,
                device_accepted=False,scope='Observed immutable runtime input identity only')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='Local tree mirroring absolute device paths')
    parser.add_argument('--lock',type=Path,default=ROOT/'parity27-runtime-inputs.lock.json')
    parser.add_argument('--category',action='append',choices=['firmware','application','webview','bridge-runtime'])
    args=parser.parse_args()
    result=verify(args.root,json.loads(args.lock.read_text()),args.category or ['firmware','application','webview','bridge-runtime'])
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['input_hashes_match'] else 1)
