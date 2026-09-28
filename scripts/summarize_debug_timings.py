#!/usr/bin/env python3
"""Summarize existing buffered diagnostics; never starts browser/model work."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics


def summarize(data):
    groups=defaultdict(list)
    for row in data['records']:
        key=row['name']+(' / '+str(row['phase']) if row.get('phase') is not None else '')
        groups[key].append(row['duration_seconds'])
    return sorted([{'span':key,'count':len(values),'total_seconds':sum(values),
                    'median_ms':statistics.median(values)*1000,'max_ms':max(values)*1000}
                   for key,values in groups.items()],key=lambda r:r['total_seconds'],reverse=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('path',type=Path,help='Trace directory or debug-timings.json')
    p.add_argument('--json',action='store_true');args=p.parse_args()
    path=args.path/'debug-timings.json' if args.path.is_dir() else args.path
    data=json.loads(path.read_text());rows=summarize(data)
    if args.json:
        print(json.dumps({'scope':data['scope'],'dropped_records':data['dropped_records'],'spans':rows},indent=2));return
    print('Nested and overlapping spans: totals are NOT additive or an exclusive wall-time breakdown.')
    print(f"Retained {len(data['records'])} records; dropped {data['dropped_records']} at buffer cap.")
    print(f"{'count':>6} {'total s':>10} {'median ms':>10} {'max ms':>10}  span")
    for row in rows:
        print(f"{row['count']:6d} {row['total_seconds']:10.4f} {row['median_ms']:10.3f} {row['max_ms']:10.3f}  {row['span']}")

if __name__=='__main__':main()
