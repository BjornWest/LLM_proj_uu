from copy import deepcopy

import pytest

from .review_evidence import summarize,rating_at_least,grade_counts


def report(i,stance='positive',*,sku='sku',context='long_walks',experience='actual_use',stars=4):
    return {'review_id':f'r{i}','reviewer_id':f'u{i}','subject':{'scope':'sku','id':sku},'stars':stars,
        'usage_reports':[{'context_id':context,'experience_kind':experience}],
        'assessments':[] if stance is None else [{'aspect_id':'comfort','context_id':context,'stance':stance}]}


def summary(reports,complete=True):
    return summarize(reports,sku_id='sku',aspect_id='comfort',context_id='long_walks',complete=complete)


def test_majority_counts_unassessed_context_users_and_rejects_ties():
    assert summary([report(1),report(2),report(3,None)])['majority_positive'] is True
    assert summary([report(1),report(2,None)])['majority_positive'] is False
    assert summary([])['majority_positive'] is None


def test_other_usage_intentions_hearsay_and_sibling_skus_are_not_votes():
    result=summary([report(1),report(2,'negative',context='styling'),report(3,experience='intention'),
        report(4,experience='hearsay'),report(5,'negative',sku='other-size')])
    assert result['contextual_reviewer_count']==1 and result['majority_positive'] is True


def test_explicit_negative_is_not_absence_and_mixed_is_separate():
    s=summary([report(i,stance) for i,stance in enumerate(('positive','negative','neutral','mixed',None))])
    assert s['review_counts']==dict.fromkeys(('positive','negative','neutral','mixed','not_assessed'),1)
    assert grade_counts(s,{'status':'review_counts','review_counts':s['review_counts']})
    assert not grade_counts(s,{'status':'review_counts','review_counts':{**s['review_counts'],'negative':2}})
    assert not grade_counts(s,{'status':'review_counts','review_counts':{**s['review_counts'],'negative':True}})


def test_copies_deduplicate_but_conflicting_copies_and_multiple_active_reviews_fail():
    a=report(1);copy={**a,'source_locator':'syndicated-copy'}
    assert summary([a,copy])['contextual_reviewer_count']==1
    bad=deepcopy(a);bad['stars']=1
    with pytest.raises(ValueError,match='Conflicting'):summary([a,bad])
    bad=deepcopy(a);bad['review_id']='another-review'
    with pytest.raises(ValueError,match='Multiple active'):summary([a,bad])


def test_incomplete_corpus_is_unknown_and_rating_threshold_uses_exact_arithmetic():
    reports=[report(i,stars=s) for i,s in enumerate((3,3,4))]
    s=summary(reports)
    assert rating_at_least(s,'3.3333333333333333') is True
    assert rating_at_least(s,'3.34') is False
    incomplete=summary(reports,False)
    assert incomplete['majority_positive'] is None and rating_at_least(incomplete,3) is None
    assert not grade_counts(incomplete,{'status':'review_counts','review_counts':incomplete['review_counts']})
    assert grade_counts(incomplete,{'status':'uncertain'})
    assert rating_at_least(summary([]),0) is None
