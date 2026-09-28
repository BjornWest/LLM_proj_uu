import pytest
from browser_training.sft_mixture import mix


def row(text): return {'messages':[{'role':'assistant','content':text}]}
def measure(row):
    n=len(row['messages'][0]['content'])
    return dict(processed_tokens=n+100,loss_tokens=n)  # Explicit synthetic token counts, no tokenizer claim.


def test_target_uses_loss_tokens_and_preserves_browser_examples():
    browser=[row('b'*190)]
    replay=[row('r'*10),row('unused'*90)]
    rows,report=mix(browser,replay,measure,replay_fraction=0.05,tolerance=0)
    assert report['actual_replay_loss_fraction']==0.05
    assert report['replay_processed_fraction']==110/400
    assert all(example in rows for example in browser)
    assert (rows,report)==mix(browser,replay,measure,replay_fraction=0.05,tolerance=0)


def test_exact_duplicates_holdouts_and_cross_source_overlap():
    _,r=mix([row('b'),row('b')],[],measure,replay_fraction=0)
    assert r['browser_exact_duplicates_removed']==1
    with pytest.raises(ValueError,match='protected'):
        mix([row('b')],[],measure,replay_fraction=0,protected=[row('b')])
    with pytest.raises(ValueError,match='overlap'):
        mix([row('b')],[row('b')],measure,replay_fraction=0)


def test_unattainable_fraction_and_zero_loss_fail_before_output():
    with pytest.raises(ValueError,match='misses target'):
        mix([row('b')],[row('r'*100)],measure,replay_fraction=0.05)
    with pytest.raises(ValueError,match='measurement'):
        mix([row('b')],[],lambda _:dict(processed_tokens=10,loss_tokens=0),replay_fraction=0)
