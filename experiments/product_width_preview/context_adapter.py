"""Opt-in private inspector adoption of accepted, source-pinned boundaries.

This module does not register a production generator, task, or browser runtime.
Completed-manufacture checks are separate from sampler-internal partial contexts.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import importlib.util

from environments.product_world.product_expressions import set_path
from environments.product_world.product_package import PackageError

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'product-width-private-context-adapter-v5'
TYPE_BINDINGS = {'sku': 'review.subject', 'product.skus[]': 'review.subject'}
MANUFACTURE_CLASSES = {
    'turner-completed-manufacture-v1': 'TurnersManufactureBoundaryV1',
    'whisk-completed-manufacture-v1': 'WhiskManufactureBoundaryV1',
    'serving-completed-manufacture-v1': 'ServingManufactureBoundaryV1',
    'tong-completed-manufacture-v1': 'TongManufactureBoundaryV1',
}
# These fields are populated by the accepted deterministic preparation steps,
# before rating/topic/sentiment draws. A selected SKU alone is still a partial
# owner context. Direct calls and finished outputs always require completion.
REVIEW_PREPARATION_FIELDS = {
    'tong-completed-manufacture-v1': (
        'subject', 'history_flags', 'cleanup_method', 'use_case', 'food',
        'action', 'residue', 'vessel', 'lock_opened_and_closed', 'eligible',
        'purchase_price_sek', 'price_min_sek', 'price_max_sek',
    ),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_module(path):
    spec = importlib.util.spec_from_file_location('private_preview_' + digest(path), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind(package, acceptance):
    """Bind a freshly compiled private package, preserving its sampled content."""
    requirement = acceptance.get('runtime_context_validation')
    if requirement is None:
        return {'version': VERSION, 'capability': None,
                'scope': 'Existing independently accepted domain; no extra raw-boundary claim.'}
    for path, expected in acceptance['source_hashes'].items():
        if digest(ROOT / path) != expected:
            raise PackageError('Private preview acceptance source changed: ' + path)
    source = ROOT / requirement['boundary_source']
    if digest(source) != requirement['boundary_sha256']:
        raise PackageError('Private preview boundary source changed')
    module = load_module(source)
    capability = requirement['required_capability']
    review_package = package.programs['review']
    if capability in ('product-context-validation-v1', 'product-context-validation-v2'):
        cls = getattr(module, 'ContextBoundaryV2' if capability.endswith('v2') else 'ContextBoundaryV1')
        parent_typed = parent_complete = cls(package)
        # Some accepted programs declare subject members individually rather than
        # an object field. Their pinned caller uses those declarations directly.
        bindings = {source: target for source, target in TYPE_BINDINGS.items()
                    if source.removesuffix('[]') in review_package.fields
                    and target in review_package.fields}
        review_typed = review_complete = cls(review_package, shape_bindings=bindings)
        completed_manufacture = False
    elif capability in MANUFACTURE_CLASSES:
        cls = getattr(module, MANUFACTURE_CLASSES[capability])
        parent_complete = cls(package)
        review_complete = cls(package, program='review')
        parent_typed = module.typed.ContextBoundaryV1(package)
        review_typed = module.typed.ContextBoundaryV1(review_package, shape_bindings=TYPE_BINDINGS)
        completed_manufacture = True
    else:
        raise PackageError('Unsupported private preview context capability: ' + capability)

    semantic_source = requirement.get('semantic_boundary_source')
    if semantic_source is not None:
        if capability != 'product-context-validation-v2':
            raise PackageError('Unsupported semantic boundary/type capability combination')
        semantic_path = ROOT / semantic_source
        if digest(semantic_path) != requirement.get('semantic_boundary_sha256'):
            raise PackageError('Private preview semantic boundary source changed')
        if requirement.get('semantic_boundary_factory') != 'boundary':
            raise PackageError('Unsupported private preview semantic boundary factory')
        semantic_module = load_module(semantic_path)
        parent_typed = parent_complete = semantic_module.boundary(package)
        review_typed = review_complete = semantic_module.boundary(review_package, review=True)

    def validate_complete(boundary, context):
        # Source semantic callers distinguish sampler partials from completed
        # direct inputs. Use their explicit closure when declared by acceptance.
        validator = getattr(boundary, 'validate_complete', boundary.validate)
        validator(context)

    counters = {'parent_partial_evaluations': 0, 'review_partial_evaluations': 0,
                'parent_completed_evaluations': 0,
                'review_completed_evaluations': 0, 'completed_product_outputs': 0,
                'completed_review_outputs': 0}
    original_parent_sample, original_review_sample = package.sample, review_package.sample
    parent_sampling_depth = review_sampling_depth = 0

    def parent_eval(expression, context):
        if parent_sampling_depth:
            counters['parent_partial_evaluations'] += 1
            return parent_typed.eval(expression, context)
        counters['parent_completed_evaluations'] += 1
        validate_complete(parent_complete, context)
        return parent_complete.eval(expression, context)

    def review_eval(expression, context):
        # Selection creates review.subject and sku before topic evaluation.
        # Earlier selection expressions still consume a complete parent menu.
        validate_complete(parent_complete, context)
        prepared = (context.get('review', {}).get('subject') is not None
                    and 'sku' in context)
        if capability in REVIEW_PREPARATION_FIELDS:
            prepared = prepared and all(
                name in context.get('review', {})
                for name in REVIEW_PREPARATION_FIELDS[capability])
        if not review_sampling_depth or prepared:
            counters['review_completed_evaluations'] += 1
            validate_complete(review_complete, context)
            return review_complete.eval(expression, context)
        counters['review_partial_evaluations'] += 1
        return review_typed.eval(expression, context)

    def checked_parent_sample(seed, inputs=None, overrides=None):
        nonlocal parent_sampling_depth
        raw = deepcopy(inputs or {})
        for path, value in (overrides or {}).items():
            set_path(raw, path, deepcopy(value))
        parent_typed.validate(raw)
        parent_sampling_depth += 1
        try:
            result = original_parent_sample(seed, inputs=inputs, overrides=overrides)
        finally:
            parent_sampling_depth -= 1
        validate_complete(parent_complete, result['entities'])
        counters['completed_product_outputs'] += 1
        return result

    def checked_review_sample(seed, inputs=None, overrides=None):
        nonlocal review_sampling_depth
        raw = deepcopy(inputs or {})
        for path, value in (overrides or {}).items():
            set_path(raw, path, deepcopy(value))
        validate_complete(parent_complete, raw)
        review_typed.validate(raw)
        review_sampling_depth += 1
        try:
            result = original_review_sample(seed, inputs=inputs, overrides=overrides)
        finally:
            review_sampling_depth -= 1
        validate_complete(review_complete, result['entities'])
        counters['completed_review_outputs'] += 1
        return result

    package._eval = parent_eval
    package.sample = checked_parent_sample
    package.formulate = parent_complete.formulate
    review_package._eval = review_eval
    review_package.sample = checked_review_sample
    review_package.formulate = review_complete.formulate
    return {'version': VERSION, 'capability': capability,
            'boundary_source': requirement['boundary_source'], 'boundary_sha256': digest(source),
            'parent_snapshot_sha256': parent_complete.snapshot_sha256,
            'review_snapshot_sha256': review_complete.snapshot_sha256,
            'completed_manufacture': completed_manufacture,
            'semantic_boundary_source': semantic_source,
            'semantic_boundary_sha256': digest(ROOT / semantic_source) if semantic_source else None,
            'counts': counters,
            'scope': 'Private inspector only; partial sampler types and completed-context calls are distinct. '
                     'No constant guarantee for V1 and no default/production consumer adoption.'}
