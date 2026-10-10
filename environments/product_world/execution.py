"""Validation policy for the existing package traversal, not a new graph format.

Compilation and external-input validation remain mandatory. ``off`` omits
generated-output assertions; ``full`` uses the original sampler unchanged.
Use the private trusted-input entry only for outputs owned by this executor.
"""
from string import Formatter
from types import MappingProxyType

from .product_package import (
    ProductPackage, PackageError, VERSION, dumpable, validate_value,
)
from .product_expressions import (
    NOT_APPLICABLE, get_path, unresolved,
)
from .shared_state import WorkingContext, freeze, mutable

MODES = ('off', 'full')


def validation_mode(value):
    if type(value) is not str or value not in MODES:
        raise ValueError('validation must be off or full')
    return value


class TraversalPackage(ProductPackage):
    """Compiled original DSL with separately selectable runtime assertions.

    Samplers, expression evaluation, RNG streams, traces and serialization use
    the original implementation. The loop below preserves its execution order
    while removing output checks in off mode. Compiled definitions are shared
    read-only trees; each sample owns its writes and shares unchanged inputs.
    """

    def __init__(self, document, *, validation='off'):
        self.validation = validation_mode(validation)
        # The legacy compiler expands nested fields in place. Give construction
        # its own editable document once, then seal the compiled definitions.
        super().__init__(mutable(document))
        self.programs = {name: self._adopt(child, self.validation)
                         for name, child in self.programs.items()}
        self._share_compiled()

    def _share_compiled(self):
        if self.validation == 'full':
            return
        if isinstance(self.expressions, MappingProxyType):
            # Per-product views of an already sealed compiler retain the same
            # expression objects without writing back into their shared state.
            self.programs = MappingProxyType(dict(self.programs))
            return
        self.document, self.fields = freeze(self.document), freeze(self.fields)
        for expression in self.expressions.values():
            expression.fields = self.fields
            expression.references = frozenset(expression.references)
        self.expressions = MappingProxyType(dict(self.expressions))
        self.producers = freeze(self.producers)
        self._pools = freeze({p['id']: p for p in self.document.get('language', [])})
        self.programs = MappingProxyType(dict(self.programs))

    @classmethod
    def _adopt(cls, compiled, validation):
        result = cls.__new__(cls)
        result.__dict__ = dict(compiled.__dict__)
        result.validation = validation
        result.programs = {name: cls._adopt(child, validation)
                           for name, child in compiled.programs.items()}
        result._share_compiled()
        return result

    def expression(self, text):
        if self.validation == 'full':
            return super().expression(text)
        # During construction ProductPackage creates the expression inventory.
        if isinstance(self.expressions, dict):
            return super().expression(text)
        if text not in self.expressions:
            raise PackageError('Expression was not compiled: ' + text)
        return self.expressions[text]

    def resolve(self, step, context):
        if self.validation == 'full':
            return super().resolve(step, context)
        # Only these resolved parameters change; nested source tables are shared.
        params = dict(step)
        matches = [c for c in params.get('cases', []) if self._eval(c['when'], context)]
        if len(matches) > 1:
            raise PackageError('Multiple conditional parameter cases match')
        if matches:
            params.update({k: v for k, v in matches[0].items() if k != 'when'})
        for key in ('min', 'max', 'mean', 'sd', 'round_to', 'execution', 'concentration'):
            if key in params:
                params[key] = self._numeric(params[key], context)
        if 'weights_from' in params:
            params['weights'] = self._eval(params['weights_from'], context)
        if 'values_from' in params:
            params['resolved_values'] = self._eval(params['values_from'], context)
        if 'weights' in params:
            weights = dict(self._weights(params['weights']))
            if 'eligible_from' in params:
                eligible = self._eval(params['eligible_from'], context)
                if not isinstance(eligible, (list, set)) or len(eligible) != len(set(eligible)) or set(eligible) - set(weights):
                    raise PackageError('Invalid eligible option pool')
                weights = {k: weights[k] for k in eligible}
            for adjustment in params.get('adjustments', []):
                if set(adjustment['multiply']) - set(weights):
                    raise PackageError('Adjustment references unknown resolved option')
                if self._eval(adjustment['when'], context):
                    weights = {k: v * adjustment['multiply'].get(k, 1) for k, v in weights.items()}
            self._weights(weights)
            params['effective_weights'] = weights
            total = sum(weights.values())
            params['probabilities'] = {k: v / total for k, v in weights.items()}
        return params

    def _inputs(self, seed, inputs, overrides):
        if type(seed) is not int or seed < 0:
            raise PackageError('Seed must be a nonnegative integer')
        if inputs is not None and not isinstance(inputs, dict):
            raise PackageError('Inputs must be an object')
        if overrides is not None and not isinstance(overrides, dict):
            raise PackageError('Overrides must be an object')
        if set(overrides or {}) - set(self.producers):
            raise PackageError('Override references an unknown generated field')
        for path, definition in self.fields.items():
            if not definition.get('input'):
                continue
            value = get_path(inputs or {}, path)
            if unresolved(value) and not definition.get('optional'):
                raise PackageError(f'Missing required input {path}')
            validate_value(value, definition, path)
        for path, value in (overrides or {}).items():
            validate_value(value, self.fields[path], path)

    def sample(self, seed, *, inputs=None, overrides=None):
        self._inputs(seed, inputs, overrides)
        result = self._sample_trusted(seed, inputs=inputs, overrides=overrides)
        # Historical public API returns independently editable values. Internal
        # consumers use the shared completed result directly instead.
        return mutable(result) if self.validation == 'off' else result

    def _sample_trusted(self, seed, *, inputs=None, overrides=None):
        if self.validation == 'full':
            return super().sample(seed, inputs=mutable(inputs), overrides=mutable(overrides))
        working = WorkingContext(inputs)
        context = working.root
        overrides = overrides or {}
        trace, statuses = [], {}
        for path, definition in self.fields.items():
            if 'constant' in definition:
                working.set(path, definition['constant'])

        def run(steps, indices=()):
            for step in steps:
                sid = step['id']
                if 'for_each' in step:
                    if 'when' in step and not self._eval(step['when'], context):
                        continue
                    each = step['for_each']
                    values = self._eval(each['from'], context)
                    saved = freeze(context.get('group', {}))
                    values = sorted(values) if isinstance(values, set) else list(values)
                    for i, value in enumerate(values):
                        working.set('group', saved)
                        working.set(each['binding'], value)
                        run(step['steps'], (*indices, i))
                    working.set('group', saved)
                    continue
                target = step['target']
                definition = self.fields[target]
                conditions = [c for c in (definition.get('applicable_when'), step.get('when'))
                              if c is not None]
                if conditions and not all(self._eval(c, context) for c in conditions):
                    working.set(target, NOT_APPLICABLE)
                    statuses[target] = 'not_applicable'
                    trace.append({'id': sid, 'target': target, 'status': 'not_applicable'})
                    continue
                key = step.get('stream', sid)
                if '{' in key:
                    key = key.format(**context.get('group', {}))
                elif indices:
                    key += '/' + '/'.join(map(str, indices))
                if 'emit' in step:
                    value = {k: self._eval(v, context) for k, v in step['emit'].items()}
                    working.append(target, value)
                    continue
                if 'derive' in step:
                    value = self._eval(step['derive'], context)
                    record = {'method': 'derive', 'expression': step['derive'],
                              'inputs': {p: freeze(get_path(context, p))
                                         for p in self.expression(step['derive']).references},
                              'outcome': freeze(value)}
                else:
                    params = self.resolve(step, context)
                    value, record = self.draw(params, seed, key, context)
                    record['parameters'] = {k: dumpable(v) for k, v in params.items()
                                            if k in {'min', 'max', 'mean', 'sd', 'bounds_mode',
                                                     'round_to', 'effective_weights'}}
                if target in overrides:
                    record['sampled_before_override'] = dumpable(value)
                    value = freeze(overrides[target])
                    record['overridden'] = True
                    record['outcome'] = dumpable(value)
                working.set(target, value)
                statuses[target] = 'unknown' if value in definition.get('unknown_values', []) else 'known'
                record.update(id=sid, target=target)
                trace.append(record)

        run(self.document.get('steps', []))
        # Status calculation is part of exported meaning, not output validation.
        for path, definition in self.fields.items():
            if path.startswith('group.'):
                continue
            value = get_path(context, path)
            if not unresolved(value):
                statuses.setdefault(path, 'unknown' if value in definition.get('unknown_values', []) else 'known')
        return {'schema_version': VERSION, 'concept_id': self.document['concept_id'],
                'seed': seed, 'entities': working.finish(), 'field_status': statuses,
                'trace': trace, 'bindings': self.document.get('bindings', [])}

    def formulate(self, pool_id, entities, *, seed, occurrence=0, usage=None):
        if self.validation == 'full':
            return super().formulate(pool_id, entities, seed=seed, occurrence=occurrence, usage=usage)
        return mutable(self._formulate_trusted(pool_id, entities, seed=seed,
                                              occurrence=occurrence, usage=usage))

    def _formulate_trusted(self, pool_id, entities, *, seed, occurrence=0, usage=None):
        pool = self._pools[pool_id]
        # Caller selects an applicable pool. Its truth assertion is offline QA;
        # reading slots and choosing words are the actual generation operation.
        forms = pool['formulations']
        weights = {str(i): 1 if isinstance(f, str) else f.get('weight', 1)
                   for i, f in enumerate(forms)}
        if usage is not None:
            weights = {k: w / (1 + usage.get((pool_id, int(k)), 0)) for k, w in weights.items()}
        index = int(self.rng(seed, f'language/{pool_id}/{occurrence}').choices(
            list(weights), weights=list(weights.values()))[0])
        form = forms[index]
        text = form if isinstance(form, str) else form['text']
        names = {f for _, f, _, _ in Formatter().parse(text) if f is not None}
        slots = {k: self._eval(pool['slots'][k], entities) for k in names}
        if usage is not None:
            usage[(pool_id, index)] = usage.get((pool_id, index), 0) + 1
        subject = get_path(entities, 'sku.sku_id')
        return {'meaning_id': pool_id, 'meaning': pool['meaning'],
                'text': text.format(**slots), 'formulation_id': f'{pool_id}/{index}',
                'slot_values': dumpable(slots),
                'sku_id': None if unresolved(subject) else subject}
