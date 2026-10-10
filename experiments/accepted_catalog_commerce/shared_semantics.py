"""Versioned shared factual stages for a closed commerce-integration slice.

Input/source compilation occurs once. Projection interprets authored status
markers; it does not resample, repair manufacture, or assert generated validity.
"""
from environments.product_world.product_expressions import Expression
from environments.product_world.market_range import stage_document
from environments.product_world.shared_state import mutable
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json

REGISTRATION_PATH = Path(__file__).with_name('shared_semantics_v1.json')


@lru_cache(maxsize=1)
def registration():
    from environments.product_world.shared_state import freeze
    return freeze(json.loads(REGISTRATION_PATH.read_text())['concepts'])


def source_gate(concept_id, *, root, entry):
    """Admit exact accepted facts, not their exhaustive authoring validators.

    Three historic comparison controls resolve only to their declared archived
    bytes. Actual graph parents and every other consumed source remain current.
    """
    declared = registration()[concept_id]
    actual = sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
    if actual != declared['accepted_entry_sha256']:
        raise ValueError('Shared-stage accepted entry changed: ' + concept_id)
    consumed, historical = {}, {}
    for name, expected in declared['source_hashes'].items():
        alias = declared['historical_controls'].get(name)
        path = root / (alias['archive'] if alias else name)
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Shared-stage consumed source changed: ' + name)
        if alias:
            if alias['sha256'] != expected:
                raise ValueError('Historical control identity changed: ' + name)
            historical[name] = mutable(alias)
            consumed[alias['archive']] = expected
        else:
            consumed[name] = expected
    from environments.product_world import market_range, reviewed_feature_publication
    for path in (Path(__file__), REGISTRATION_PATH, Path(market_range.__file__),
                 market_range.POLICY_PATH, Path(reviewed_feature_publication.__file__),
                 reviewed_feature_publication.CATALOGUE / (concept_id + '.json')):
        consumed[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    return {'capability': 'shared_declared_factual_stages_v1',
            'source_hashes': consumed, 'historical_controls': historical,
            'accepted_entry_sha256': actual,
            'qualification': 'Compiled authored facts/reviews plus declared market/status stages; original exhaustive authoring caller guards are not invoked.'}


def prepare_package(document, *, weights=None, validation='off'):
    """Compile once per execution/cache key; share completed facts by identity."""
    from environments.product_world.execution import TraversalPackage
    from environments.product_world.reviewed_feature_publication import load_reviewed_policy
    document, stage = compose_market_stage(document, weights=weights)
    package = TraversalPackage(document, validation=validation)
    projection = StatusProjection(package.fields, load_reviewed_policy(document['concept_id'])['fields'])
    sample = package._sample_trusted
    package._sample_trusted = lambda seed, **kwargs: projection.project(sample(seed, **kwargs))
    return package

MISSING=object()
STATUSES=('known','unknown','not_applicable')

def lookup(context,path):
    for key in path.split('.'):
        if not isinstance(context,dict) or key not in context:return MISSING
        context=context[key]
    return context

def compose_market_stage(document, *, weights=None):
    if not any(s['id']=='market_range' for s in document['steps']):
        return document,None
    stage=stage_document(document['concept_id'],weights=weights)
    return {**document,'fields':{**document['fields'],**stage['fields']},
            'steps':[stage['steps'][0] if s['id']=='market_range' else s for s in document['steps']]},stage

class StatusProjection:
    def __init__(self, fields, policy_fields):
        self.fields=fields
        # Reviewed status declarations include logical applicability and typed
        # sentinel meanings absent from some historical raw graph definitions.
        self.definitions={p:mutable(r['definition']) for p,r in policy_fields.items()}
        for path,d in self.definitions.items():
            # Source product facts and their same-feature SKU declaration share
            # the wire sentinel domain. Borrow only declared sentinel lists.
            counterpart=self.definitions.get('sku.'+path.split('.facts.',1)[1]) if '.facts.' in path else None
            if counterpart:
                for key in ('unknown_values','not_applicable_values'):
                    if key not in d and key in counterpart:d[key]=counterpart[key]
        self.conditions={p:Expression(d['applicable_when'],fields) for p,d in self.definitions.items() if d.get('applicable_when')}

    def status(self,path,value,context,default=None):
        explicit=lookup(context,path+'_status')
        if isinstance(explicit,str) and explicit in STATUSES:return explicit
        if path in self.conditions:
            applicability=self.conditions[path].evaluate(context)
            if applicability is False:return 'not_applicable'
        d=self.definitions.get(path,self.fields.get(path,{}))
        for key,label in [('unknown_values','unknown'),('not_applicable_values','not_applicable')]:
            if any(type(value) is type(v) and value==v for v in d.get(key,[])):return label
        return default if default is not None else 'known'

    def project(self,result):
        # Preserve immutable entities, trace and RNG outcomes by identity.
        entities=result['entities'];statuses=dict(result['field_status'])
        for path in set(statuses)|set(self.definitions):
            value=lookup(entities,path)
            if value is not MISSING:statuses[path]=self.status(path,value,entities,statuses.get(path))
        rows=[]
        for sku in entities['product']['skus']:
            context={**entities,'sku':sku};projected={}
            for path in self.definitions:
                if not path.startswith('sku.'):continue
                value=lookup(context,path)
                if value is MISSING:continue
                projected[path]=self.status(path,value,context)
            rows.append({'sku_id':sku['sku_id'],'statuses':projected})
        return {**result,'field_status':statuses,'typed_status_projection':{
            'schema':'shared-declared-status-projection-v1','manufactured_SKU_status':rows}}
