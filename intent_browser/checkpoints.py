"""Opt-in, private settled-boundary capsules. Never policy tools or task oracles.

A capsule is an immutable manifest plus content-addressed original trace files.
No pickle, running browser process, executable uploaded artifact or model repair.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .checkpoint_browser import capture_browser, restore_browser, digest

VERSION = 'rollout-checkpoint-v1'
CONVERSATION_FIELDS = ('_messages','_system','_goal','_bindings','_requested',
    '_pending_result','_pending_updates','_pending_retry','_pending_human')
AX_FIELDS = ('document','_next_ref','seen','pending','_page_seen','_page_pending',
             'visits','feedback_metadata','_reuse','_semantic_key','_next_overview')


def finite(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def conversation_state(conversation):
    from .native_tools import NativeConversation
    if not isinstance(conversation,NativeConversation):
        raise ValueError('Checkpoint requires native append-only conversation')
    if not conversation._requested or any(getattr(conversation,k) for k in
            ('_pending_result','_pending_updates','_pending_retry','_pending_human')):
        raise ValueError('Checkpoint requires a fully assembled, unsettled model request')
    if getattr(conversation,'_pending_images',None):raise ValueError('Pending image delivery')
    state={k:deepcopy(getattr(conversation,k)) for k in CONVERSATION_FIELDS}
    state['call_ids']=sorted(conversation._call_ids)
    state['class']=type(conversation).__name__
    if hasattr(conversation,'_image_locations'):state['image_locations']=deepcopy(conversation._image_locations)
    return finite(state)


def restore_conversation(conversation,state,system,goal):
    if type(conversation).__name__!=state['class'] or (system,goal)!=(state['_system'],state['_goal']):
        raise ValueError('Checkpoint conversation profile/system/goal differs')
    if conversation._messages:raise ValueError('Conversation must be fresh')
    for k in CONVERSATION_FIELDS:setattr(conversation,k,deepcopy(state[k]))
    conversation._call_ids=set(state['call_ids'])
    if 'image_locations' in state:conversation._image_locations=deepcopy(state['image_locations'])


def ax_semantics(explorer):
    return {'url':explorer.url,'nodes':[{k:deepcopy(n[k]) for k in
        ('role','name','value','properties','parent','children','bid')} for n in explorer.nodes]}


def ax_state(explorer):
    from .ax_context import AXContext
    if not isinstance(explorer,AXContext):raise ValueError('Checkpoint requires incremental AX')
    state={k:deepcopy(getattr(explorer,k)) for k in AX_FIELDS}
    state.update(semantics=ax_semantics(explorer),refs=list(explorer._refs),
        states=deepcopy(explorer._states),revisit_cache=list(explorer._revisit_cache.items()))
    return finite(state)


def reconcile_label_echoes(explorer,expected):
    """Chromium sometimes retains redundant LabelText child text on a new
    document. Drop ONLY leaf, noninteractive exact copies of a sibling control
    name, and ONLY if doing so yields the entire recorded semantic tree exactly.
    Never match by labels alone or drop distinct controls/new information.
    """
    if ax_semantics(explorer)==expected:return
    nodes=explorer.nodes
    excluded=set()
    for i,n in enumerate(nodes):
        if (n['role']!='StaticText' or n['bid'] is not None or n['properties'] or
                n['children'] or n['parent'] is None):continue
        parent=nodes[n['parent']]
        if parent['role']!='LabelText':continue
        if any(nodes[j]['role'] in ('checkbox','radio') and nodes[j]['name']==n['name']
               for j in parent['children']):excluded.add(i)
    keep=[i for i in range(len(nodes)) if i not in excluded]
    indices={old:new for new,old in enumerate(keep)}
    result=deepcopy([nodes[i] for i in keep])
    for i,n in enumerate(result):
        n['index']=i;n['parent']=indices[n['parent']] if n['parent'] is not None else None
        n['children']=[indices[j] for j in n['children'] if j in indices]
    semantic={'url':explorer.url,'nodes':[{k:n[k] for k in
        ('role','name','value','properties','parent','children','bid')} for n in result]}
    if semantic!=expected:return  # Leave mismatch intact; caller rejects it.
    explorer.nodes=result
    explorer.roots=[indices[i] for i in explorer.roots]
    explorer._refs=[explorer._refs[i] for i in keep]
    explorer._identity_refs={k:v for k,v in explorer._identity_refs.items() if v in explorer._refs}
    explorer.positions={i:i for i in range(len(result))}


def restore_ax(explorer,state,observation):
    explorer.capture(observation)
    reconcile_label_echoes(explorer,state['semantics'])
    if ax_semantics(explorer)!=state['semantics']:
        raise ValueError('Checkpoint AX semantics/BIDs differ; old refs cannot be rebound')
    if len(set(state['refs']))!=len(explorer.nodes):raise ValueError('Invalid checkpoint AX refs')
    # Bind OLD policy references to verified NEW Chromium identities, rather
    # than copying backendDOMNodeId/frame IDs into the new browser.
    mapping=dict(zip(explorer._refs,state['refs']))
    identities={identity:mapping[ref] for identity,ref in explorer._identity_refs.items()}
    for k in AX_FIELDS:setattr(explorer,k,deepcopy(state[k]))
    explorer._identity_refs=identities
    explorer._refs=list(state['refs']);explorer._indices={r:i for i,r in enumerate(explorer._refs)}
    explorer._states=deepcopy(state['states'])
    explorer._revisit_cache=OrderedDict((k,{int(i):v for i,v in items.items()})
                                      for k,items in state['revisit_cache'])
    # _document_key is the LIVE root identity from capture, intentionally kept.


def fsync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def safe_name(name):
    if not isinstance(name,str):raise ValueError('Invalid checkpoint artifact path')
    p=PurePosixPath(name)
    if name!=p.as_posix() or name in ('','.','..') or p.is_absolute() or any(x in ('..','.') for x in p.parts) or '\\' in name:
        raise ValueError('Unsafe checkpoint artifact path')
    return p


class CheckpointStore:
    """Atomic manifests, exclusive objects, verified reads; concurrent writers safe."""
    def __init__(self,root):
        self.root=Path(root);self.objects=self.root/'objects';self.capsules=self.root/'checkpoints'
        self.objects.mkdir(parents=True,exist_ok=True);self.capsules.mkdir(exist_ok=True)

    def put(self,data):
        sha=hashlib.sha256(data).hexdigest();path=self.objects/sha
        temp=self.objects/('.'+uuid4().hex)
        try:
            with temp.open('xb') as f:
                f.write(data);f.flush();os.fsync(f.fileno())
            try:os.link(temp,path)
            except FileExistsError:pass
            if path.is_symlink() or path.read_bytes()!=data:raise ValueError('Corrupt checkpoint object')
            fsync_directory(self.objects)
        finally:temp.unlink(missing_ok=True)
        return {'sha256':sha,'bytes':len(data)}

    def get(self,record):
        sha=record['sha256']
        if not isinstance(sha,str) or type(record.get('bytes')) is not int or record['bytes']<0:
            raise ValueError('Invalid object record')
        if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('Invalid object hash')
        path=self.objects/sha
        if path.is_symlink():raise ValueError('Checkpoint object must not be a symlink')
        data=path.read_bytes()
        if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=sha:
            raise ValueError('Checkpoint object changed')
        return data

    def save(self,payload,trace):
        trace.flush_observations()
        files={}
        for path in sorted(trace.directory.rglob('*')):
            if path.is_symlink():raise ValueError('Symlink in trace prefix')
            if path.is_file():files[path.relative_to(trace.directory).as_posix()]=self.put(path.read_bytes())
        record=finite({'schema_version':VERSION,'payload':payload,'prefix':files})
        data=json.dumps(record,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        identifier=hashlib.sha256(data).hexdigest()
        path=self.capsules/(identifier+'.json')
        temp=self.capsules/('.'+uuid4().hex)
        try:
            temp.write_bytes(data)
            with temp.open('rb') as f:os.fsync(f.fileno())
            try:os.link(temp,path)
            except FileExistsError:pass
            if path.is_symlink() or path.read_bytes()!=data:raise ValueError('Checkpoint manifest changed')
            fsync_directory(self.capsules)
        finally:temp.unlink(missing_ok=True)
        return identifier

    def load(self,identifier):
        if not isinstance(identifier,str) or len(identifier)!=64 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError('Invalid checkpoint ID')
        path=self.capsules/(identifier+'.json')
        if path.is_symlink():raise ValueError('Checkpoint manifest must not be a symlink')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=identifier:raise ValueError('Checkpoint manifest changed')
        record=json.loads(data)
        if record['schema_version']!=VERSION:raise ValueError('Unsupported checkpoint')
        for name,value in record['prefix'].items():safe_name(name);self.get(value)
        return record

    def materialize_prefix(self,record,destination):
        destination=Path(destination)
        destination.mkdir(parents=True,exist_ok=False)
        for name,value in record['prefix'].items():
            path=destination.joinpath(*safe_name(name).parts);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(self.get(value))


class CheckpointControl:
    """Trusted caller-selected boundaries; first version is generated-page only.

    selector receives local decision index and read-only trace metadata, never
    modifies a policy request. Returning true saves; stop_after_save suspends
    before any backend call at that boundary. Restore creates a fresh branch.
    """
    def __init__(self,store,world,*,selector=None,restore=None,stop_after_save=True):
        self.store=store;self.world=world;self.selector=selector
        self.restore_id=restore;self.stop_after_save=stop_after_save;self.saved=[]
        self.record=store.load(restore) if restore else None
        self.restored=False

    def close(self):
        bridge=getattr(self,'bridge',None)
        if bridge is not None:bridge.close()

    def validate(self,profile,pipeline,**features):
        if (not profile or not profile.ax_config or not profile.ax_config.incremental or
                profile.agent_limits or profile.tools.open_internet or not profile.delivery_tracking or
                not hasattr(profile.tools,'parse_completion') or pipeline is not None or
                any(features.values())):
            raise ValueError('Checkpoint v1 requires native incremental generated pages without pipeline, helpers, memory, retries, clarification, search or video')
        for name in ('checkpoint_state','restore_state','state_fingerprint','checkpoint_hydration'):
            if not callable(getattr(self.world,name,None)):raise ValueError('Missing world checkpoint adapter: '+name)
        if self.record:
            from .trace import runtime_provenance
            state=self.record['payload']
            if runtime_provenance()!=state['runtime']:raise ValueError('Checkpoint runtime source/package closure differs')
        self.world.state_fingerprint()  # Explicit adoption/settled-source gate BEFORE inference.

    def restore_world(self):
        if self.record:
            self.world.restore_state(deepcopy(self.record['payload']['world']))

    def prepare_env(self,env):
        from browsergym.core.task import OpenEndedTask
        base=env.unwrapped
        if base.task_entrypoint is not OpenEndedTask:
            raise ValueError('Checkpoint v1 requires an adopted OpenEndedTask factory')
        from .checkpoint_browser import LogicalOrigins
        from .checkpoint_history import track
        control=self
        if self.record:
            self.bridge=LogicalOrigins(self.record['payload']['logical_origins'],self.world.origins)
        class CheckpointTask(OpenEndedTask):
            def setup(self,page):
                track(page.context)
                if control.record:
                    control.bridge.attach(page.context)
                    return self.goal, {}
                return super().setup(page)
        base.task_entrypoint=CheckpointTask
        self.restore_world()

    def restore_browser(self,env):
        if not self.record:return None
        state=self.record['payload']
        if self.world.state_fingerprint()!=state['world_fingerprint']:
            raise ValueError('Restored world changed before browser initialization')
        with self.world.checkpoint_hydration():
            restore_browser(env,state['browser'])
            from .observation import refresh_observation
            obs=refresh_observation(env)
        if self.world.state_fingerprint()!=state['world_fingerprint']:
            raise ValueError('Browser hydration changed world checkpoint state')
        return obs

    def restore_episode(self,env,trace,conversation,ax,delivery,profile,system,obs,vision,data):
        if not self.record:return None
        state=deepcopy(self.record['payload'])
        if trace.metadata['seed']!=state['seed']:raise ValueError('Checkpoint browser seed differs')
        if trace.metadata['runtime']!=state['runtime']:
            raise ValueError('Checkpoint runtime source/package closure differs')
        if finite(profile.describe())!=state['profile']:raise ValueError('Checkpoint harness profile differs')
        try:
            restore_ax(ax,state['ax'],obs)
        except ValueError:
            from .trace import write_json
            write_json(trace.directory/'checkpoint-ax-mismatch.json',
                {'expected':state['ax']['semantics'],'actual':ax_semantics(ax)})
            raise
        restore_conversation(conversation,state['conversation'],system,obs['goal'])
        self.store.materialize_prefix(self.record,trace.directory/'inherited')
        delivery.sources=deepcopy(state['delivery']['sources'])
        delivery.confirmed={tuple(v) for v in state['delivery']['confirmed']}
        for item in delivery.sources.values():item['artifact']='inherited/'+item['artifact']
        if vision is not None:
            vision.images=deepcopy(state['vision'])
            for value in vision.images.values():value['artifact']='inherited/'+value['artifact']
        if data is not None:
            data.restore_state(state['data'])
        state['event']['checkpoint_pending_observation']={k:'inherited/'+v if v is not None else None
            for k,v in state['event']['observation'].items()}
        state['event']['observation_text_scope']='Inherited pending policy text; new restored raw snapshot validates equivalence.'
        self.restored=True
        trace.metadata['continuation']={'version':VERSION,'checkpoint':self.restore_id,
            'parent_episode':state['parent_episode'],'parent_turn':state['turn'],
            'inherited_prefix':'inherited','messages_sha256':digest(state['conversation']['_messages']),
            'scope':'New isolated runtime/browser; inherited effects and exact pending request'}
        from .trace import write_json
        write_json(trace.directory/'metadata.json',trace.metadata)
        return obs,state

    def boundary(self,env,trace,conversation,ax,delivery,profile,index,event,vision,data,counters):
        if self.selector is None or not self.selector(index,deepcopy(trace.metadata)):return False
        before=self.world.state_fingerprint()
        world=self.world.checkpoint_state()
        browser=capture_browser(env)
        from urllib.parse import urlsplit
        declared=set(self.record['payload']['logical_origins'].values() if self.record else self.world.origins.values())
        for page in browser['pages']:
            for url in [page['url'],*[item['url'] for item in page['history']['entries'] if item['url']!='about:blank']]:
                parsed=urlsplit(url)
                if f'{parsed.scheme}://{parsed.netloc}' not in declared:raise ValueError('Checkpoint document/history outside adopted world')
        if before!=self.world.state_fingerprint():raise ValueError('World changed while checkpointing browser')
        payload={'world':world,'world_fingerprint':self.world.state_fingerprint(),
            'browser':browser,'conversation':conversation_state(conversation),'ax':ax_state(ax),
            'delivery':{'sources':deepcopy(delivery.sources),'confirmed':sorted(delivery.confirmed)},
            'profile':profile.describe(),'runtime':trace.metadata['runtime'],
            'parent_episode':trace.episode_id,'turn':index,'seed':trace.metadata['seed'],'counters':counters,
            'event':{k:deepcopy(event[k]) for k in ('messages','policy_bindings','observation','observation_text_sha256')},
            'vision':deepcopy(vision.images) if vision else None,
            'data':data.checkpoint_state() if data else None,
            'logical_origins':deepcopy(self.record['payload']['logical_origins'] if self.record else self.world.origins)}
        identifier=self.store.save(payload,trace);self.saved.append(identifier)
        trace.event('checkpoint_saved',checkpoint=identifier,turn=index,version=VERSION,
            request_dispatched=False,world_fingerprint=payload['world_fingerprint'])
        return self.stop_after_save
