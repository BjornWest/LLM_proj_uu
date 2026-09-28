from copy import deepcopy
from html import escape
from urllib.request import urlopen
from urllib.error import HTTPError
import pytest
from .test_sites import world,bundle,Structure
from .evidence import generate_evidence
from .runtime import Runtime


@pytest.fixture(scope='module')
def panel(world):return generate_evidence(world,seed=42,reviews_per_sku=4)


def test_frozen_report_text_scope_and_links(world,bundle,panel):
    before=deepcopy(panel)
    with Runtime(bundle['public'],families=['footwear'],evidence=panel,evidence_world=world) as rt:
        assert urlopen(rt.origin+'/reader-panel').status==200
        rows=rt.evidence.reviews
        assert rows
        for a in rt.db.articles:
            body=urlopen(rt.origin+'/reviews/'+a['id']).read().decode()
            parsed=Structure(body)
            reports=[r for r in rows if r['article_id']==a['id']]
            for r in reports:
                assert escape(r['body'],quote=True) in body
                assert parsed.ids.count(r['review_id'])==1
                assert r['subject']['id'] in body and r['reviewer_id'] in body
                assert '/reviews/'+a['id']+'#'+r['review_id'] in parsed.links
            assert not any(r['review_id'] in body for r in panel['public']['reviews'] if r not in reports)
            assert 'private_provenance' not in body and 'template_choices' not in body
            for shortcut in ('First-hand use','Second-hand account; not tried','Considering this use; not tried','experience_kind','actual_use'):
                assert shortcut not in body
        with pytest.raises(HTTPError) as e:urlopen(rt.origin+'/reader-panel?sku=hidden')
        assert e.value.code==400
    assert panel==before


def test_binding_rejects_corruption_and_legacy_unchanged(world,bundle,panel):
    bad=deepcopy(panel);bad['public']['reviews'][0]['body']='fabricated'
    with pytest.raises(ValueError):Runtime(bundle['public'],evidence=bad,evidence_world=world)
    with pytest.raises(ValueError):Runtime(bundle['public'],evidence=panel)
    with Runtime(bundle['public']) as rt:
        assert rt.evidence is None
        with pytest.raises(HTTPError) as e:urlopen(rt.origin+'/reader-panel')
        assert e.value.code==404
