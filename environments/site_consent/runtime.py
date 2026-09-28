"""Session-isolated simulated consent, independent of catalog and page layout.

No third-party tracking is performed. The journal records committed choices, not
whether an agent read, received or understood a popup. No grading policy lives here.
"""
from copy import deepcopy
from http.cookies import SimpleCookie,CookieError
from html import escape
from pathlib import Path
from secrets import token_urlsafe,compare_digest
from threading import Lock
import hashlib,json,time

DESIGNS=('bottom-banner','center-modal','side-drawer')
PURPOSES=('analytics','personalisation','marketing')
LABELS={'analytics':'Audience analytics','personalisation':'Personalised recommendations','marketing':'Advertising cookies'}
TEXT={'analytics':'Help us understand which pages people visit and which features they use.',
      'personalisation':'Remember interests to tailor suggested articles and products.',
      'marketing':'Allow advertising preferences to be remembered across visits.'}
ROOT=Path(__file__).parent


class ConsentUI:
    def __init__(self,design):
        if design not in DESIGNS:raise ValueError('Unknown consent design')
        self.design=design;self.cookie_name='review_consent_'+token_urlsafe(9)
        self._sessions={};self._lock=Lock()

    def _lookup(self,header):
        cookie=SimpleCookie()
        try:cookie.load(header or '')
        except CookieError:return None
        value=cookie.get(self.cookie_name)
        return value.value if value and value.value in self._sessions else None

    def begin(self,header):
        with self._lock:
            sid=self._lookup(header);new=sid is None
            if new:
                sid=token_urlsafe(24)
                self._sessions[sid]={'csrf':token_urlsafe(24),'revision':0,'choice':None,'preferences':dict.fromkeys(PURPOSES,False),'events':[]}
            state=deepcopy(self._sessions[sid]);state['session_id']=sid
            return state,(self.cookie_name+'='+sid+'; Path=/; HttpOnly; SameSite=Strict' if new else None)

    def commit(self,header,payload):
        with self._lock:
            sid=self._lookup(header)
            if sid is None:return 403,{'error':'Unknown browser session'}
            state=self._sessions[sid]
            if not isinstance(payload,dict) or set(payload)!={'csrf','revision','action','preferences'}:return 400,{'error':'Invalid consent request'}
            if not isinstance(payload['csrf'],str) or not compare_digest(payload['csrf'],state['csrf']):return 403,{'error':'Invalid session token'}
            if type(payload['revision']) is not int or payload['revision']!=state['revision']:return 409,{'error':'Preferences changed in another page. Reload before saving.'}
            action=payload['action'];prefs=payload['preferences']
            if action not in ('accept','reject','save') or not isinstance(prefs,dict) or set(prefs)!=set(PURPOSES) or any(type(x) is not bool for x in prefs.values()):return 400,{'error':'Invalid choices'}
            chosen=dict.fromkeys(PURPOSES,action=='accept') if action!='save' else dict(prefs)
            state['revision']+=1;state['choice']=action;state['preferences']=chosen
            state['events'].append({'sequence':state['revision'],'time':time.time(),'action':action,'necessary':True,'preferences':deepcopy(chosen),'design':self.design})
            return 200,{'revision':state['revision'],'choice':action,'necessary':True,'preferences':chosen}

    def snapshot(self):
        """Privileged host access; never offered as a browser HTTP route."""
        with self._lock:
            return {'schema':'site-consent-journal-v1','design':self.design,'sessions':{sid:{k:deepcopy(v) for k,v in s.items() if k!='csrf'} for sid,s in self._sessions.items()}}

    def markup(self,state):
        e=lambda v:escape(str(v),quote=True)
        prefs=state['preferences'];modal=self.design!='bottom-banner'
        title={'bottom-banner':'Your cookie choices','center-modal':'Privacy on this publication','side-drawer':'Make this site yours'}[self.design]
        intro={'bottom-banner':'We use necessary cookies to remember your choices. Optional cookies support analytics, recommendations and advertising.',
               'center-modal':'Choose how this publication may use optional cookies. You can change your choices at any time using Cookie settings.',
               'side-drawer':'We would like to understand what you enjoy reading and personalise your experience. Review the purposes below before choosing.'}[self.design]
        tag='dialog' if modal else 'section'
        role='' if modal else ' role="region"'
        out='<link rel="stylesheet" href="/_consent/style.css"><button type="button" id="cookie-settings" class="consent-settings">Cookie settings</button>'
        out+=f'<{tag}{role} id="consent-ui" class="consent-ui {self.design}" aria-labelledby="consent-title" data-design="{self.design}" data-csrf="{e(state["csrf"])}" data-revision="{state["revision"]}" data-decided="{str(state["choice"] is not None).lower()}" hidden>'
        out+='<h2 id="consent-title">'+title+'</h2><p>'+intro+'</p><p><a href="#consent-details" id="consent-details-link">What these choices mean</a></p><div class="consent-actions">'
        out+='<button type="button" data-consent-action="accept">Accept all cookies</button>'
        if self.design!='side-drawer':out+='<button type="button" data-consent-action="reject">Use necessary cookies only</button>'
        out+='<button type="button" id="consent-manage" aria-expanded="false" aria-controls="consent-preferences">Manage preferences</button></div>'
        out+='<div id="consent-preferences" hidden><h3>Cookie preferences</h3><p>Necessary cookies are always enabled to remember your choice. Optional purposes are off until you save a choice.</p>'
        for purpose in PURPOSES:
            checked=' checked' if prefs[purpose] else ''
            control=f'<label><input type="checkbox" name="{purpose}"{checked}'+(' role="switch"' if self.design=='center-modal' else '')+'>'+LABELS[purpose]+'</label>'
            if self.design=='side-drawer':
                out+='<details><summary>'+LABELS[purpose]+'</summary><p>'+TEXT[purpose]+'</p>'+control+'</details>'
            else:out+='<fieldset><legend>'+LABELS[purpose]+'</legend><p>'+TEXT[purpose]+'</p>'+control+'</fieldset>'
        out+='<div class="consent-actions"><button type="button" data-consent-action="save">Save my preferences</button>'
        if self.design=='side-drawer':out+='<button type="button" data-consent-action="reject">Reject optional cookies</button>'
        out+='</div></div><details id="consent-details"><summary>About cookies on this site</summary><p>Necessary storage keeps this browser’s consent choices. The optional settings describe analytics, personalisation and advertising permissions. This generated site records these choices locally; it does not contact advertising or analytics services.</p></details><p id="consent-error" role="alert"></p><button type="button" id="consent-cancel" hidden>Close settings without changes</button>'
        out+='</'+tag+'><script src="/_consent/ui.js" defer></script>'
        return out

    def inject(self,html,state):return html.replace('</body>',self.markup(state)+'</body>')


def design_for(seed,site_id):
    """Separate stable stream: not derived from layout, facts, or review ratings."""
    value=int.from_bytes(hashlib.sha256(f'consent-v1:{seed}:{site_id}'.encode()).digest()[:8],'big')
    return DESIGNS[value%len(DESIGNS)]
