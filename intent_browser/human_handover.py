"""Per-episode human tab ownership. Pure state; never touches browser objects.

UI completion is a human assertion, not verification success. Only the browser
owner may resume after capturing fresh state. Optional JSONL is human-control
evidence, not attribution of arbitrary DOM/browser events.
"""
from copy import deepcopy
from datetime import datetime,timezone
import json,re,threading,time
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode


class HandoverConflict(ValueError):
    """Invalid, stale, or out-of-order transition; nothing was accepted."""


class HumanHandoverController:
    def __init__(self, *, journal_path=None):
        self._lock=threading.RLock();self._tabs={};self._pending=[];self._revision=0
        self._journal=None;self._broken=False
        if journal_path is not None:
            self._journal=Path(journal_path)
            self._journal.parent.mkdir(parents=True,exist_ok=True)
            with self._journal.open('x',encoding='utf-8'):pass

    @staticmethod
    def _id(tab_id):
        if not isinstance(tab_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',tab_id):
            raise ValueError('Expected a stable opaque tab ID')
        return tab_id

    @staticmethod
    def _text(value,limit):
        if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):
            raise ValueError('Invalid human-control text')
        return value

    @staticmethod
    def _url(value):
        HumanHandoverController._text(value,8192)
        u=urlsplit(value)
        if u.username is not None or u.password is not None:raise ValueError('Credential-bearing URLs are not accepted')
        if value in ('about:blank','about:srcdoc'):return value
        if u.scheme not in ('http','https') or not u.hostname:raise ValueError('Expected a public HTTP(S) page URL')
        # Display projection only: do not archive common auth secrets in the UI journal.
        sensitive={'token','access_token','id_token','refresh_token','api_key','apikey','password','secret','authorization','signature','x-amz-signature','code'}
        pairs=parse_qsl(u.query,keep_blank_values=True)
        query=urlencode([(k,'[redacted]' if k.lower() in sensitive else v) for k,v in pairs])
        return urlunsplit((u.scheme,u.netloc,u.path,query,''))

    def _tab(self,tab_id):
        self._id(tab_id)
        if self._broken:raise RuntimeError('Human-control journal failed; controller unavailable')
        if tab_id not in self._tabs:raise HandoverConflict('Unknown tab')
        return self._tabs[tab_id]

    def _commit(self,tab,event,state,actor,**updates):
        if self._broken:raise RuntimeError('Human-control journal failed; controller unavailable')
        seq=self._revision+1;new={**tab,**updates,'state':state}
        transition={'sequence':seq,'event':event,'tab_id':tab['tab_id'],
            'prior_state':tab.get('state'),'new_state':state,'actor':actor,
            'timestamp':datetime.now(timezone.utc).isoformat(),'monotonic_seconds':time.monotonic(),
            'handover_id':new.get('handover_id'),'reason':new.get('reason'),
            'title':new['title'],'url':new['url']}
        if self._journal is not None:
            try:
                with self._journal.open('a',encoding='utf-8') as f:
                    f.write(json.dumps(transition,ensure_ascii=False)+'\n');f.flush()
            except Exception:
                self._broken=True
                raise
        self._tabs[tab['tab_id']]=new;self._revision=seq;self._pending.append(transition)
        return deepcopy(transition)

    def register(self,tab_id,*,title,url):
        self._id(tab_id);title=self._text(title,1000);url=self._url(url)
        with self._lock:
            if self._broken:raise RuntimeError('Human-control journal failed; controller unavailable')
            old=self._tabs.get(tab_id)
            if old:
                if old['state']=='closed':raise HandoverConflict('Closed tab IDs cannot be reused')
                if old['title']==title and old['url']==url:return None
                return self._commit(old,'metadata_updated',old['state'],'browser',title=title,url=url)
            return self._commit({'tab_id':tab_id,'title':title,'url':url,'reason':None,'handover_id':None},'registered','agent_controlled','browser')

    def handover(self,tab_id,reason):
        reason=self._text(reason,2000)
        if not reason.strip():raise ValueError('Handover needs a reason')
        with self._lock:
            tab=self._tab(tab_id)
            if tab['state']!='agent_controlled':raise HandoverConflict('Tab is not agent-controlled')
            return self._commit(tab,'handover','awaiting_human','agent',reason=reason,
                handover_id=f"handover-{self._revision+1}")

    def signal(self,tab_id,event,*,handover_id=None):
        with self._lock:
            tab=self._tab(tab_id)
            if handover_id is not None and handover_id!=tab['handover_id']:raise HandoverConflict('Stale handover')
            expected={'start':('awaiting_human',),'complete':('human_active',),
                      'cancel':('awaiting_human','human_active')}
            if event not in expected or tab['state'] not in expected[event]:raise HandoverConflict('Invalid human transition')
            return self._commit(tab,event,'human_active' if event=='start' else 'returned','human')

    def resume(self,tab_id):
        with self._lock:
            tab=self._tab(tab_id)
            if tab['state']!='returned':raise HandoverConflict('Fresh observation required after human return')
            return self._commit(tab,'resumed','agent_controlled','browser',reason=None)

    def close(self,tab_id):
        with self._lock:
            tab=self._tab(tab_id)
            if tab['state']=='closed':return None
            return self._commit(tab,'closed','closed','browser')

    def snapshot(self):
        with self._lock:
            return {'revision':self._revision,'tabs':deepcopy(list(self._tabs.values())),
                    'available':not self._broken,'url_scope':'display-only; fragments and common auth parameters omitted/redacted'}

    def drain(self):
        with self._lock:
            events=deepcopy(self._pending);self._pending.clear();return events
