"""Public-corpus facets. OR within a choice facet; AND across facets and ranges."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json
from environments.shopping_intent.catalog import FAMILIES


def token(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def describe(variants):
    by_key=defaultdict(list)
    for v in variants:
        for key,value in v['facts'].items():by_key[key].append((v['family'],value))
    result={}
    for key,rows in by_key.items():
        attributes=[next((a for a in FAMILIES[f].attributes if a.key==key),None) for f,_ in rows]
        values=[]
        for _,value in rows:
            for x in value if isinstance(value,list) else [value]:
                if token(x) not in [token(y) for y in values]:values.append(x)
        values.sort(key=lambda v:(0,v) if type(v) in (int,float) else (1,str(v).casefold()))
        numeric=values and all(type(v) in (int,float) for v in values)
        kind='range' if numeric and all(a is not None and a.operator in ('ge','le') for a in attributes) else 'choice'
        if values and all(type(v) is bool for v in values):kind='boolean'
        # A complete supplied ingredient/compatibility list supports absence tests.
        excludes=all(a is not None and a.operator=='excludes' for a in attributes)
        result[key]={'kind':kind,'values':values,'exclude':excludes,'family':rows[0][0]}
    return result


def finite_decimal(text):
    try:value=Decimal(text)
    except (InvalidOperation,ValueError):raise ValueError('Expected numeric bound') from None
    if not value.is_finite():raise ValueError('Finite numeric bound required')
    return value


def compile_filters(query,facets):
    checks=[];bounds={}
    for param,raw in query.items():
        if '.' not in param:continue
        op,key=param.split('.',1)
        if op not in ('f','x','min','max') or key not in facets:raise ValueError('Unknown product facet')
        facet=facets[key]
        if op in ('f','x'):
            selected=raw if isinstance(raw,list) else [raw]
            if selected==['']:continue
            if not selected or len(selected)>50 or len(set(selected))!=len(selected):raise ValueError('Invalid facet selection')
            allowed={token(v) for v in facet['values']}
            if not set(selected)<=allowed:raise ValueError('Value not in this public corpus')
            if op=='x' and not facet['exclude']:raise ValueError('Exclusion not supported for this attribute')
            if op=='f' and facet['kind']=='range':raise ValueError('Use numeric bounds')
            checks.append((op,key,set(selected)))
        else:
            if raw=='':continue
            if facet['kind']!='range' or not isinstance(raw,str):raise ValueError('Range not supported')
            value=finite_decimal(raw);bounds.setdefault(key,{})[op]=value;checks.append((op,key,value))
    for b in bounds.values():
        if 'min' in b and 'max' in b and b['min']>b['max']:raise ValueError('Reversed range')
    return checks


def matches(facts,checks):
    for op,key,want in checks:
        if key not in facts:return False  # Unknown is not evidence of absence.
        value=facts[key]
        if op in ('f','x'):
            have={token(v) for v in value} if isinstance(value,list) else {token(value)}
            if op=='f' and not have&want:return False
            if op=='x' and have&want:return False
        else:
            if type(value) not in (int,float):return False
            numeric=Decimal(str(value))
            if op=='min' and numeric<want or op=='max' and numeric>want:return False
    return True
