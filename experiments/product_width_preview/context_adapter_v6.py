"""Additive private-inspector binding to accepted actual consumers.

Original producer inputs are copied before sampling, never inferred from finished
snapshots. The v5 adapter and historical reports remain available. This module
does not promote a shared/default producer or broaden fixture-only acceptances.
"""
from copy import deepcopy

from environments.product_world.product_package import ProductPackage, PackageError
from .context_adapter import ROOT, bind as bind_v5, digest, load_module

VERSION = 'product-width-private-context-adapter-v6'
AUTHORITY_FACTORIES = {'SaucepanCallerV1', 'StockpotCallerV2', 'CasseroleCallerV1'}
COMPLETED_FACTORIES = {'CompletedGraterCallerV2', 'CompletedKnifeCallerV4'}
STRAINER_SOURCE = ('.local/product-width/lane-c/strainers-colanders-price-alias-repair-v1/'
                   'strainers-manufacture-boundary-v1.py')


def _same(left, right):
    """Raw types matter: bool does not authenticate an integer producer input."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def _verify(acceptance, path, declared=None):
    expected = acceptance['source_hashes'].get(path)
    if expected is None or (declared is not None and expected != declared):
        raise PackageError('Private preview source is not pinned by acceptance: ' + path)
    if digest(ROOT / path) != expected:
        raise PackageError('Private preview acceptance source changed: ' + path)
    return expected


def bind(package, acceptance, *, authoritative_inputs):
    requirement = acceptance.get('runtime_context_validation')
    if requirement is None:
        return bind_v5(package, acceptance)
    if requirement.get('private_inspector_supported') is False:
        raise PackageError('Acceptance is fixture-only; arbitrary private-preview identities are unsupported')
    for path, expected in acceptance['source_hashes'].items():
        _verify(acceptance, path, expected)

    factory = requirement.get('actual_class') or requirement.get('semantic_boundary_factory')
    source = requirement.get('semantic_boundary_source')
    is_strainer = requirement['boundary_source'] == STRAINER_SOURCE
    needs_authority = requirement.get('constructor_requires_authoritative_inputs', False)
    if not needs_authority and not is_strainer:
        return bind_v5(package, acceptance)
    if type(authoritative_inputs) is not dict:
        raise PackageError('Private preview requires trusted original producer inputs')
    authority = deepcopy(authoritative_inputs)
    counters = {'completed_product_outputs': 0, 'completed_review_outputs': 0,
                'parent_completed_evaluations': 0, 'review_completed_evaluations': 0}
    review = package.programs['review']
    _verify(acceptance, requirement['boundary_source'], requirement.get('boundary_sha256'))

    def complete(boundary, context):
        getattr(boundary, 'validate_complete', boundary.validate)(context)

    if factory in COMPLETED_FACTORIES:
        if factory == 'CompletedKnifeCallerV4':
            source = requirement['enforced_caller']
            source_sha = _verify(acceptance, source, requirement['caller_sha256'])
        else:
            source_sha = _verify(acceptance, source, requirement['semantic_boundary_sha256'])
        module = load_module(ROOT / source)
        caller = getattr(module, factory)(package, authoritative_inputs=authority)

        def parent_sample(seed, inputs=None, overrides=None):
            if overrides or (inputs is not None and not _same(inputs, authority)):
                raise PackageError('Completed preview caller requires its original inputs without overrides')
            result = caller.sample_product(seed)
            counters['completed_product_outputs'] += 1
            return result

        def review_sample(seed, inputs=None, overrides=None):
            if overrides:
                raise PackageError('Completed preview caller does not expose review overrides')
            result = caller.sample_review(seed, product_context=inputs)
            counters['completed_review_outputs'] += 1
            return result

        def evaluator(program):
            def evaluate(expression, context):
                key = 'parent_completed_evaluations' if program is None else 'review_completed_evaluations'
                counters[key] += 1
                return caller.eval(expression, context, program=program)
            return evaluate

        def formatter(program):
            def formulate(pool_id, context, *, seed, occurrence=0, usage=None):
                return caller.formulate(pool_id, context, program=program, seed=seed,
                                        occurrence=occurrence, usage=usage)
            return formulate

        package.sample, review.sample = parent_sample, review_sample
        package._eval, review._eval = evaluator(None), evaluator('review')
        package.formulate, review.formulate = formatter(None), formatter('review')
    else:
        source = requirement['boundary_source'] if is_strainer else source
        source_sha = _verify(acceptance, source, None if is_strainer else requirement['semantic_boundary_sha256'])
        module = load_module(ROOT / source)
        if factory in AUTHORITY_FACTORIES:
            cls = getattr(module, factory)
            parent = cls(package, authoritative_inputs=authority)
            owner = cls(package, authoritative_inputs=authority, program='review')
            parent_sampler, review_sampler = parent.sample, owner.sample
        elif factory == 'boundary' and needs_authority:
            parent = module.boundary(package, authoritative_inputs=authority)
            owner = module.boundary(review, review=True, authoritative_inputs=authority)
            # Keep the accepted source's partial evaluation/override checks during
            # sampling. Completed direct operations use the separate boundaries.
            sampling_package = ProductPackage(deepcopy(package.document))
            sampling_review = sampling_package.programs['review']
            module.bind_package(sampling_package, authoritative_inputs=authority)
            module.bind_package(sampling_review, review=True, authoritative_inputs=authority)
            parent_sampler, review_sampler = sampling_package.sample, sampling_review.sample
        elif is_strainer:
            factory = 'StrainerManufactureBoundaryV1'
            parent = module.StrainerManufactureBoundaryV1(package)
            owner = module.StrainerManufactureBoundaryV1(package, program='review')
            sampling_package = ProductPackage(deepcopy(package.document))
            parent_sampler = sampling_package.sample
            review_sampler = sampling_package.programs['review'].sample
        else:
            raise PackageError('Unsupported accepted actual private-preview factory: ' + str(factory))

        def parent_sample(seed, inputs=None, overrides=None):
            if is_strainer and overrides:
                raise PackageError('Strainer private preview does not expose partial overrides')
            if is_strainer:
                module.typed.ContextBoundaryV1(sampling_package).validate(authority if inputs is None else inputs)
            result = parent_sampler(seed, inputs=deepcopy(authority if inputs is None else inputs), overrides=overrides)
            complete(parent, result['entities'])
            counters['completed_product_outputs'] += 1
            return result

        def review_sample(seed, inputs=None, overrides=None):
            complete(parent, inputs)
            if is_strainer and overrides:
                raise PackageError('Strainer private preview does not expose partial overrides')
            result = review_sampler(seed, inputs=inputs, overrides=overrides)
            complete(owner, result['entities'])
            counters['completed_review_outputs'] += 1
            return result

        def evaluator(boundary, key):
            def evaluate(expression, context):
                complete(boundary, context)
                counters[key] += 1
                return boundary.eval(expression, context)
            return evaluate

        package.sample, review.sample = parent_sample, review_sample
        package._eval = evaluator(parent, 'parent_completed_evaluations')
        review._eval = evaluator(owner, 'review_completed_evaluations')
        package.formulate, review.formulate = parent.formulate, owner.formulate

    return {'version': VERSION, 'capability': requirement['required_capability'],
            'actual_factory': factory, 'actual_source': source, 'actual_source_sha256': source_sha,
            'original_inputs_bound': needs_authority, 'counts': counters,
            'scope': 'Private inspector only; actual accepted source consumer and original inputs. '
                     'Strainer uses its accepted source/menu boundary without a new identity-authority guarantee. '
                     'Sampler partials are separate from completed direct calls; no production adoption.'}
