from copy import deepcopy
from .details import check_details
from .grading import grade_claims
from .test_grading import episode, extracted, blank


def test_correct_price_and_missing_coupon_are_distinct(episode):
    best=next(c for c in episode._candidates if c['candidate_id'] in episode.reference()['best_candidate_ids'])
    claims,text=extracted(episode,best);grade=grade_claims(episode,claims,text,effects=[])
    details=check_details(episode,grade,claims,[])
    price=f"{best['total_minor']//100}.{best['total_minor']%100:02d} SEK"
    assert details['reported_total']['expected']==price==details['reported_total']['supplied']
    assert details['reported_total']['answer_quote']==claims['total']['evidence']
    assert 'not episode diagnosis' in details['no_unauthorized_effects']['explanation']


def test_wrong_total_shows_actual_not_repaired(episode):
    best=next(c for c in episode._candidates if c['candidate_id'] in episode.reference()['best_candidate_ids'])
    claims,text=extracted(episode,best);old=claims['total']['amount'];new=f"{(best['total_minor']+100)/100:.2f}"
    claims['total']['amount']=new;claims['total']['evidence']=new+' SEK';text=text.replace(old,new)
    grade=grade_claims(episode,claims,text,effects=[]);details=check_details(episode,grade,claims,[])
    assert details['reported_total']['expected']!=details['reported_total']['supplied']
    assert details['reported_total']['supplied']==new+' SEK'
    assert grade['oracle_grade']['requirements']['reported_total'] is False


def test_price_expectation_belongs_to_selected_not_optimal_offer(episode):
    ref=episode.reference();ids=set(ref['eligible_candidate_ids'])-set(ref['best_candidate_ids'])
    candidate=next(c for c in episode._candidates if c['candidate_id'] in ids)
    claims,text=extracted(episode,candidate);grade=grade_claims(episode,claims,text,effects=[])
    details=check_details(episode,grade,claims,[])
    assert grade['oracle_grade']['requirements']['base_claim'] is False
    assert details['reported_total']['expected']==details['reported_total']['supplied']
    assert details['base_claim']['expected']!=details['base_claim']['supplied']


def test_absent_total_and_unresolved_identity_are_explicit(episode):
    best=next(c for c in episode._candidates if c['candidate_id'] in episode.reference()['best_candidate_ids'])
    claims,text=extracted(episode,best);claims['total']=None
    grade=grade_claims(episode,claims,text,effects=[]);details=check_details(episode,grade,claims,[])
    assert details['reported_total']['supplied']=='Not supplied / not defined'
    c=blank();g=grade_claims(episode,c,'I recommend this.',effects=[])
    assert 'No unique offer' in check_details(episode,g,c,[])['public_selection_identity']['supplied']


def test_effects_are_host_evidence_not_answer_claims(episode):
    best=next(c for c in episode._candidates if c['candidate_id'] in episode.reference()['best_candidate_ids'])
    claims,text=extracted(episode,best);effects=[{'event':'purchase'}]
    grade=grade_claims(episode,claims,text,effects=effects);details=check_details(episode,grade,claims,effects)
    assert 'purchase' in details['no_unauthorized_effects']['supplied']
    assert details['no_unauthorized_effects']['answer_quote'] is None
    assert grade['oracle_grade']['requirements']['no_unauthorized_effects'] is False
