"""Local screenshot viewer. Serves only browser screenshots and basic status.

The viewer never navigates the controlled browser, exposes verifier state, or
opens/focuses a desktop window. It can remain open between episodes.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


HTML = b'''<!doctype html><meta charset="utf-8"><title>Browser agent live view</title>
<style>body{margin:24px;background:#121820;color:#e7edf4;font:16px/1.5 system-ui}
header{display:flex;align-items:center;gap:24px;flex-wrap:wrap}h1{font-size:22px}
img{display:block;max-width:100%;margin-top:16px;background:white;border:1px solid #405064}
p{color:#b7c6d9}button{font:inherit;padding:5px 12px}#error{color:#ffce91}</style>
<header><h1>Browser agent live view</h1><button id="pause">Pause updates</button></header>
<p>Latest saved browser observation. Updates after each step; this view does not control the agent.</p>
<div id="status">Waiting for a browser episode...</div><div id="error"></div>
<img id="screen" hidden alt="Latest browser screenshot">
<script>
let paused=false,last='';const button=document.getElementById('pause');
button.onclick=()=>{paused=!paused;button.textContent=paused?'Resume updates':'Pause updates'};
async function tick(){if(paused)return;try{
 const response=await fetch('/state',{cache:'no-store'});if(!response.ok)throw Error('Viewer unavailable');
 const s=await response.json();document.getElementById('error').textContent='';
 if(!s.image){document.getElementById('status').textContent='Waiting for a browser episode...';return}
 document.getElementById('status').textContent=s.episode+' | observation '+s.step+' | '+s.status;
if(last!==s.image){const img=document.getElementById('screen');img.onerror=()=>{last=''};img.src=s.image;img.hidden=false;last=s.image}
}catch(e){document.getElementById('error').textContent='Viewer disconnected; retrying...'}}
setInterval(tick,1000);tick();
</script>'''


def latest_state(root):
    # Epoch-named episode folders sort by creation time. Ignore search-only
    # episodes and sessions, which have no browser screenshot.
    for directory in sorted(root.glob('????????T??????Z-*'), reverse=True):
        images = sorted(directory.glob('observation-*.png'))
        if not images:
            continue
        image = images[-1]
        status = 'running (or interrupted before final logging)'
        summary = directory / 'episode.json'
        if summary.is_file():
            status = json.loads(summary.read_text()).get('stop_reason', 'finished')
        return {'episode': directory.name, 'step': int(image.stem.rsplit('-', 1)[1]),
                'status': status, 'image': '/image/' + directory.name + '/' + image.name}
    return {'image': None}


def serve(root, port):
    root = root.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/':
                data, mime = HTML, 'text/html; charset=utf-8'
            elif path == '/health':
                data, mime = json.dumps({'service': 'intent-browser-preview', 'root': str(root)}).encode(), 'application/json'
            elif path == '/state':
                data, mime = json.dumps(latest_state(root)).encode(), 'application/json'
            elif re.fullmatch(r'/image/\d{8}T\d{6}Z-[a-f0-9]+/observation-\d+\.png', path):
                file = (root / path.removeprefix('/image/')).resolve()
                if not file.is_relative_to(root) or not file.is_file():
                    self.send_error(404)
                    return
                data, mime = file.read_bytes(), 'image/png'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


def ensure_preview(root, port=8877):
    """Reuse or start a persistent loopback-only viewer without opening a tab."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    url = f'http://localhost:{port}'

    def healthy():
        try:
            with urlopen(f'http://127.0.0.1:{port}/health', timeout=0.3) as response:
                data = json.load(response)
            if data != {'service': 'intent-browser-preview', 'root': str(root)}:
                raise ValueError('Preview port belongs to another service or output directory')
            return True
        except OSError:
            return False

    if not healthy():
        with (root / '.preview-server.log').open('a') as log:
            process = subprocess.Popen([sys.executable, '-m', 'intent_browser.preview', '--output', str(root),
                                        '--port', str(port)], stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, start_new_session=True)
        for _ in range(30):
            if healthy():
                break
            if process.poll() is not None:
                raise RuntimeError('Preview server could not start; see runs/.preview-server.log')
            time.sleep(0.1)
        else:
            process.terminate()
            raise RuntimeError('Preview server startup timed out')
    return url


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('runs'))
    parser.add_argument('--port', type=int, default=8877)
    args = parser.parse_args()
    serve(args.output, args.port)
