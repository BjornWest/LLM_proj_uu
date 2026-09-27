"""Deterministic claims about a scoped published review corpus, not product quality.

Canonical copies count once. Absence of a judgment is never an explicit negative.
An incomplete corpus exposes observed counts but cannot establish complete totals.
"""
from copy import deepcopy
from fractions import Fraction

STANCES=('positive','negative','neutral','mixed','not_assessed')


def summarize(reports, *, sku_id, aspect_id, context_id, complete):
    if type(complete) is not bool:raise ValueError('Explicit coverage completeness required')
    canonical={};authors={}
    for report in reports:
        rid=report['review_id'];author=report['reviewer_id'];subject=report['subject']
        if subject.get('scope')!='sku':raise ValueError('Only exact SKU review scope is supported')
        if not all(isinstance(v,str) and v for v in (rid,author,subject.get('id'))):raise ValueError('Stable review identities required')
        core={k:deepcopy(report.get(k)) for k in ('review_id','reviewer_id','subject','usage_reports','assessments','stars','sensory_observations')}
        if rid in canonical:
            if canonical[rid]!=core:raise ValueError('Conflicting copies of a canonical review')
            continue
        key=(author,subject['id'])
        if key in authors:raise ValueError('Multiple active reviews by one reviewer for a SKU')
        authors[key]=rid;canonical[rid]=core
    counts=dict.fromkeys(STANCES,0);review_ids={s:[] for s in STANCES};contextual=[];ratings=[]
    for r in canonical.values():
        if r['subject']['id']!=sku_id:continue
        stars=r['stars']
        if stars is not None:
            if type(stars) is not int or not 1<=stars<=5:raise ValueError('Rating must be integer stars from one to five')
            ratings.append(stars)
        usage=r['usage_reports'];assessments=r['assessments']
        if not isinstance(usage,list) or not isinstance(assessments,list):raise ValueError('Usage and assessments must be lists')
        if len({u['context_id'] for u in usage})!=len(usage):raise ValueError('Duplicate usage context')
        if any(u['experience_kind'] not in ('actual_use','intention','hearsay') for u in usage):raise ValueError('Unknown experience kind')
        keys=[(a['aspect_id'],a['context_id']) for a in assessments]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate aspect/context assessment')
        if any(a['stance'] not in STANCES[:-1] for a in assessments):raise ValueError('Invalid explicit assessment stance')
        if not any(u['context_id']==context_id and u['experience_kind']=='actual_use' for u in usage):continue
        contextual.append(r['reviewer_id'])
        a=next((a for a in assessments if (a['aspect_id'],a['context_id'])==(aspect_id,context_id)),None)
        stance=a['stance'] if a else 'not_assessed'
        counts[stance]+=1;review_ids[stance].append(r['review_id'])
    denominator=len(contextual)
    return {'status':'complete' if complete else 'incomplete','subject':{'scope':'sku','id':sku_id},
        'aspect_id':aspect_id,'context_id':context_id,'review_counts':counts,
        'review_ids':{k:sorted(v) for k,v in review_ids.items()},
        'contextual_reviewer_ids':sorted(contextual),'contextual_reviewer_count':denominator,
        'positive_reviewer_count':counts['positive'],
        'majority_positive':2*counts['positive']>denominator if complete and denominator else None,
        'rating_sum':sum(ratings),'rating_count':len(ratings)}


def rating_at_least(summary, threshold):
    """Use exact sum/count; a displayed rounded mean never decides a threshold."""
    if summary['status']!='complete' or not summary['rating_count']:return None
    return Fraction(summary['rating_sum'],summary['rating_count'])>=Fraction(str(threshold))


def grade_counts(summary, answer):
    """Strict structured totals; optional prose is not evaluated or inferred."""
    if summary['status']!='complete':return answer.get('status')=='uncertain'
    counts=answer.get('review_counts')
    return (answer.get('status')=='review_counts' and isinstance(counts,dict)
        and set(counts)==set(STANCES) and all(type(counts[k]) is int and counts[k]==v for k,v in summary['review_counts'].items()))
