"""Versioned, private site presentation choices, independent of commercial facts."""
import hashlib
from .department_variations import CHOICES, DEFAULTS as DEPARTMENT_DEFAULTS, validate as validate_variations

DESIGNS=('legacy-catalog','department-market','editorial-boutique','technical-catalog','dense-storefront')
SHOWCASE={'nordhem':'department-market','vardagslagret':'editorial-boutique','teknikgarden':'technical-catalog'}
SHOWCASE_OPTIONS={
    'nordhem':{'nav_expanded':True,'image_count':2,'title_style':'descriptive','details_presentation':'inline'},
    'vardagslagret':{'nav_expanded':False,'image_count':2,'title_style':'short','details_presentation':'linked'},
    'teknikgarden':{'nav_expanded':True,'image_count':1,'title_style':'short','details_presentation':'disclosure'},
}
DEFAULT_DETAILS={'legacy-catalog':'inline','department-market':'inline','editorial-boutique':'linked','technical-catalog':'disclosure','dense-storefront':'disclosure'}


def resolve_presentations(seed,retailer_ids,designs=None,options=None):
    designs={} if designs is None else dict(designs)
    options={} if options is None else dict(options)
    if (set(designs)|set(options))-set(retailer_ids):raise ValueError('Unknown presentation retailer')
    result={};settings={}
    for site in retailer_ids:
        design=designs.get(site,'legacy-catalog')
        if design not in DESIGNS:raise ValueError('Unknown retailer design')
        def pick(key,values):
            h=hashlib.sha256(f'commerce-presentation-v2/{seed}/{site}/{key}'.encode()).digest()
            return values[int.from_bytes(h[:8],'big')%len(values)]
        configured=dict(options.get(site,{}))
        if set(configured)-({'nav_expanded','image_count','title_style','details_presentation','legacy_style'}|set(CHOICES)):raise ValueError('Unknown presentation option')
        validate_variations(design,configured)
        default_style={'nordhem':'catalog','vardagslagret':'boutique','teknikgarden':'specifications'}.get(site,'catalog')
        resolved={'nav_expanded':pick('nav_expanded',(False,True)),
                  'image_count':pick('image_count',(1,2)),
                  'title_style':pick('title_style',('short','descriptive')),
                  'details_presentation':DEFAULT_DETAILS[design],
                  'legacy_style':default_style,**(DEPARTMENT_DEFAULTS if design=='department-market' else {}),**configured}
        if type(resolved['nav_expanded']) is not bool:raise ValueError('nav_expanded must be boolean')
        if type(resolved['image_count']) is not int or resolved['image_count'] not in (1,2):raise ValueError('image_count must be 1 or 2')
        if resolved['title_style'] not in ('short','descriptive'):raise ValueError('Invalid title_style')
        if resolved['details_presentation'] not in ('inline','linked','disclosure'):raise ValueError('Invalid details_presentation')
        if resolved['legacy_style'] not in ('catalog','boutique','specifications'):raise ValueError('Invalid legacy_style')
        supported_details={'legacy-catalog':{'inline'},'department-market':{'inline','disclosure'},'editorial-boutique':{'linked'},'technical-catalog':{'disclosure'},'dense-storefront':{'disclosure'}}
        if resolved['details_presentation'] not in supported_details[design]:raise ValueError('Unsupported detail mode for this design')
        if design!='legacy-catalog':
            if 'legacy_style' in configured:raise ValueError('legacy_style belongs to legacy-catalog only')
            resolved.pop('legacy_style')
        result[site]=design;settings[site]=resolved
    return result,settings
