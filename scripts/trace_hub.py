"""Project-local multi-directory catalog using common_agent_util's read-only viewer.

Only configured roots are readable. Original artifacts are never moved or rewritten.
"""
import datetime as dt
from collections import OrderedDict
from collections.abc import Mapping
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit,parse_qs,unquote
from agent_trace.collections import CollectionStore, collection_post, declared_collection, declared_tags, normalize_collection, parent_ids
from scripts.trace_failure_annotations import read_failure_annotations
try:
    from .trace_grades import project_grade, FILENAME
except ImportError:
    from trace_grades import project_grade, FILENAME


def source_key(root):return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]


def started_key(group):
    value=group.get('started_at') or group.get('updated_at')
    try:
        time=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        if time.tzinfo is None:time=time.replace(tzinfo=dt.timezone.utc)
        return time.timestamp()
    except (AttributeError,ValueError,TypeError):return float('-inf')


def media_prefix(value,key):
    if isinstance(value,list):return [media_prefix(v,key) for v in value]
    if isinstance(value,dict):
        return {k:('/artifacts/'+key+'/'+v.removeprefix('/artifacts/')
                   if k=='url' and isinstance(v,str) and v.startswith('/artifacts/') else media_prefix(v,key)) for k,v in value.items()}
    return value


def summary_fields(group):
    """The sidebar does not need per-turn records or message bodies."""
    return {k:v for k,v in group.items() if k not in ('messages','turns','value_ledger')}


def retain_summary_counts(summary, previous):
    """Keep last loaded counters while metadata/revision advances independently."""
    if not previous or previous.get('model_turn_count') is None:
        return summary
    fields = ('model_turn_count', 'tool_call_count', 'message_count', 'decision_count',
              'visible_message_count', 'unparsed_tool_proposal_count', 'max_isl_tokens',
              'total_osl_tokens', 'input_token_usage_count', 'output_token_usage_count')
    return {**summary, **{key: previous[key] for key in fields if key in previous},
            'summary_pending': True, 'summary_stale': True}


def fingerprint(directory):
    # Observation text and newly appearing review artifacts affect projection too.
    result=[]
    with os.scandir(directory) as entries:
        for entry in entries:
            try:
                if not entry.is_file():continue
                stat=entry.stat()
                result.append((entry.name,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
            except FileNotFoundError:pass
    return sorted(result)


def initial_summary(directory, previous=None):
    """Read small metadata/lifecycle files, never steps or model payloads."""
    from agent_trace.adapters.browsergym import episode_end, episode_title, initial_goal, read_json
    from agent_trace.trace import read_events
    metadata=read_json(directory,'metadata.json')
    if 'browsergym_version' not in metadata:return None
    episode=read_json(directory,'episode.json');task=read_json(directory,'task.json')
    evaluation=read_json(directory,'evaluation.json')
    # Use the adapter's path validation even for discovery reads.
    from agent_trace.adapters.browsergym import safe_file
    events_path=safe_file(directory,'events.jsonl')
    lifecycle=read_events(events_path) if events_path.is_file() else []
    started=next((e.get('timestamp') for e in lifecycle if e.get('event')=='episode_started'),None)
    # Some diagnostic events use numeric clock readings, not wall-clock dates.
    known=[e['timestamp'] for e in lifecycle if isinstance(e.get('timestamp'),str) and e['timestamp']]
    def compact(value):
        text=' '.join(value.split()) if isinstance(value,str) else ''
        return text if len(text)<=60 else text[:60].rsplit(' ',1)[0]+'…'
    goal=task.get('trusted_policy_goal') or metadata.get('goal') or episode.get('resolved_goal')
    goal_source='task.json' if task.get('trusted_policy_goal') else 'metadata.json' if metadata.get('goal') else 'episode.json'
    previous=previous or {}
    recording_id=metadata.get('episode_id')
    # Only a loaded model-input goal needs retention. Metadata/reset titles can
    # be reread, and a reused directory must not inherit another episode's goal.
    same_recording=(isinstance(recording_id,str) and bool(recording_id) and recording_id==previous.get('recording_id'))
    if same_recording and started and previous.get('started_at') and started!=previous['started_at']:
        same_recording=False
    if recording_id is None and previous.get('recording_id') is None:
        same_recording=isinstance(started,str) and bool(started) and started==previous.get('started_at')
    retained=(previous.get('task_title'),'steps.jsonl') if same_recording and previous.get('task_title_source')=='steps.jsonl' else None
    reset_goal=initial_goal(directory) if not goal else None
    title,title_source=episode_title(metadata,task,goal,goal_source,retained=retained,reset_goal=reset_goal)
    model=metadata.get('model');driver=metadata.get('driver')
    model_label=compact(model.rsplit('/',1)[-1]) if isinstance(model,str) else ''
    driver_label=(model_label or 'Model not recorded') if driver=='llm' else compact(driver) or model_label
    label='safe success' if evaluation.get('safe_success') is True else 'unsafe / incomplete' if evaluation.get('safe_success') is False else 'outcome unknown'
    if (directory/FILENAME).exists():label+=' · derived grade available'
    case=(metadata.get('calibration_case') or {}).get('case_id')
    return dict(id=hashlib.sha256(('browsergym:'+directory.name).encode()).hexdigest()[:20],
        title=' · '.join(str(v) for v in (case,title,driver_label,label) if v),task_title=title,
        task_title_source=title_source,recording_id=recording_id,
        started_at=started,updated_at=max(known) if known else '',
        state='recorded' if episode else 'incomplete',environment='browsergym',
        episode_end=episode_end(episode,metadata,lifecycle),
        recording_locations=[str(directory.resolve())+'/'],tags=declared_tags(metadata),
        **({'collection': declared_collection(metadata)} if declared_collection(metadata) else {}),
        summary_pending=True,message_count=None,decision_count=0,
        model_turn_count=None,tool_call_count=None,max_isl_tokens=None,total_osl_tokens=None)


class LazySessions(Mapping):
    """Keep snapshot compatibility without projecting entries during enumeration."""
    def __init__(self,hub,entries):self.hub=hub;self.entries=entries
    def __iter__(self):return iter(self.entries)
    def __len__(self):return len(self.entries)
    def __contains__(self,ident):return ident in self.entries
    def __getitem__(self,ident):return self.hub.load(self.entries[ident])


class Hub:
    def __init__(self,registry,mode='auto',*,cache_bytes=256*1024*1024,ledger=True):
        from scripts.trace_suites import SuiteCatalog
        self.suites=SuiteCatalog(registry);self.suite_memberships={}
        self.collections=CollectionStore(Path(registry).parent/'collections.json');self.collection_roots={}
        self.registry=Path(registry);self.mode=mode;self.caches={};self.lock=threading.Lock()
        self.entries={};self.bodies=OrderedDict();self.body_lock=threading.Lock()
        self.suite_refresh_lock=threading.Lock()
        self.last_snapshot_at=self.last_suite_attempt_at=float('-inf')
        self.cache_bytes=cache_bytes;self.body_bytes=0
        self.ledger=ledger
        self.cache_directory=self.registry.parent/('summary-cache-ledger' if ledger else 'summary-cache')
        # Invalidate derived summaries if the shared adapter changes.
        from agent_trace import sessions
        package=Path(sessions.__file__).parent
        self.version=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('trace_grades.py').read_bytes()+Path(__file__).with_name('trace_suites.py').read_bytes()+b''.join(
            p.read_bytes() for p in sorted(package.rglob('*.py')))+str(ledger).encode()).hexdigest()

    def roots(self):
        config=json.loads(self.registry.read_text());base=Path(config['project_root']).resolve()
        self.collection_roots={str(Path(p).resolve()):normalize_collection(label) for p,label in config.get('collection_roots',{}).items()}
        self.collection_base=base
        roots=[Path(p).resolve() for p in config.get('roots',[])]
        for pattern in config.get('patterns',[]):
            if Path(pattern).is_absolute() or '..' in Path(pattern).parts:raise ValueError('Root patterns must stay inside project')
            roots.extend(p.resolve() for p in base.glob(pattern) if p.is_dir())
        return {source_key(p):p for p in sorted(set(roots)) if p.is_dir()}

    def collection_metadata(self):
        result=self.collections.index()
        annotations=read_failure_annotations(self.registry.parent/'failure-annotations.json')
        return {**result,'failure_annotations':annotations} if annotations is not None else result

    def folder_label(self,root):
        root=Path(root).resolve()
        return self.collection_roots.get(str(root)) or (str(root.relative_to(self.collection_base)) if root.is_relative_to(self.collection_base) and root!=self.collection_base else root.name)

    def revision(self,directory,key):
        return hashlib.sha256(json.dumps((self.version,key,self.mode,str(directory),fingerprint(directory),self.suite_memberships.get(directory.resolve()))).encode()).hexdigest()

    def describe(self,directory,root,key):
        revision=self.revision(directory,key)
        ident=hashlib.sha256(('browsergym:'+directory.name).encode()).hexdigest()[:20]
        old=self.entries.get(ident)
        if old and old.get('revision')==revision:return old
        cache_path=self.cache_directory/(key+'-'+ident+'-'+self.mode+'.json')
        summary=None
        previous=old.get('summary') if old else None
        try:
            cached=json.loads(cache_path.read_text())
            if isinstance(cached.get('summary'),dict):
                if previous is None:previous=cached['summary']
                if cached.get('revision')==revision:summary=cached['summary']
        except (OSError,ValueError,KeyError,AttributeError):pass
        if summary is None:
            summary=initial_summary(directory,previous)
            if summary is not None:summary=retain_summary_counts(summary,previous)
        if summary is None:return None
        member=self.suite_memberships.get(directory.resolve())
        if member:summary={**summary,'suite':member}
        entry=dict(directory=directory,root=root,key=key,revision=revision,
                   summary={**summary,'revision':revision},cache_path=cache_path,lock=threading.Lock())
        self.persist_summary(entry)
        return entry

    def persist_summary(self,entry):
        # Persist only small derived summaries; never duplicate recordings.
        temporary=entry['cache_path'].with_suffix('.'+str(os.getpid())+'-'+str(threading.get_ident())+'.tmp')
        try:
            self.cache_directory.mkdir(parents=True,exist_ok=True)
            temporary.write_text(json.dumps({'revision':entry['revision'],'summary':entry['summary']}))
            os.replace(temporary,entry['cache_path'])
        except OSError:
            pass  # A read-only cache directory must not prevent viewing traces.

    def snapshot(self):
        from agent_trace.sessions import CatalogCache
        with self.lock:
            self.suite_memberships=self.suites.memberships()
            entries={};groups=[];folders=self.collections.read()
            for key,root in self.roots().items():
                # Historical portable/Civ5 groups retain their existing parser.
                # BrowserGym-only roots never enter this eager compatibility path.
                if any(root.glob('*/trace.jsonl')):
                    cache=self.caches.setdefault(key,CatalogCache(root,mode=self.mode))
                    summary,legacy=cache.snapshot()
                    for item in json.loads(summary):
                        if item.get('environment')=='browsergym':continue
                        ident=item['id']
                        if ident in entries:raise ValueError('Duplicate trace ID in configured sources: '+ident)
                        entries[ident]={'legacy':legacy[ident],'key':key}
                        item={**summary_fields(item),'viewer_tags':CollectionStore.tags(folders,ident,item.get('tags', [])),'viewer_collection':CollectionStore.folder(folders,ident,item.get('collection'),self.folder_label(root))}
                        groups.append(item)
                paths=sorted([*root.glob('*/metadata.json'),*root.glob('*/children/*/metadata.json'),*root.glob('*/children/*/children/*/metadata.json')])
                for path in paths:
                    directory=path.parent
                    if not path.resolve().is_relative_to(root) or not directory.resolve().is_relative_to(root):continue
                    entry=self.describe(directory,root,key)
                    if entry is None:continue
                    ident=entry['summary']['id']
                    if ident in entries:raise ValueError('Duplicate trace ID in configured sources: '+ident)
                    entry['summary']={**entry['summary'],'viewer_collection':CollectionStore.folder(folders,ident,entry['summary'].get('collection'),self.folder_label(root),parent_ids(directory))}
                    entries[ident]=entry;groups.append(entry['summary'])
            for index,item in enumerate(groups):
                entry=entries[item['id']]
                if 'directory' not in entry:continue
                parents=parent_ids(entry['directory'])
                declared=item.get('collection') or next((entries[p]['summary'].get('collection') for p in parents if p in entries and entries[p].get('summary',{}).get('collection')),None)
                entry['summary']={**item,'viewer_tags':CollectionStore.tags(folders,item['id'],item.get('tags', [])),'viewer_collection':CollectionStore.folder(folders,item['id'],declared,self.folder_label(entry['root']),parents)}
                groups[index]=entry['summary']
            self.entries=entries
            groups.sort(key=lambda g:(started_key(g),g['id']),reverse=True)
            self.last_snapshot_at=time.monotonic()
            return json.dumps(groups).encode(),LazySessions(self,entries)

    def suite_summaries(self):
        # Multiple suite tabs share one refresh per polling interval. A broken
        # unrelated recording must not hide an otherwise readable suite.
        with self.suite_refresh_lock:
            if time.monotonic()-max(self.last_snapshot_at,self.last_suite_attempt_at)>=2.5:
                try:
                    self.snapshot()
                except (OSError,ValueError,KeyError):
                    pass
                finally:
                    self.last_suite_attempt_at=time.monotonic()
            return {k:v['summary'] for k,v in self.entries.items() if 'summary' in v}

    def lookup(self,ident):
        """Revalidate only the selected trace, without rebuilding its siblings."""
        with self.lock:
            self.suite_memberships=self.suites.memberships()
            old=self.entries.get(ident)
            if old and 'directory' in old:
                roots=self.roots()
                if old['key'] not in roots or not old['directory'].resolve().is_relative_to(roots[old['key']]):raise KeyError(ident)
                entry=self.describe(old['directory'],old['root'],old['key'])
                if entry is None:raise KeyError(ident)
                self.entries[ident]=entry
                return entry
        # A new deep link still needs discovery, but never unrelated projections.
        _,entries=self.snapshot()
        return entries.entries[ident]

    def load(self,entry):
        if 'legacy' in entry:return entry['legacy']
        revision=entry['revision']
        with entry['lock']:
            with self.body_lock:
                if revision in self.bodies:
                    self.bodies.move_to_end(revision)
                    return self.bodies[revision][0],revision
            if not entry['directory'].resolve().is_relative_to(entry['root']):raise ValueError('Trace escaped root')
            group=self.project(entry)
            if group is None:raise ValueError('Trace unavailable')
            group=project_grade(group,entry['directory'])
            member=entry['summary'].get('suite')
            if member:group={**group,'suite':member}
            group=media_prefix(group,entry['key'])
            body=json.dumps(group).encode()
            # Live writers need not stop for a readable projection to be useful.
            # Give a racing read its own ETag, never the stable file fingerprint,
            # so the next poll will still fetch any events that arrived meanwhile.
            after=self.revision(entry['directory'],entry['key'])
            if after!=revision:
                entry['summary']={**summary_fields(group),'viewer_collection':entry['summary'].get('viewer_collection'),'revision':revision,
                                  'summary_pending':True,'summary_stale':True}
                self.persist_summary(entry)
                return body,'live-'+hashlib.sha256(body).hexdigest()
            compressed=gzip.compress(body,compresslevel=1,mtime=0)
            with self.body_lock:
                weight=len(body)+len(compressed)
                if weight<=self.cache_bytes:
                    while self.bodies and self.body_bytes+weight>self.cache_bytes:
                        _,removed=self.bodies.popitem(last=False);self.body_bytes-=len(removed[0])+len(removed[1])
                    self.bodies[revision]=(body,compressed);self.body_bytes+=weight
            entry['summary']={**summary_fields(group),'viewer_collection':entry['summary'].get('viewer_collection'),'revision':revision}
            self.persist_summary(entry)
            return body,revision

    def project(self,entry):
        from agent_trace.adapters import browsergym
        return browsergym.project(entry['directory'],artifact_prefix=str(entry['directory'].relative_to(entry['root'])),ledger=self.ledger)

    def encoded(self,body,revision):
        with self.body_lock:
            cached=self.bodies.get(revision)
            if cached:return cached[1]
        return gzip.compress(body,compresslevel=1,mtime=0)

    def asset(self,relative):
        from agent_trace.adapters.browsergym import asset
        key,sep,path=relative.partition('/')
        if not sep or key not in self.roots():raise ValueError('Unknown trace source')
        return asset(self.roots()[key],path)


def make_handler(registry, *, hub_class=Hub, html_factory=None):
    from agent_trace.adapters import MODES
    hubs={mode:hub_class(registry,mode) for mode in MODES}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            collection_post(self,hubs['auto'].collections,lambda:hubs['auto'].snapshot()[1])

        def do_GET(self):
            url=urlsplit(self.path);mode=parse_qs(url.query).get('parser',['auto'])[0]
            if mode not in hubs:self.send_error(400,'Unknown parsing mode');return
            hub=hubs[mode]
            try:
                if url.path=='/':
                    body=(html_factory or viewer_html)()
                    mime='text/html; charset=utf-8'
                elif url.path=='/api/collections':body=json.dumps(hub.collection_metadata()).encode();mime='application/json'
                elif url.path=='/api/sessions':body,_=hub.snapshot();mime='application/json'
                elif url.path=='/api/suites':
                    summaries=hub.suite_summaries()
                    body=json.dumps(hub.suites.index(summaries)).encode();mime='application/json'
                elif url.path.startswith('/api/suites/'):
                    ident=unquote(url.path.removeprefix('/api/suites/'))
                    try:result=hub.suites.detail(ident,summaries=hub.suite_summaries())
                    except KeyError:self.send_error(404);return
                    body=json.dumps(result).encode();mime='application/json'
                elif url.path.startswith('/api/sessions/'):
                    ident=url.path.removeprefix('/api/sessions/')
                    try:descriptor=hub.lookup(ident)
                    except KeyError:self.send_error(404);return
                    revision=descriptor.get('revision') or descriptor['legacy'][1]
                    if self.headers.get('If-None-Match')=='"'+revision+'"':
                        self.send_response(304);self.send_header('ETag','"'+revision+'"');self.end_headers();return
                    body,revision=hub.load(descriptor)
                    uncompressed_length=len(body)
                    compressed='gzip' in self.headers.get('Accept-Encoding','')
                    if compressed:body=hub.encoded(body,revision)
                    self.send_response(200);self.send_header('ETag','"'+revision+'"');self.send_header('Cache-Control','no-store' if revision.startswith('live-') else 'private, no-cache');self.send_header('Vary','Accept-Encoding');self.send_header('X-Trace-Bytes',str(uncompressed_length))
                    if compressed:self.send_header('Content-Encoding','gzip')
                    self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
                elif url.path.startswith('/artifacts/'):
                    path,mime=hub.asset(unquote(url.path.removeprefix('/artifacts/')));body=path.read_bytes()
                else:self.send_error(404);return
            except (ValueError,OSError,KeyError):
                self.send_error(404 if url.path.startswith('/artifacts/') else 503,'Trace source unavailable or changing; retry shortly');return
            self.send_response(200);self.send_header('Cache-Control','no-store');self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    return Handler


def viewer_html(*, preview=False):
    """Install the hub loader while retaining the shared renderer and scroll logic."""
    from agent_trace import sessions
    html=Path(sessions.__file__).with_name('session_viewer.html').read_text()
    start=html.index('async function refresh(){')
    end=html.index("el('parser').onchange=",start)
    loader=Path(__file__).with_name('trace_hub_client.js').read_text()
    html=html[:start]+loader+'\n'+html[end:]
    replacements={
        "list();const query=el('search').value.toLowerCase(),filter=el('filter').value;":"renderDerivedGrade();list();const query=el('search').value.toLowerCase(),filter=el('filter').value;",
        '<option value="newest">Recently updated</option>':'<option value="newest">Newest run first</option>',
        "s.message_count+' events · '+s.decision_count+' decisions'":"s.summary_pending?'Open trace to load totals':s.message_count+' events · '+s.decision_count+' decisions'",
        "window.onhashchange=()=>{refresh()};":"window.onhashchange=()=>{refresh({navigate:true})};",
        "setInterval(async()=>{if(el('live').checked&&!refreshing){refreshing=true;try{await refresh()}finally{refreshing=false}}},3000);refresh();":"setInterval(()=>{if(el('live').checked)refresh({background:true})},3000);",
    }
    for before,after in replacements.items():
        if html.count(before)!=1:raise ValueError('Shared viewer integration anchor changed: '+before[:80])
        html=html.replace(before,after)
    from agent_trace.viewer import enhance_viewer
    html=enhance_viewer(html)
    # Suite refresh needs initialized collection/sidebar state. Install it last
    # and start once, rather than racing the shared runtime's initialization.
    suite_client=Path(__file__).with_name('trace_failure_annotations.js').read_text()
    suite_client+='\n'+Path(__file__).with_name('trace_sidebar_suite.js').read_text()
    suite_client+='\n'+Path(__file__).with_name('trace_suite_client.js').read_text()
    html=html.replace('</script>',suite_client+'\n</script>',1)
    if preview:
        html=html.replace('Agent · Session traces','Agent · Ledger preview').replace('Agent / Session traces','Agent / Ledger preview')
    return html.encode()


def serve(registry,port):
    server=ThreadingHTTPServer(('127.0.0.1',port),make_handler(registry))
    print(f'Trace hub: http://localhost:{server.server_port}/#latest',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
