"""Start a prepared Chaos variant with its own state directory; no native window."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--human-port',type=int,default=3141)
    args=parser.parse_args();build=args.build.resolve()
    if not (build/'dist/intent-repair.json').is_file():raise ValueError('Not a prepared repaired build')
    # fingerprint_server uses integer /proc/stat btime, a conservative start
    # estimate up to one second early. Do not launch in a file-write boundary.
    latest=max(p.stat().st_mtime for p in [build/'package.json', *(build/'dist').rglob('*')] if p.is_file())
    time.sleep(max(0, latest+1.1-time.time()))
    state=build/'state';state.mkdir(exist_ok=True)
    pid_file=build/'server.pid'
    if pid_file.exists() and Path('/proc',pid_file.read_text().strip(),'cmdline').exists():
        command=Path('/proc',pid_file.read_text().strip(),'cmdline').read_bytes()
        if str(build/'dist/cli.mjs').encode() in command:raise ValueError('This build is already running')
    env={**os.environ,'XDG_STATE_HOME':str(state)}
    with (build/'server.log').open('w') as log:
        process=subprocess.Popen(['node',str(build/'dist/cli.mjs'),'--port',str(args.human_port),'--no-open'],
                                 stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
    pid_file.write_text(str(process.pid))
    for _ in range(100):
        if process.poll() is not None:raise RuntimeError('Server exited; inspect '+str(build/'server.log'))
        match=re.search(r'http://localhost:(\d+)/start', (build/'server.log').read_text())
        if match:
            record={'pid':process.pid,'agent_url':'http://localhost:'+match[1],
                    'human_url':'http://localhost:'+str(args.human_port),'state_home':str(state),'build':str(build)}
            (build/'server.json').write_text(json.dumps(record,indent=2));print(json.dumps(record));return
        time.sleep(.1)
    process.terminate();raise TimeoutError('Server startup timed out')

if __name__=='__main__':main()
