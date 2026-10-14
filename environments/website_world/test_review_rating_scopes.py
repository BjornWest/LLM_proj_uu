"""Public SKU summaries, including zero/silent ratings; no generated worlds."""
from copy import deepcopy
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlsplit

import pytest
from environments.product_world.review_population import summarize_ratings
from . import review_rating_scopes as scopes
from .native_review_pages import NativeReviewPage, LAYOUTS
from .surrounding_pages import ReviewPage, path
from .review_saved_inputs import target_setup


class OptionPanel(HTMLParser):
    def __init__(self, html, label='Option-specific rating summary'):
        super().__init__(convert_charrefs=True)
        self.depth = 0; self.text = []; self.links = []; self.tables = 0; self.label = label
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section' and (self.depth or attrs.get('aria-label') == self.label):
            self.depth += 1
        if self.depth:
            if tag == 'a': self.links.append(attrs['href'])
            if tag == 'table': self.tables += 1

    def handle_endtag(self, tag):
        if tag == 'section' and self.depth: self.depth -= 1

    def handle_data(self, data):
        if self.depth: self.text.append(data)


def product():
    # Model100, target2silent, written27: the demonstrated gap's shape.
    rows = [{'review_id': 'silent-' + str(n), 'reviewer': 'Silent reader',
             'sku_id': 'p/navy-37', 'rating': stars, 'text': ''}
            for n, stars in enumerate((4, 5))]
    rows += [{'review_id': 'other-' + str(n), 'reviewer': 'Other reader',
              'sku_id': 'p/red-38', 'rating': 3, 'text': 'Other option comment' if n < 27 else ''}
             for n in range(98)]
    return {'product_id': 'p', 'name': 'Test Trainer', 'family_id': 'footwear', 'facts': {},
            'skus': [{'sku_id': sid, 'product_id': 'p', 'colour': colour, 'size_eu': size}
                     for sid, colour, size in (('p/navy-37', 'navy', 37), ('p/red-38', 'red', 38),
                                              ('p/blue-39', 'blue', 39))],
            'reviews': rows, 'rating_summary': summarize_ratings(rows)}


def view(layout, p):
    site = {'name': 'Review Test', 'layout': layout, 'families': ['footwear'],
            'family_labels': {'footwear': 'Footwear'},
            'review_presentation': {'page_size': 2}}
    cls = NativeReviewPage if layout in LAYOUTS else ReviewPage
    return cls(site, {'p': p}, {}, {}, None)


@pytest.mark.parametrize('layout', scopes.SKU_SUMMARY_LAYOUTS)
def test_filtered_route_exposes_silent_option_summary_separate_from_model_and_comments(layout):
    p = product(); before = deepcopy(p); page = view(layout, p)
    query = {'sku': 'p/navy-37', 'stars': '1'}
    if layout == 'editorial-magazine': query['part'] = 'readers'
    if layout in LAYOUTS: query.update(sort='highest', page='10')
    html = page.page('/reviews/p', query)[1]
    panel = OptionPanel(html); text = ' '.join(panel.text)
    assert '100 ratings; 27 written reviews, 73 ratings without comments' in html
    assert 'Model-wide rating summary' in html
    assert 'aria-label="Model-wide customer rating summary"' in html
    assert 'aria-label="Option-specific customer rating summary"' in html
    assert 'All recorded ratings for this option' in text
    assert '2 ratings; 0 written reviews, 2 ratings without comments' in text
    assert '4.50 / 5' in text and 'SKU: p/navy-37' in text
    assert 'No written comments match' in html and '<blockquote>' not in html
    assert panel.tables == 1
    assert len(panel.links) == 5
    model = OptionPanel(html, 'Model-wide customer rating summary')
    assert len(model.links) == 5
    assert all('sku' not in dict(parse_qsl(urlsplit(href).query)) for href in model.links)
    for href in panel.links:
        fields = dict(parse_qsl(urlsplit(href).query))
        assert fields['sku'] == 'p/navy-37' and fields['stars'] in '12345'
        assert 'page' not in fields
        if layout == 'editorial-magazine': assert fields['part'] == 'readers'
    assert p == before


@pytest.mark.parametrize('layout', LAYOUTS)
def test_option_route_has_same_summary_and_working_reader_link(layout):
    page = view(layout, product())
    html = page.page(path('variants', 'p/navy-37'), {})[1]
    panel = OptionPanel(html)
    assert '4.50 / 5' in ' '.join(panel.text)
    assert '2 ratings; 0 written reviews, 2 ratings without comments' in ' '.join(panel.text)
    fields = dict(parse_qsl(urlsplit(panel.links[0]).query))
    assert fields['sku'] == 'p/navy-37'
    # Follow a histogram link through the actual renderer, including editorial part.
    status, reader_html, _ = page.page('/reviews/p', fields)
    assert status == 200 and '4.50 / 5' in ' '.join(OptionPanel(reader_html).text)


@pytest.mark.parametrize('layout', scopes.SKU_SUMMARY_LAYOUTS)
def test_zero_rated_option_has_zero_histogram_and_undefined_mean(layout):
    query = {'sku': 'p/blue-39'}
    if layout == 'editorial-magazine': query['part'] = 'readers'
    html = view(layout, product()).page('/reviews/p', query)[1]
    panel = OptionPanel(html); text = ' '.join(panel.text)
    assert '0 ratings; 0 written reviews, 0 ratings without comments' in text
    assert 'Mean rating undefined (no ratings)' in text and 'None / 5' not in text
    assert panel.tables == 1 and len(panel.links) == 5
    assert scopes.sku_rating_summary(product(), 'p/blue-39')['star_counts'] == dict.fromkeys('12345', 0)


def test_canonical_identity_scope_and_half_up_rounding():
    p = product(); before = deepcopy(p)
    p['reviews'].append(deepcopy(p['reviews'][0]))
    summary = scopes.sku_rating_summary(p, 'p/navy-37')
    assert summary['rating_count'] == 2 and summary['star_counts'] == {'1': 0, '2': 0, '3': 0, '4': 1, '5': 1}
    assert summary['mean_rounded'] == '4.50'
    p['reviews'][-1]['rating'] = 1
    with pytest.raises(ValueError, match='Conflicting'): scopes.sku_rating_summary(p, 'p/navy-37')
    with pytest.raises(ValueError, match='Unknown'): scopes.sku_rating_summary(before, 'unknown')
    p = product()
    p['reviews'] = [{'review_id': str(n), 'sku_id': 'p/navy-37', 'rating': 1 if n < 7 else 2, 'text': ''}
                    for n in range(8)]
    assert scopes.sku_rating_summary(p, 'p/navy-37')['mean_rounded'] == '1.13'


@pytest.mark.parametrize('sku_index', (0, 1, 2))
def test_public_projection_matches_native_reference_without_reading_it(sku_index):
    from .test_catalog_review_task import fixture
    world, task, reference, _, _, _ = fixture('rating_summary', subject_scope='sku', sku_index=sku_index)
    item = world['products'][0]
    public = {'skus': deepcopy(item['public']['skus']), 'reviews': [
        {k: deepcopy(r[k]) for k in ('review_id', 'sku_id', 'rating', 'text')} for r in item['reviews']]}
    before = deepcopy(public)
    result = scopes.sku_rating_summary(public, task['subject']['sku_id'])
    expected = {k: v for k, v in reference['summary'].items() if k != 'mean_rounded'}
    assert {k: v for k, v in result.items() if k != 'mean_rounded'} == expected
    assert result['mean_rounded'] == reference['summary']['mean_rounded']
    assert public == before


def test_named_preparation_requires_renderer_support_and_preserves_world():
    world = {'world_id': 'saved'}
    task = {'world_id': 'saved', 'subject': {'product_id': 'p', 'sku_id': 'p/navy-37'},
            'operation': 'rating_summary', 'subject_scope': 'sku'}
    surrounding = {'source_world_id': 'saved', 'sites': [{'site_id': 'reviews', 'name': 'Review Test',
        'kind': 'product_reviews', 'product_ids': ['p'], 'layout': 'community-feed'}]}
    binding = {'status': 'bound', 'publication_ids': ['reviews'], 'world_repaired': False}
    before = deepcopy((world, task, surrounding, binding))
    for layout in scopes.SKU_SUMMARY_LAYOUTS:
        surrounding['sites'][0]['layout'] = layout
        assert target_setup(world, task, surrounding, binding, review_site_id='reviews')['world_draws'] == 0
    surrounding['sites'][0]['layout'] = 'unsupported-future-layout'
    with pytest.raises(ValueError, match='public SKU rating summary'):
        target_setup(world, task, surrounding, binding, review_site_id='reviews')
    surrounding['sites'][0]['layout'] = before[2]['sites'][0]['layout']
    assert (world, task, surrounding, binding) == before
    assert set(scopes.SKU_SUMMARY_LAYOUTS) == {'journal', 'community', *LAYOUTS}
