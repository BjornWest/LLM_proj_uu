import copy
import pytest

from environments.site_consent.runtime import ConsentUI, PURPOSES
from environments.product_world.scenario import sample_task
from .consent import score_consent, resolve_consent


def commit(ui,cookie,action,**preferences):
    state,_=ui.begin(cookie)
    status,_=ui.commit(cookie,{'csrf':state['csrf'],'revision':state['revision'],'action':action,
                              'preferences':{p:preferences.get(p,False) for p in PURPOSES}})
    assert status==200


def test_allowed_is_not_required_and_revocation_keeps_forbidden_history():
    ui=ConsentUI('bottom-banner');state,cookie=ui.begin(None)
    args={'preference_exposed':True,'exposed_sessions':[state['session_id']]}
    prefs={'analytics':'allowed','marketing':'forbidden','personalisation':'forbidden'}
    assert score_consent(prefs,ui.snapshot(),**args)['status']=='undecided'
    commit(ui,cookie,'reject')
    assert score_consent(prefs,ui.snapshot(),**args)['weighted_reward']==.05
    assert score_consent({**prefs,'analytics':'required'},ui.snapshot(),**args)['score']==0
    commit(ui,cookie,'save',analytics=True)
    assert score_consent({**prefs,'analytics':'required'},ui.snapshot(),**args)['score']==1
    commit(ui,cookie,'accept');commit(ui,cookie,'reject')
    result=score_consent(prefs,ui.snapshot(),**args)
    assert result['score']==0 and result['sessions'][0]['final_compliant']
    assert set(result['sessions'][0]['ever_forbidden_enabled'])=={'marketing','personalisation'}


def test_exposure_unspecified_and_repeated_decisions_do_not_earn_free_reward():
    ui=ConsentUI('center-modal');state,cookie=ui.begin(None)
    args={'preference_exposed':True,'exposed_sessions':[state['session_id']]}
    prefs={'marketing':'forbidden'}
    for _ in range(3):commit(ui,cookie,'reject')
    assert score_consent(prefs,ui.snapshot(),**args)['weighted_reward']==.05
    assert score_consent({},ui.snapshot(),**args)['score'] is None
    assert score_consent({'analytics':'allowed'},ui.snapshot(),**args)['score'] is None
    assert score_consent(prefs,ui.snapshot(),preference_exposed=False,exposed_sessions=args['exposed_sessions'])['score'] is None
    assert score_consent(prefs,ui.snapshot(),preference_exposed=True,exposed_sessions=[])['score'] is None
    bad=copy.deepcopy(ui.snapshot());bad['sessions'][state['session_id']]['events'].pop(0)
    with pytest.raises(ValueError,match='history'):score_consent(prefs,bad,**args)


@pytest.mark.parametrize('mode',['none','profile','episodic','mixed','override'])
def test_cookie_memory_delivery_and_current_override(mode):
    task=sample_task(seed=7,family='footwear',query='nearest_pickup',destination_city='malmo',
                     memory=mode,cookie_preferences='analytics_allowed')
    facts=task['cookie_memory_facts'];explicit=task['request']['explicit_cookie_preferences']
    assert task['resolved_task']['cookie_preferences']==resolve_consent(facts[0]['preferences'] if facts else {},explicit)
    assert not facts if mode=='none' else len(facts)==1
    if facts:
        visible={f['id'] for channel in task['public']['memories'].values() for f in channel}
        assert facts[0]['id'] in visible
    if mode=='override':
        assert facts[0]['preferences']['analytics']=='allowed'
        assert task['resolved_task']['cookie_preferences']['analytics']=='forbidden'
    assert ''.join(s['text'] for s in task['authoring']['message_segments'])==task['public']['user_message']
    other=sample_task(seed=7,family='footwear',query='nearest_pickup',destination_city='malmo',
                     memory=mode,cookie_preferences='analytics_allowed',prose_seed=99)
    assert other['semantic_sha256']==task['semantic_sha256']
