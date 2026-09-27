"""Typed product-review preferences with request/profile/episodic prose placement."""
from copy import deepcopy

from .generator import stream
from .world import fingerprint
from .review_evidence import rating_at_least


def requirement_result(requirement,summary):
    if summary is None or summary['status']!='complete':return None
    if requirement['rule']=='strict_majority':return summary['majority_positive']
    if requirement['rule']=='minimum_rating':
        if summary['rating_count']<requirement['minimum_reviews']:return False
        return rating_at_least(summary,requirement['minimum_stars'])
    raise ValueError('Unknown product review rule')


def extend(bundle,recipe='none'):
    from environments.product_review_sites.evidence import PRIMARY,ASPECTS,PUBLISHER
    if recipe not in ('none','auto','majority','rating'):raise ValueError('Unknown product review preference recipe')
    if recipe=='auto':recipe=stream(bundle['seed'],'product-review-recipe').choice(('none','none','majority','rating'))
    if recipe=='none':return bundle
    task=bundle['resolved_task']
    if len(task['lines'])!=1:raise ValueError('Product review preferences currently support one product line')
    family=task['lines'][0]['family_id'];aspect=PRIMARY[family];context=ASPECTS[aspect]['context']
    requirement={'publisher_id':PUBLISHER,'aspect_id':aspect,'context_id':context,'unit':'reviewer',
        'rule':'strict_majority' if recipe=='majority' else 'minimum_rating'}
    rng=stream(bundle['prose_seed'],'product-review-wording')
    if recipe=='majority':
        clause={'footwear':'people who mention wearing them on long walks say they are comfortable',
            'laptops':'people who mention typing on it say the keyboard is comfortable',
            'dog_food':'owners who report feeding it to their dogs say their dogs readily ate it',
            'cat_food':'owners who report feeding it to their cats say their cats readily ate it',
            'beer':'people who report tasting it say they enjoyed the taste',
            'wine':'people who report tasting it say they enjoyed the taste'}[family]
        text=rng.choice((f'I want one where most {clause}.',f'Please look for one where more than half of the {clause}.'))
    else:
        requirement.update(minimum_stars=stream(bundle['seed'],'product-review-rating').choice((3,3.5,4)),minimum_reviews=5)
        text=rng.choice((f'I want at least five reader ratings, averaging {requirement["minimum_stars"]}/5 or better.',
            f'Only consider options with a reader average of at least {requirement["minimum_stars"]}/5 from five or more ratings.'))
    mode=bundle['settings']['resolved_memory_mode'];memories=[];explicit=[]
    if mode=='none':explicit=[deepcopy(requirement)]
    else:
        channel=mode if mode in ('profile','episodic') else stream(bundle['seed'],'review-memory-placement').choice(('profile','episodic'))
        memory={'id':'product-review-memory-1','family_id':family,'subject':task['lines'][0]['subject'],
            'channel':channel,'requirement':deepcopy(requirement),'provenance':'synthetic_prior_user_statement'}
        memories=[memory]
        if channel=='profile':bundle['public']['memories']['profile'].append({'id':memory['id'],'family_id':family,'subject':memory['subject'],'review_preference':deepcopy(requirement),'text':text})
        else:bundle['public']['memories']['episodes'].append({'id':memory['id'],'text':f'Previous conversation about {family.replace("_"," ")}: "{text} Keep this preference for future searches."'})
    source={'kind':'memory','id':memories[0]['id'],'channel':memories[0]['channel']} if memories else {'kind':'request'}
    bundle['product_review_memory_facts']=memories
    bundle['request']['explicit_product_review_requirements']=explicit
    for key in ('resolved_task','initial_accessible_task'):bundle[key]['product_review_requirements']=[{**deepcopy(requirement),'source':source}]
    if explicit:
        bundle['public']['user_message']+=' '+text
        bundle['authoring']['message_segments'].append({'stage':'requirement','text':' '+text,'sources':['product_review_requirements']})
    bundle['public']['environment_context']['product_review_scope']='Use the published reader reports in the supplied product-review sites, for the exact product option, as of the corpus date. Count people reporting actual use in the requested context, including those who leave that aspect unassessed. Missing or incomplete coverage is unknown.'
    if recipe=='rating':
        bundle['public']['environment_context']['product_review_scope']='Use all published reader ratings in the supplied product-review sites, for the exact product option, as of the corpus date. Unrated reports have no star value; second-hand reports may still carry a submitted rating. Missing or incomplete coverage is unknown.'
    bundle['settings']['product_review_preferences']=recipe
    bundle['semantic_sha256']=fingerprint(bundle)
    return bundle
