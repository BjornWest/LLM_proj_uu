"""Explicit authoring overrides, never draws or sampling weights."""
from copy import deepcopy

CONTROLS = {'site': {'skipLinks': ['main', 'none', 'regions'], 'navigation': ['base', 'flat', 'grouped'], 'navigationGrouping': ['departments', 'shopping-services'], 'selectors': ['inherit', 'select', 'radio', 'buttons']}, 'home': {'sectionOrder': ['base', 'showcase-first', 'services-first']}, 'results': {'presentation': ['base', 'cards', 'list', 'table'], 'filterOrder': ['seeded', 'catalog-first', 'price-first'], 'sortPlacement': ['filters', 'toolbar'], 'filterApply': ['submit', 'immediate']}, 'product': {'sectionOrder': ['base', 'buying-first', 'details-first'], 'facts': ['base', 'definitions', 'table'], 'detailsPresentation': ['base', 'inline', 'disclosure', 'tabs'], 'purchaseRegion': ['base', 'section', 'complementary', 'fieldset'], 'gallery': ['stacked', 'list', 'featured'], 'highlightCount': ['base', '1', '2', '3', '4']}, 'cards': {'detail': ['base', 'compact', 'full'], 'grouping': ['base', 'paragraphs', 'definitions']}, 'recommendations': {'presentation': ['base', 'cards', 'list'], 'placement': ['base', 'after-buying', 'after-information']}}

def validate(value):
    if not isinstance(value,dict) or set(value)-set(CONTROLS):raise ValueError("Invalid variation roles")
    for role,fields in value.items():
        if not isinstance(fields,dict) or set(fields)-set(CONTROLS[role]):raise ValueError("Invalid variation fields")
        for key,item in fields.items():
            if item not in CONTROLS[role][key]:raise ValueError("Invalid variation value")
    return deepcopy(value)
