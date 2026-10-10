"""Optional exhaustive validation around the frozen commerce producer.

The old producer and accepted callers are unchanged. Each Execution owns its
factory/exporter bindings; no process-wide monkeypatch or environment switch.
The explicit registered slice retains historical five-concept defaults.
Compilation/source/input checks happen at construction/entry.
"""
from copy import deepcopy
import importlib.util
import json
from types import FunctionType, SimpleNamespace

from environments.product_world.execution import TraversalPackage, validation_mode
from environments.product_world.product_package import load_document
from environments.product_world.market_range import stage_document
from environments.product_world import footwear_context_pilot as footwear
from environments.product_world.product_naming import sample_product_name
from environments.product_world.review_population import summarize_ratings
from environments.product_world.shared_state import WorkingContext, freeze, mutable
from environments.product_world.product_expressions import unresolved
from experiments.world_sampling_defaults.execution import PopulationExecution
from . import model, package_export
from .catalog_registry import ADDITIONS, SHARED_ADDITIONS, input_defaults


def _bind(function, **bindings):
    """Reuse a frozen function body with private, explicit dependency bindings.

    Required because the historical producer has no exporter injection point.
    Its source is not rewritten, and its module globals are never modified.
    """
    namespace = {**function.__globals__, **bindings}
    result = FunctionType(function.__code__, namespace, function.__name__,
                          function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


class Execution:
    def __init__(self, *, validation='off'):
        self.validation = validation_mode(validation)
        self.gates = {}
        self.documents = {}
        self.packages = {}
        self._stages = {}
        self._spec = None
        self._tshirt = None
        export = SimpleNamespace(CONCEPTS=package_export.CONCEPTS,
                                 SUPPORTED_CONCEPTS=package_export.SUPPORTED_CONCEPTS,
                                 source_gate=self.source_gate if self.validation == 'full' else self._shared_gate,
                                 sample=self.sample)
        bindings = {'package_export': export,
                    'validate': model.validate if self.validation == 'full' else lambda world: None}
        self.population = None
        if self.validation == 'off':
            self.population = PopulationExecution(_bind)
            pop = self.population.functions
            native = SimpleNamespace(**vars(model.native))
            native.choose_home = _bind(model.native.choose_home, population=pop)
            bindings.update(population=pop, native=native,
                            footwear=SimpleNamespace(**{**vars(footwear), 'load_spec': self._footwear_spec}))
        self._generate = _bind(model.generate, **bindings)

    def _footwear_spec(self):
        if self._spec is None:
            self._spec = freeze(footwear.load_spec())
        return self._spec

    def source_gate(self, concept_id):
        return mutable(self._shared_gate(concept_id))

    def _shared_gate(self, concept_id):
        if concept_id not in self.gates:
            self.gates[concept_id] = freeze(package_export.source_gate(concept_id))
        return self.gates[concept_id]

    def _tshirt_functions(self):
        if self._tshirt is None:
            path = package_export.ROOT / package_export.COMPLETED['tops.t_shirts']
            spec = importlib.util.spec_from_file_location('execution_owned_tshirt', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # original manifest checked once
            # Pure status projection has one provenance digest. Pin it at load;
            # don't turn a status calculation into another disk integrity scan.
            plan = module.A / 'language-plan-v2.json'
            digest = module.digest(plan)
            project = _bind(module.project_status,
                            digest=lambda path: digest if path == plan else module.digest(path))
            self._tshirt = SimpleNamespace(module=module, project=project)
        return self._tshirt

    def _package(self, concept_id, inputs):
        if concept_id not in self.documents:
            self.documents[concept_id] = freeze(load_document(package_export.WIDTH / (concept_id + '.json')))
        if concept_id in SHARED_ADDITIONS:
            from .shared_semantics import prepare_package
            weights = inputs['brand'].get('market_range_weights')
            key = (concept_id, json.dumps(weights, sort_keys=True))
            if key not in self.packages:
                self.packages[key] = prepare_package(self.documents[concept_id],
                    weights=weights, validation=self.validation)
            return self.packages[key]
        if concept_id != 'tops.t_shirts':
            if concept_id not in self.packages:
                self.packages[concept_id] = TraversalPackage(self.documents[concept_id])
            package = self.packages[concept_id]
            return package
        functions = self._tshirt_functions()
        module = functions.module
        original = module._original(inputs)  # defensive raw-input boundary
        weights = original['brand'].get('market_range_weights')
        key = (concept_id, json.dumps(weights, sort_keys=True))
        if key not in self.packages:
            stage = freeze(stage_document(concept_id, weights=weights))
            source = self.documents[concept_id]
            doc = {**source, 'fields': {**source['fields'], **stage['fields']},
                   'steps': [stage['steps'][0] if step['id'] == 'market_range' else step
                             for step in source['steps']]}
            self.packages[key] = TraversalPackage(doc)
            self._stages[key] = stage
        stage = self._stages[key]
        # Only the per-product completion flag and original identity are local;
        # definitions/expressions/review programs remain shared and read-only.
        package = TraversalPackage._adopt(self.packages[key], 'off')
        sample = package._sample_trusted
        completed = False

        def manufacture(seed, *, inputs=None, overrides=None):
            nonlocal completed
            result = sample(seed, inputs=inputs, overrides=overrides)
            # Keep the same factual stage record/status meaning as the original
            # caller. This is recording execution, not reconstructing/checking it.
            rows = [row for row in result['trace'] if row.get('target') == 'product.facts.market_range']
            record = {'schema': 'tshirt-executed-market-stage-v1', 'concept_id': concept_id,
                      'product_id': original['product']['product_id'], 'status': 'known',
                      'value': result['entities']['product']['facts']['market_range'],
                      'stage_document': stage,
                      'stage_sha256': module.sha256(module.json.dumps(stage, sort_keys=True).encode()).hexdigest(),
                      'source_files': freeze(module.STAGE_SOURCE['source_files']),
                      'manifest_sha256': module.STAGE_SOURCE['manifest_sha256'],
                      'trace': deepcopy(rows), 'seed': seed, 'range_draw_count': len(rows)}
            working = WorkingContext(result['entities'])
            working.set('private.market_stage', record)
            result['entities'] = working.finish()
            completed = True
            return functions.project(result)

        def make_review():
            if not completed:
                raise ValueError('Manufacture must precede review sampling')
            reviewer = package.programs['review']
            sample_review = reviewer._sample_trusted
            # Private exporter provides the completed output from this package.
            # No recursive revalidation of its unchanged manufacture is needed.
            result = TraversalPackage._adopt(reviewer, 'off')
            result.sample = lambda seed, *, inputs=None, overrides=None: functions.project(
                sample_review(seed, inputs=inputs, overrides=overrides))
            return result

        package.sample = manufacture
        package._sample_trusted = manufacture
        package.make_review = make_review
        return package

    def _descriptions(self, package, entities, seed):
        rows, projected = [], {}
        projection = package_export.SKU_CONTEXT_PROJECTIONS.get(package.document['concept_id'])
        for pool in package.document['language']:
            if pool['meaning']['kind'] != 'catalog_fact':
                continue
            expressions = [*pool.get('slots', {}).values(), *([pool['when']] if 'when' in pool else [])]
            refs = set().union(*(package.expression(x).references for x in expressions))
            scoped = any(x == 'sku' or x.startswith('sku.') for x in refs)
            for sku in entities['product']['skus'] if scoped else [None]:
                context = entities
                if sku is not None:
                    sid = sku['sku_id']
                    if sid not in projected:
                        projected[sid] = (package.programs[projection]._sample_trusted(seed, inputs={
                            'product': {'product_id': entities['product']['product_id'],
                                        'skus': entities['product']['skus']},
                            'projection': {'subject': sku}})['entities']['sku'] if projection else sku)
                    context = {**entities, 'sku': projected[sid]}
                if 'when' in pool and not package._eval(pool['when'], context):
                    continue
                if package.document['concept_id'] in SHARED_ADDITIONS and any(
                        unresolved(package.expression(value).evaluate(context))
                        for value in pool.get('slots', {}).values()):
                    continue
                formulate = package.formulate if self.validation == 'full' else package._formulate_trusted
                row = formulate(pool['id'], context, seed=seed)
                row.update(subject_type='sku' if scoped else 'product',
                           subject_id=sku['sku_id'] if scoped else entities['product']['product_id'],
                           source_pool_id=pool['id'], mapping_status='unmapped')
                rows.append(row)
        return rows

    def sample(self, *args, **kwargs):
        concept_id = args[1] if len(args) > 1 else kwargs.get('concept_id')
        if self.validation == 'full' and concept_id not in SHARED_ADDITIONS:
            return package_export.sample(*args, **kwargs)
        return self._export_product(*args, **kwargs)

    def _export_product(self, seed, concept_id, brand, product_id, *, earlier=(), review_count=0):
        """Same export data, without the original post-generation join asserts."""
        if type(review_count) is not int or not 0 <= review_count <= 1000:
            raise ValueError('Declare finite review count0..1000')
        if concept_id in package_export.PILOTS:
            return package_export.sample(seed, concept_id, brand, product_id,
                                         earlier=earlier, review_count=review_count)
        gate = self._shared_gate(concept_id)
        if concept_id not in self.documents:
            self.documents[concept_id] = freeze(load_document(package_export.WIDTH / (concept_id + '.json')))
        declared = self.documents[concept_id]['fields']
        inputs = {'brand': {path.split('.')[1]: brand[path.split('.')[1]]
                            for path, definition in declared.items()
                            if path.startswith('brand.') and path.count('.') == 1
                            and definition.get('input') and path.split('.')[1] in brand},
                  'product': {'product_id': product_id}}
        inputs['brand']['eligible_concepts'] = [concept_id]
        if declared.get('product.concept_id', {}).get('input'):
            inputs['product']['concept_id'] = concept_id
        if declared.get('product.name', {}).get('input'):
            inputs['product']['name'] = brand['name'] + ' ' + product_id.split('/')[-1]
        if concept_id in ADDITIONS:
            inputs = input_defaults(self.documents[concept_id], inputs)
        package = self._package(concept_id, inputs)
        # Defensive entry validation once, then share the completed manufacture.
        package._inputs(seed, inputs, None)
        result = package._sample_trusted(seed, inputs=inputs)
        entities = result['entities']
        catalog = dict(entities['product'])
        name, _ = sample_product_name(self._footwear_spec()['product_names'], brand_id=brand['brand_id'],
                                     existing_products=[p['public'] for p in earlier],
                                     rng=footwear.stream(seed, 'commerce-model-name'))
        catalog.setdefault('name', brand['name'] + ' ' + name)
        catalog.setdefault('model_name', name)
        catalog.update(family_id=concept_id.split('.')[0], concept_id=concept_id,
                       concept=concept_id.split('.')[1], brand_id=brand['brand_id'])
        item = {'public': catalog, 'private': {'profiles': entities['profile'],
                'sample': result, 'commerce_source_gate': gate},
                'descriptions': self._descriptions(package, entities, seed), 'reviews': []}
        for index in range(review_count):
            stage = package.make_review() if hasattr(package, 'make_review') else package.programs['review']
            rs = int.from_bytes(package_export.sha256(f'accepted-catalog-review/{seed}/{index}'.encode()).digest()[:4], 'big')
            review = stage._sample_trusted(rs, inputs=entities) if not hasattr(package, 'make_review') else stage.sample(rs, inputs=entities)
            context = review['entities']
            statements = [stage._formulate_trusted(pool['id'], context, seed=rs)
                          for pool in stage.document['language']
                          if 'when' not in pool or stage._eval(pool['when'], context)]
            presentation = footwear.compose_review(rs, product_id + '/review-' + str(index),
                                                   [dict(s, polarity=s['meaning']['polarity']) for s in statements])
            item['reviews'].append({'review_id': product_id + '/review-' + str(index),
                                   'reviewer_id': product_id + '/reviewer-' + str(index),
                                   'sku_id': context['sku']['sku_id'], 'rating': package_export.review_rating(context),
                                   'text': presentation['text'], 'statements': statements,
                                   'presentation': presentation, 'private_trace': review['trace']})
        item['rating_summary'] = summarize_ratings(item['reviews'])
        item['catalog_status'] = {k: deepcopy(v) for k, v in result['field_status'].items()
                                  if k.startswith('product.facts.') or k == 'product.reference_price_sek'}
        typed = result.get('typed_status_projection', {})
        if 'manufactured_SKU_status' in typed:
            item['sku_status'] = {r['sku_id']: deepcopy(r['statuses']) for r in typed['manufactured_SKU_status']}
        elif concept_id in package_export.SKU_CONTEXT_PROJECTIONS:
            item['sku_status'] = {}
            for row in catalog['skus']:
                projected = package.programs[package_export.SKU_CONTEXT_PROJECTIONS[concept_id]]._sample_trusted(seed, inputs={
                    'product': {'product_id': product_id, 'skus': catalog['skus']},
                    'projection': {'subject': row}})
                item['sku_status'][row['sku_id']] = {k: deepcopy(v) for k, v in projected['field_status'].items() if k.startswith('sku.')}
        else:
            item['sku_status'] = {row['sku_id']: {k: deepcopy(v) for k, v in result['field_status'].items() if k.startswith('sku.')}
                                  for row in catalog['skus']}
        item['status_provenance'] = 'accepted caller status projection where declared; otherwise exact compiler/projection output, no inferred status upgrade'
        if concept_id in SHARED_ADDITIONS:
            item['status_provenance'] = 'shared declared logical/sentinel/sibling status projection; manufacture and review RNG outcomes unchanged'
        item['variant_fields'] = {k[4:]: deepcopy(v) for k, v in package.fields.items()
                                  if k.startswith('sku.') and 'retail_presentation' in v}
        item['public_mapping_status'] = 'unmapped_prose; source-bound structured facts/status retained'
        item['commerce'] = {'shipping_class': 'regular', 'classification_basis': 'closed_ordinary_parcel_concept_slice_v1'}
        return item

    def generate(self, seed=0, **kwargs):
        # Public producer validates seed, slice, controls and location before
        # sampling; source gates are cached for this execution instance only.
        world = self._generate(seed, **kwargs)
        # Website consumers retain their existing editable-dictionary interface.
        # Materialize once at that boundary, never once per review/pool/SKU.
        return mutable(world) if self.validation == 'off' else world

    def freeze(self, world, output):
        factory = model.freeze if self.validation == 'full' else _bind(
            model.freeze, validate=lambda world: None)
        return factory(world, output)

    def record(self):
        return {'schema': 'catalog-execution-policy-v1', 'validation': self.validation,
                'compilation_and_external_input_checks': True,
                'source_verification': 'legacy_repeated_checks' if self.validation == 'full' else 'at_package_load',
                'exhaustive_generated_context_checks': self.validation == 'full',
                'shared_compiled_packages': self.validation == 'off',
                'shared_completed_manufacture': self.validation == 'off',
                'population_definitions': 'once_per_execution' if self.validation == 'off' else 'legacy_repeated_loads',
                'shared_factual_stage_concepts': list(SHARED_ADDITIONS),
                'limitations': ['External mutable-world export and primitive parameter guards remain.',
                               'Ported footwear pilots keep their existing internal checks.',
                               'Shared-stage graphs use declared meaning projection; original exhaustive authoring caller guards are not adopted.',
                               'Fixture-only Wok identity and bulky commerce adoption remain separate.']}


def generate(seed=0, *, validation='off', **kwargs):
    return Execution(validation=validation).generate(seed, **kwargs)
