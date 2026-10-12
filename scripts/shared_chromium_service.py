"""Finite private Chromium service fenced to its suite owner's process identity."""
import argparse
from pathlib import Path
import signal
import sys
import time


def owner_alive(pid, expected_start):
    try:
        data=(Path('/proc')/str(pid)/'stat').read_text()
        return data[data.rfind(')')+2:].split()[19] == expected_start
    except (FileNotFoundError, ProcessLookupError):
        return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--owner-pid',type=int,required=True)
    parser.add_argument('--owner-start',required=True)
    parser.add_argument('--max-leases',type=int,required=True)
    parser.add_argument('--per-server',type=int,required=True)
    args=parser.parse_args()
    if not owner_alive(args.owner_pid,args.owner_start):raise RuntimeError('Suite owner absent before pool startup')
    sys.path.insert(0,str(args.source_root.resolve()))
    from intent_browser.chromium_pool import PoolSupervisor
    supervisor=PoolSupervisor(args.directory,max_servers=4,max_leases=args.max_leases,per_server=args.per_server)
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    handlers={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP)}
    try:
        supervisor.start()
        print(str(supervisor.descriptor_path),flush=True)
        while supervisor.process.poll() is None and not stopping:
            if not owner_alive(args.owner_pid,args.owner_start):break
            time.sleep(.1)
    finally:
        try:supervisor.close()
        finally:
            for sig,handler in handlers.items():signal.signal(sig,handler)

if __name__=='__main__':main()
