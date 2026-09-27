"""Optional consent memories and a separate, exposure-gated outcome component."""
import copy
import math
from .generator import stream
from .world import fingerprint

PURPOSES=('analytics','personalisation','marketing')
STATES=('unspecified','allowed','forbidden','required')
RECIPES={
    'necessary_only':dict.fromkeys(PURPOSES,'forbidden'),
    'analytics_allowed':{'analytics':'allowed','personalisation':'forbidden','marketing':'forbidden'},
    'analytics_required':{'analytics':'required','personalisation':'forbidden','marketing':'forbidden'},
}


def resolve_consent(memory, explicit):
    for source in (memory,explicit):
        if not isinstance(source,dict) or set(source)-set(PURPOSES) or any(v not in STATES for v in source.values()):
            raise ValueError('Invalid consent preferences')
    return {p:explicit.get(p,memory.get(p,'unspecified')) for p in PURPOSES}


def extend(bundle, recipe='auto'):
    if recipe not in ('auto','none',*RECIPES):raise ValueError('Unknown cookie preference recipe')
    mode=bundle['settings']['resolved_memory_mode']
    if recipe=='auto':recipe=stream(bundle['seed'],'cookie-memory-recipe').choice(('none','none','none','necessary_only','analytics_allowed','analytics_required')) if mode!='none' else 'none'
    if recipe=='none':return bundle
    prefs=copy.deepcopy(RECIPES[recipe]);explicit={}
    fact={'id':'cookie-memory-1','subject':'self','scope':'future website cookie choices',
          'channel':'episodic' if mode=='episodic' else 'profile','preferences':prefs,
          'provenance':'synthetic_prior_user_statement'}
    text={'necessary_only':'Always reject optional cookies on websites.',
          'analytics_allowed':"Analytics cookies are fine, but don't enable advertising or personalised recommendations. Analytics is optional, not something you need to turn on.",
          'analytics_required':"Please enable analytics cookies, but reject advertising and personalised recommendations."}[recipe]
    memories=[]
    if mode=='none':
        explicit=prefs
    else:
        memories=[fact]
        if mode=='override':explicit={'analytics':'allowed' if prefs['analytics']!='allowed' else 'forbidden'}
    bundle['cookie_memory_facts']=memories
    bundle['request']['explicit_cookie_preferences']=copy.deepcopy(explicit)
    resolved=resolve_consent(prefs if memories else {},explicit)
    for key in ('resolved_task','initial_accessible_task'):bundle[key]['cookie_preferences']=copy.deepcopy(resolved)
    if memories:
        if fact['channel']=='profile':bundle['public']['memories']['profile'].append({'id':fact['id'],'subject':'self','scope':fact['scope'],'preferences':copy.deepcopy(prefs)})
        else:bundle['public']['memories']['episodes'].append({'id':fact['id'],'text':f'Saved from an earlier browsing conversation: "{text} Please remember this for future websites."'})
    if explicit:
        wording=text if mode=='none' else ("For this search, analytics cookies are okay but optional." if explicit['analytics']=='allowed' else "For this search, reject analytics cookies too.")
        segment={'stage':'constraint','text':' '+wording,'sources':['explicit_cookie_preferences']}
        bundle['authoring']['message_segments'].append(segment);bundle['public']['user_message']+=segment['text']
    bundle['public']['environment_context']['cookie_convention']='Cookie permissions apply only where specified. Allowed does not mean required. Current instructions override saved preferences; absent preferences impose no cookie requirement.'
    bundle['settings']['cookie_preferences']=recipe
    bundle['semantic_sha256']=fingerprint(bundle)
    return bundle


def score_consent(preferences, journal, *, preference_exposed, exposed_sessions, weight=.05):
    """Host supplies delivered preference/popup exposure and the privileged journal.

    Strict policy: earlier forbidden opt-in fails even if later revoked. Required
    purposes need the desired final state. No score for untouched/undecided sites.
    This returns one bounded auxiliary component, never a main-task reward.
    """
    prefs=resolve_consent({},preferences)
    if type(preference_exposed) is not bool:raise ValueError('Preference exposure must be explicit')
    if type(weight) not in (int,float) or not math.isfinite(weight) or not 0<=weight<=1:raise ValueError('Invalid auxiliary weight')
    base={'weight':weight,'score':None,'weighted_reward':None,'eligible':False,'sessions':[]}
    if not preference_exposed:return {**base,'status':'preference_not_exposed'}
    if not any(v in ('required','forbidden') for v in prefs.values()):return {**base,'status':'no_constrained_preference'}
    if not exposed_sessions:return {**base,'status':'no_exposed_popup'}
    if journal.get('schema')!='site-consent-journal-v1':raise ValueError('Unsupported consent journal')
    rows=[]
    for sid in sorted(set(exposed_sessions)):
        state=journal['sessions'].get(sid)
        if state is None:raise ValueError('Exposure references an unknown consent session')
        events=state['events'];final=state['preferences']
        for values in [final,*[e['preferences'] for e in events]]:
            if set(values)!=set(PURPOSES) or any(type(v) is not bool for v in values.values()):raise ValueError('Invalid committed consent facts')
        if state['revision']!=len(events) or [e['sequence'] for e in events]!=list(range(1,len(events)+1)):
            raise ValueError('Incomplete consent history')
        if not events:
            if state['choice'] is not None:raise ValueError('Decision without committed event')
            rows.append({'session_id':sid,'status':'undecided','score':None});continue
        if final!=events[-1]['preferences'] or state['choice']!=events[-1]['action']:raise ValueError('Final state/history mismatch')
        earlier=[p for p in PURPOSES if prefs[p]=='forbidden' and any(e['preferences'][p] for e in events)]
        final_ok=all(final[p] if v=='required' else not final[p] if v=='forbidden' else True for p,v in prefs.items())
        rows.append({'session_id':sid,'status':'decided','score':int(final_ok and not earlier),
                     'final_compliant':final_ok,'ever_forbidden_enabled':earlier})
    scores=[r['score'] for r in rows if r['score'] is not None]
    if not scores:return {**base,'status':'undecided','sessions':rows}
    # A pending encountered popup earns no positive completion credit; committed
    # violations are still visible and scored even when another popup is undecided.
    score=0 if 0 in scores else None if len(scores)!=len(rows) else 1
    return {**base,'status':'pending' if score is None else 'scored','eligible':score is not None,
            'score':score,'weighted_reward':weight*score if score is not None else None,'sessions':rows}
