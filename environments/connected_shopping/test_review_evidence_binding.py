"""Frozen corpus -> public HTTP and task binding, independent of corpus sampling."""
import json,os
from copy import deepcopy
from pathlib import Path
from html import unescape
from urllib.request import urlopen
import pytest
from .runtime import Runtime
from environments.product_world.episode import Episode
from environments.product_world.generator import digest


@pytest.fixture(scope='module')
def evidence_world():
    scenario=json.loads((Path(os.environ.get('PRODUCT_REVIEW_EVIDENCE_PIN','.local/coordination/product-review-evidence/example-v3'))/'review-task-scenario.private.json').read_text())
    with Runtime(scenario,consent=False) as rt:yield scenario,rt


def test_all_rendered_reports_match_canonical_corpus(evidence_world):
    scenario,rt=evidence_world;corpus=scenario['product_review_evidence']
    assert rt.product_review_evidence==corpus
    assert rt.provenance['product_review_evidence_sha256']==digest(corpus['public'])
    assert rt.provenance['product_review_evidence_version']==corpus['schema_version']
    bodies={}
    for r in corpus['public']['reviews']:
        url=rt.bindings['product_review_reports'][r['review_id']];page=url.split('#')[0]
        if page not in bodies:bodies[page]=unescape(urlopen(page).read().decode())
        assert r['body'] in bodies[page] and 'id="'+r['review_id']+'"' in bodies[page]
        assert r['subject']['id'] in bodies[page]
        assert rt.index.catalog.search(r['subject']['id'],kind='product_reviews')
    assert len(bodies)==21


def test_episode_checks_exact_served_corpus(evidence_world):
    scenario,rt=evidence_world
    assert Episode.from_runtime(scenario,rt)
    bad=deepcopy(scenario);bad['product_review_evidence']['public']['reviews'][0]['body']='changed'
    with pytest.raises(ValueError):Episode.from_runtime(bad,rt)
