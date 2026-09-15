"""Export a finished BrowserGym trace to a portable, read-only replay bundle.

Reuses common_agent_util's BrowserGym projection and viewer. index.html works
without a server or network; original trace bytes, session.json and an asset
map also support an authenticated website viewer. This does not re-execute the
browser, call a model or recompute grades. Existing output paths are rejected.
"""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
from string import Template
from urllib.parse import unquote
import zipfile

ROOT=Path(__file__).resolve().parents[2]
UTILITY=ROOT.parent/'common_agent_util'
sys.path.insert(0,str(UTILITY))
from agent_trace.adapters import browsergym


def digest(data):return hashlib.sha256(data).hexdigest()

def js_json(value):
    # Untrusted page/model text must not terminate an HTML script element.
    return json.dumps(value,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')


def exclusive(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(data)


def export(directory,output,max_bytes=64*1024*1024):
    directory=directory.resolve()
    if output.exists() or output.is_symlink():raise ValueError('Choose a new output directory')
    if not directory.is_dir():raise ValueError('Episode directory missing')
    files={}
    total=0
    for p in sorted(directory.rglob('*')):
        if p.is_symlink():raise ValueError('Trace symlinks are not portable evidence')
        if p.is_file():
            total+=p.stat().st_size
            if total>max_bytes:raise ValueError('Trace exceeds explicit export size cap')
            files[p.relative_to(directory).as_posix()]=p.read_bytes()
    episode=json.loads(files['episode.json']);metadata=json.loads(files['metadata.json'])
    events=[json.loads(l) for l in files['events.jsonl'].decode().splitlines()]
    if not any(e.get('event')=='episode_finished' for e in events):raise ValueError('Only finished saved episodes can be exported')
    if metadata.get('episode_id')!=directory.name:raise ValueError('Episode identity mismatch')
    session=browsergym.project(directory)
    if not session:raise ValueError('Not a BrowserGym trace')
    assets={};embedded={}
    for message in session['messages']:
        for attachment in message.get('attachments',[]):
            url=attachment['url']
            if not url.startswith('/artifacts/'):raise ValueError('Unexpected projection asset URL')
            relative=unquote(url.removeprefix('/artifacts/'))
            path,mime=browsergym.asset(directory.parent,relative)
            name=path.relative_to(directory).as_posix()
            raw=files[name]
            assets[url]={'path':'original/'+directory.name+'/'+name,'mime_type':mime,'sha256':digest(raw),'bytes':len(raw)}
            embedded[url]='data:'+mime+';base64,'+base64.b64encode(raw).decode()
    original_hashes={name:digest(raw) for name,raw in files.items()}
    viewer_path=UTILITY/'agent_trace/session_viewer.html';viewer=viewer_path.read_text()
    bootstrap=Template('''<script>
'use strict';
const offlineSession=$session;
const offlineAssetURLs=new Map(Object.entries($assets));
window.fetch=async function(input){
 const url=new URL(String(input),'https://offline.invalid');
 if(url.pathname==='/api/sessions'){
  const {messages,...summary}=offlineSession;
  return new Response(JSON.stringify([{...summary,revision:'immutable-offline'}]),{headers:{'Content-Type':'application/json'}});
 }
 if(url.pathname==='/api/sessions/'+offlineSession.id)return new Response(JSON.stringify(offlineSession),{headers:{'Content-Type':'application/json'}});
 throw new Error('Network disabled in saved-run replay');
};
</script>''').substitute(session=js_json(session), assets=js_json(embedded))
    replacements={
        "if(!asset.url.startsWith('/artifacts/'))continue;":"if(!offlineAssetURLs.has(asset.url))continue;",
        'a.href=asset.url;':"a.href=offlineAssetURLs.get(asset.url);a.download=asset.url.split('/').pop();",
        'img.src=asset.url;':'img.src=offlineAssetURLs.get(asset.url);',
        '<h1>Agent / Session traces</h1>':'<h1>Saved browser run · offline replay</h1>',
        "s.message_count+' events · '+s.decision_count+' decisions'":"s.message_count+' recorded events'",
        '<button id="decisions-only" aria-pressed="false" aria-controls="chat">Decisions only</button>':'<button id="decisions-only" aria-pressed="false" aria-controls="chat">Browser actions only</button>',
        '<option value="decision">Decisions only</option>':'<option value="tool">Browser actions only</option>',
        "el('filter').value=el('filter').value==='decision'?'all':'decision'":"el('filter').value=el('filter').value==='tool'?'all':'tool'",
        "String(filter==='decision')":"String(filter==='tool')",
        'aria-label="Jump to game turn"':'aria-label="Jump to recorded browser step"',
        '<span class="decision">Action + reason</span>':'<span class="tool">Browser actions</span>',
        '<select id="parser" aria-label="Parsing mode">':'<select id="parser" aria-label="Parsing mode" disabled>',

        'Prompts, decisions and execution · local workspace':'Read-only recorded evidence · no browser or model execution',
        'type="checkbox" checked> Live refresh':'type="checkbox" disabled> Frozen replay',
        "el('connection').textContent='Connected · checked '":"el('connection').textContent='Offline replay · loaded '",
    }
    for before,after in replacements.items():
        if viewer.count(before)!=1:raise ValueError('Viewer integration anchor changed: '+before)
        viewer=viewer.replace(before,after)
    # The existing viewer safely creates DOM nodes with textContent. The only
    # data interpolation is JSON escaped against closing-script injection.
    viewer=viewer.replace('<script>',bootstrap+'\n<script>',1)
    # Distinguish replay of saved observation sequence from live execution.
    viewer=viewer.replace('<meta charset="utf-8">','<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; media-src data:; connect-src \'none\'; base-uri \'none\'; form-action \'none\'">',1)
    payloads={'session.json':(json.dumps(session,indent=2)+'\n').encode(),
              'assets.json':(json.dumps(assets,indent=2)+'\n').encode(),
              'index.html':viewer.encode()}
    for name,raw in files.items():payloads['original/'+directory.name+'/'+name]=raw
    manifest={'schema_version':1,'kind':'browsergym-saved-replay-v1','created_at':datetime.now(timezone.utc).isoformat(),
        'episode_id':directory.name,'viewer_session_id':session['id'],'source_episode':str(directory),
        'read_only':True,'new_model_calls':0,'new_browser_actions':0,'grader_recomputed':False,
        'raw_outcomes':json.loads(files['evaluation.json']),
        'source_trace_sha256':original_hashes,
        'projection':{'implementation':'common_agent_util.agent_trace.adapters.browsergym.project',
                      'module_sha256':digest((UTILITY/'agent_trace/adapters/browsergym.py').read_bytes()),
                      'trace_reader_sha256':digest((UTILITY/'agent_trace/trace.py').read_bytes()),
                      'original_viewer_sha256':digest(viewer_path.read_bytes()),
                      'exporter_sha256':digest(Path(__file__).read_bytes()),
                      'viewer_delta':'Static data fetch bridge; embedded recorded assets; no network; frozen status labels; BrowserGym action-only filter and event count (original projection unchanged).'},
        'files':{name:{'sha256':digest(raw),'bytes':len(raw)} for name,raw in payloads.items()},
        'website_integration':'Consume session.json + assets.json; resolve asset IDs through authenticated routes. Original trace is privileged review evidence, not policy input.',
        'limitations':['Saved replay cannot change an action or test an alternative outcome.',
                      'Missing historical fields and null outcomes are preserved, never inferred.',
                      'Original requests/responses and privileged verification are included; use existing invitation-scoped access on the website.']}
    payloads['manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    payloads['README.txt']=('Open index.html in a browser to inspect this saved run offline.\n'
        'This does not run the agent, replay actions against a website, or recompute verification.\n'
        'session.json is the common_agent_util projection. assets.json maps its attachment URLs to originals.\n'
        'manifest.json records original hashes and exact projection/exporter provenance.\n'
        'Original trace files and unknown outcomes are retained. Website serving must enforce per-invitation access.\n').encode()
    # Refuse racing writes in the source before publishing a portable snapshot.
    for name,h in original_hashes.items():
        if digest((directory/name).read_bytes())!=h:raise ValueError('Source changed during export')
    output.mkdir(parents=True,exist_ok=False)
    for name,raw in payloads.items():exclusive(output/name,raw)
    with zipfile.ZipFile(output/'replay.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in payloads.items():archive.writestr(name,raw)
    result={'output':str(output),'episode':directory.name,'source_files':len(files),'source_bytes':total,
            'projection_events':len(session['messages']),'attachments':len(assets),'zip_bytes':(output/'replay.zip').stat().st_size,
            'manifest_sha256':digest(payloads['manifest.json'])}
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('episode',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-mb',type=int,default=64);a=p.parse_args()
    if a.max_mb<1:p.error('Positive size cap required')
    export(a.episode,a.output,a.max_mb*1024*1024)
