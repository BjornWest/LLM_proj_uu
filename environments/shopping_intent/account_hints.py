"""Optional factual coupon cues, never a requirement to use a suboptimal coupon."""
from copy import deepcopy
from .generator import stream
from .world import fingerprint


def extend(bundle,accounts,retailers,recipe='none'):
    if recipe not in ('none','auto','request','memory'):raise ValueError('Unknown coupon disclosure recipe')
    if recipe=='auto':recipe=stream(bundle['seed'],'coupon-disclosure').choice(('none','none','request','memory'))
    if recipe=='none':return bundle
    names={r['retailer_id']:r['name'] for r in retailers}
    choices=[(a,c) for a in accounts['accounts'] if a['signed_in'] for c in a['coupons']
             if not c['redeemed'] and c['valid_from']<=accounts['as_of']<=c['valid_until']]
    if not choices:
        bundle['settings']['coupon_disclosure']='none_available';return bundle
    a,c=stream(bundle['seed'],'coupon-cue-target').choice(choices);sid=a['retailer_id']
    hint={'retailer_id':sid,'coupon_id':c['coupon_id'],'code':c['code']}
    text=stream(bundle['prose_seed'],'coupon-cue-wording').choice((
        f"I've got code {c['code']} in my {names[sid]} account; check whether it helps.",
        f'There is a {c["code"]} coupon saved in my account at {names[sid]}. It might be useful here.'))
    memories=[]
    if recipe=='memory':
        mode=bundle['settings']['resolved_memory_mode'];channel=mode if mode in ('profile','episodic') else 'episodic'
        fact={'id':'account-memory-1','channel':channel,'scope':'saved account coupon','hint':hint};memories=[fact]
        if channel=='profile':bundle['public']['memories']['profile'].append({**deepcopy(fact),'text':text})
        else:bundle['public']['memories']['episodes'].append({'id':fact['id'],'text':f'Previous shopping conversation: "{text}"'})
    else:
        bundle['public']['user_message']+=' '+text
        bundle['authoring']['message_segments'].append({'stage':'context','text':' '+text,'sources':['account_hints']})
        bundle['request']['account_hints']=[hint]
    bundle['account_memory_facts']=memories
    bundle['settings']['coupon_disclosure']=recipe
    bundle['semantic_sha256']=fingerprint(bundle)
    return bundle
