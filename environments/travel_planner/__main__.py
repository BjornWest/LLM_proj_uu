"""Host a standalone fixed travel snapshot without privileged authoring routes."""
import argparse
import json
import os
from pathlib import Path
import signal
import threading
from .runtime import Runtime


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scenario',type=Path,required=True)
    p.add_argument('--port',type=int,default=0)
    p.add_argument('--manifest',type=Path)
    args=p.parse_args()
    from environments.product_world.travel import export_travel_planner
    scenario=json.loads(args.scenario.read_text())
    export=export_travel_planner(scenario['bundle'],scenario['locations'])
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    with Runtime(args.port) as runtime:
        url=runtime.register(export)
        result={'pid':os.getpid(),'url':url,'places':len(export['public']['places']),
                'trips':len(export['public']['trips']),'public_sha256':export['public_sha256']}
        if args.manifest:args.manifest.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
        stop.wait()


if __name__=='__main__':main()
