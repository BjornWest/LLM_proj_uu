"""Verify pinned resource cache; --fetch explicitly restores missing files.

Preparation only. Neither package export nor environment startup uses networking.
"""
import argparse
import hashlib
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache',type=Path,default=ROOT/'.research/environment-fonts-v1')
    p.add_argument('--fetch',action='store_true')
    args=p.parse_args()
    rows=json.loads((ROOT/'environments/portable-resources/inter.json').read_text())['resources']
    fetched=0
    for url,row in rows.items():
        path=args.cache/row['file']
        if path.is_symlink():raise ValueError('Cache symlink rejected')
        if not path.exists():
            if not args.fetch:raise FileNotFoundError('Missing resource; explicitly run --fetch during preparation')
            with httpx.stream('GET',url,timeout=30,trust_env=False) as response:
                response.raise_for_status();raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>row['bytes']:raise ValueError('Upstream resource exceeded pinned size')
            if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Upstream resource changed; refusing silent update')
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as out:out.write(raw)
            fetched+=1
        if path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Existing cache differs from pinned resource')
    print(json.dumps({'verified':len(rows),'downloaded_files':fetched,'bytes':sum(r['bytes'] for r in rows.values())}))


if __name__=='__main__':main()
