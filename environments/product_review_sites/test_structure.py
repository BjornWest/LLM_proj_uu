"""Navigation destinations and counts must be derived, not decorative placeholders."""
from copy import deepcopy
from urllib.request import urlopen
from urllib.error import HTTPError
import pytest
from .test_sites import world,bundle,Structure
from .runtime import Runtime
from . import render,structure


def get(rt,path):return urlopen(rt.origin+path).read().decode()


@pytest.mark.parametrize('layout',['lab-directory','editorial-magazine','community-feed'])
def test_archives_preserve_identity_and_all_links_resolve(bundle,layout):
    with Runtime(bundle['public'],families=['footwear'],layout=layout,page_size=4) as rt:
        a=rt.db.articles[0];c=a['reader_opinions'][0]
        paths=['/contributors','/members','/activity','/activity?stars=1',structure.person_url('contributors',a['author']),structure.person_url('members',c['handle'])]
        for path in paths:
            html=get(rt,path)
            for link in Structure(html).links:
                if link.startswith('/'):assert urlopen(rt.origin+link).status==200
        html=get(rt,structure.person_url('members',c['handle']))
        assert c['body'] in html and c['date'] in html and render.review_url(a) in html
        assert '1 recorded reader notes.' in html
        for path in ['/members/not-a-person','/contributors/no-such-author']:
            with pytest.raises(HTTPError) as err:get(rt,path)
            assert err.value.code==404
        with pytest.raises(HTTPError) as err:get(rt,'/activity?family=unknown')
        assert err.value.code==400


def test_activity_filter_and_pagination_derive_from_full_corpus(bundle):
    with Runtime(bundle['public'],page_size=4) as rt:
        rows=structure.all_notes(rt,{'family':'wine','stars':'2'})
        expected=sorted(((a,c) for a in rt.db.articles if a['family']=='wine' for c in a['reader_opinions'] if c['stars']==2),key=lambda x:(x[1]['date'],x[1]['id']),reverse=True)
        assert rows==expected
        html=get(rt,'/activity?family=wine&stars=2&page=2')
        ids=[x.split('/opinions/')[-1] for x in Structure(html).links if '/opinions/' in x]
        assert ids==[c['id'] for _,c in expected[4:8]]


def test_facts_coverage_and_missing_fields_do_not_invent_values(bundle):
    public=deepcopy(bundle['public']);a=next(a for a in public['articles'] if a['family']=='footwear')
    v=next(v for v in public['variants'] if v['sku']==a['reviewed_sku']);v['facts'].pop('width')
    with Runtime(public,families=['footwear']) as rt:
        html=get(rt,render.review_url(a));parsed=Structure(html)
        assert '#fact-width' not in parsed.links and 'fact-width' not in parsed.ids
        assert 'Not reported' in html # comparison's missing value
        assert len(parsed.ids)==len(set(parsed.ids))
        for link in parsed.links:
            if link.startswith('#'):assert link[1:] in parsed.ids
        sections=structure.attribute_sections(rt,a)
        for key,val in v['facts'].items():
            values=[rt.db.variants[p['reviewed_sku']]['facts'][key] for p in rt.db.articles if key in rt.db.variants[p['reviewed_sku']]['facts']]
            assert f'{sum(x==val for x in values)} of {len(values)} reviewed options' in sections
        assert 'laboratory scores' in html and 'catalog facts' in html


def test_empty_reader_corpus_archives_and_histograms(bundle):
    public=deepcopy(bundle['public'])
    for a in public['articles']:
        a['reader_opinions']=[];a['reader_statistics']={'count':0,'mean':None,'histogram':{str(i):0 for i in range(1,6)}}
    with Runtime(public,layout='community-feed') as rt:
        a=rt.db.articles[0];html=get(rt,render.review_url(a))
        assert 'Not rated' in html and 'value="0"' in html
        assert '0 recorded notes' in get(rt,'/activity')
        assert 'Page 1 of 1' in get(rt,'/members')
