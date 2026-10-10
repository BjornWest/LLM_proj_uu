"""Executable v1 product-context authoring packages; isolated from live sites.

Finite typed sampling, safe expressions, explicit constraints/variants and fact-bound
language. Existing population, reviews, stock and shipping modules remain consumers.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import NormalDist
from string import Formatter

from .product_expressions import (Expression, ExpressionError, UNKNOWN, NOT_APPLICABLE,
                                  Unresolved, unresolved, get_path, set_path, kind, compatible)

VERSION = 'product-package-v1'
ALGORITHM = 'product-package-sampling-v1'
METHODS = {'weighted_choice', 'weighted_subset', 'uniform_choice', 'uniform_int', 'uniform', 'normal', 'rating', 'review_topics'}


class PackageError(ValueError):
    pass


def dumpable(value):
    if unresolved(value):
        return {'status': value.reason}
    if isinstance(value, dict):
        return {k: dumpable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [dumpable(v) for v in value]
    if isinstance(value, set):
        return sorted((dumpable(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def validate_value(value, definition, path):
    if unresolved(value):
        return
    typ = definition['type']
    valid = {'boolean': lambda v: isinstance(v, bool),
             'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
             'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
             'string': lambda v: isinstance(v, str), 'enum': lambda v: v in definition['values'],
             'array': lambda v: isinstance(v, list), 'set': lambda v: isinstance(v, (list, set)),
             'object': lambda v: isinstance(v, dict)}
    if typ not in valid or not valid[typ](value):
        raise PackageError(f'{path}: invalid {typ} value {value!r}')
    if typ in ('number', 'integer'):
        if 'min' in definition and value < definition['min'] or 'max' in definition and value > definition['max']:
            raise PackageError(f'{path}: outside declared domain')
    if typ in ('array', 'set'):
        if len(value) < definition.get('min_items', 0) or len(value) > definition.get('max_items', 10000):
            raise PackageError(f'{path}: invalid collection size')
        if typ == 'set' and len({json.dumps(dumpable(v), sort_keys=True) for v in value}) != len(value):
            raise PackageError(f'{path}: set contains duplicates')
        for item in value:
            validate_value(item, definition['items'], path+'[]')
    if typ == 'object' and 'properties' in definition:
        if set(value) != set(definition['properties']):
            raise PackageError(f'{path}: object members do not match declared fields')
        for key, d in definition['properties'].items():
            validate_value(value[key], d, path+'.'+key)


def load_document(path, *, allowed_root=None, seen=()):
    path = Path(path).resolve()
    root = path.parent if allowed_root is None else Path(allowed_root).resolve()
    if not path.is_relative_to(root):
        raise PackageError('Package import escapes its authoring directory')
    if path in seen:
        raise PackageError('Cyclic package inheritance')
    def unique_pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise PackageError(f'Duplicate JSON key {key}')
            result[key] = value
        return result
    document = json.loads(path.read_text(), object_pairs_hook=unique_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(PackageError(f'Nonfinite JSON {x}')))
    if 'extends' not in document:
        return document
    parent = load_document(path.parent/document['extends'], allowed_root=root, seen=(*seen, path))
    merged = {**parent, **document}
    merged['fields'] = {**parent.get('fields', {}), **document.get('fields', {})}
    replacements = document.get('replace_steps', {})
    inherited = parent.get('steps', [])
    if set(replacements)-{s['id'] for s in inherited}:
        raise PackageError('Replacement references an unknown inherited step')
    merged['steps'] = [replacements.get(s['id'], s) for s in inherited] + document.get('steps', [])
    for key in ('rules', 'language', 'bindings'):
        merged[key] = parent.get(key, []) + document.get(key, [])
    return merged


class ProductPackage:
    def __init__(self, document):
        self.document = deepcopy(document)
        if document.get('schema_version') != VERSION:
            raise PackageError('Unsupported package schema version')
        if not isinstance(document.get('concept_id'), str) or not document['concept_id']:
            raise PackageError('Package needs a concept identity')
        self.fields = deepcopy(document.get('fields', {}))
        self.expressions = {}
        self.producers = {}
        self._ids = set()
        for path, definition in list(self.fields.items()):
            if not isinstance(definition, dict) or definition.get('type') not in {'boolean', 'integer', 'number', 'string', 'enum', 'array', 'set', 'object'}:
                raise PackageError(f'Invalid field definition {path}')
            if definition['type'] == 'enum' and (not definition.get('values') or len(set(definition['values'])) != len(definition['values'])):
                raise PackageError(f'Invalid enum domain {path}')
            if definition['type'] in ('array', 'set') and not isinstance(definition.get('items'), dict):
                raise PackageError(f'Missing collection item type {path}')
            if 'retail_presentation' in definition:
                roles = definition['retail_presentation']['allowed']
                if not roles or set(roles)-{'selector', 'separate_page', 'description'}:
                    raise PackageError('Invalid retail presentation roles')
            self._flatten(path, definition)
        for path, definition in self.fields.items():
            if 'constant' in definition:
                validate_value(definition['constant'], definition, path)
                self._claim(path, 'constant:'+path)
            if definition.get('input') and 'constant' in definition:
                raise PackageError('Field cannot be both input and constant')
            if definition.get('input'):
                self._claim(path, 'input:'+path)
            if 'applicable_when' in definition:
                self._condition(definition['applicable_when'])
        self._validate_steps(document.get('steps', []), loop=False)
        self._check_dependencies(document.get('steps', []),
                                 {p for p, f in self.fields.items() if f.get('input') or 'constant' in f})
        for rule in document.get('rules', []):
            self._condition(rule['require'])
            if 'when' in rule:
                self._condition(rule['when'])
        self._validate_language()
        for binding in document.get('bindings', []):
            if binding.get('role') not in {'task_requirement', 'memory_preference', 'store_affinity', 'filter', 'shipping_class'}:
                raise PackageError('Invalid world binding role')
            self._condition(binding['predicate'])
        self._validate_presentation()
        self.programs = {}
        for name, child in document.get('programs', {}).items():
            if not isinstance(name, str) or not isinstance(child, dict) or 'programs' in child:
                raise PackageError('Programs are named, self-contained, single-level stages')
            child = {'schema_version': VERSION, 'concept_id': document['concept_id'], **child}
            if child['concept_id'] != document['concept_id']:
                raise PackageError('A stage cannot change concept identity')
            self.programs[name] = ProductPackage(child)

    @classmethod
    def load(cls, path, **kwargs):
        return cls(load_document(path, **kwargs))

    def _flatten(self, path, definition):
        for key, child in definition.get('properties', {}).items():
            subpath = path+'.'+key
            if subpath in self.fields:
                raise PackageError(f'Duplicate object field declaration {subpath}')
            self.fields[subpath] = deepcopy(child)
            self._flatten(subpath, child)

    def expression(self, text):
        if text not in self.expressions:
            self.expressions[text] = Expression(text, self.fields)
        return self.expressions[text]

    def _condition(self, text):
        if self.expression(text).result_kind.name != 'boolean':
            raise PackageError('Condition must be boolean')

    def _claim(self, path, producer):
        if path not in self.fields:
            raise PackageError(f'Undeclared target {path}')
        for other in self.producers:
            if path == other or path.startswith(other+'.') or other.startswith(path+'.'):
                raise PackageError(f'Overlapping producers: {path} and {other}')
        self.producers[path] = producer

    def _compile_parameters(self, step, target_definition=None):
        target_definition = target_definition or self.fields.get(step.get('target'))
        for key in ('min', 'max', 'mean', 'sd', 'round_to', 'execution', 'concentration'):
            if isinstance(step.get(key), str):
                result = self.expression(step[key]).result_kind
                if not result.numeric:
                    raise PackageError(f'Numeric parameter expected: {key}')
                expected = kind({'type': 'number'}) if key in ('execution', 'concentration') else kind(target_definition) if target_definition else None
                if expected and not compatible(result, expected):
                    raise PackageError(f'Parameter units do not match target: {key}')
        for key in ('weights_from', 'values_from', 'domain_from', 'eligible_from', 'count_from'):
            if key in step:
                self.expression(step[key])
        for adjustment in step.get('adjustments', []):
            self._condition(adjustment['when'])
            if set(adjustment.get('multiply', {}))-set(step.get('weights', {})) and 'weights_from' not in step:
                raise PackageError('Adjustment references an unknown option')
            self._weights(adjustment['multiply'], allow_zero=True)
        for case in step.get('cases', []):
            allowed = {'when', 'min', 'max', 'mean', 'sd', 'round_to', 'bounds_mode',
                       'weights', 'weights_from', 'values', 'values_from', 'values_expr',
                       'count_weights', 'count_from', 'eligible_from', 'adjustments',
                       'execution', 'concentration', 'length_weights', 'topic_config', 'topic_multipliers'}
            if set(case) - allowed:
                raise PackageError('Conditional cases may only override distribution parameters')
            self._condition(case['when'])
            self._compile_parameters({k: v for k, v in case.items() if k != 'when'}, target_definition)
        for text in step.get('values_expr', {}).values():
            self.expression(text)

    def _validate_steps(self, steps, loop):
        for step in steps:
            sid = step.get('id')
            if not isinstance(sid, str) or not sid or sid in self._ids:
                raise PackageError('Missing or duplicate step ID')
            self._ids.add(sid)
            common = {'id', 'target', 'stream', 'streams', 'when', 'sample', 'derive', 'for_each', 'steps', 'emit',
                      'min', 'max', 'mean', 'sd', 'round_to', 'bounds_mode', 'weights', 'weights_from', 'values', 'values_expr',
                      'values_from', 'count_weights', 'count_from', 'eligible_from', 'adjustments', 'cases',
                      'execution', 'concentration', 'positioning_from', 'length_weights', 'topic_config', 'topic_multipliers'}
            if set(step) - common:
                raise PackageError(f'Unknown draw keys: {sorted(set(step)-common)}')
            if sum(key in step for key in ('sample', 'derive', 'emit', 'for_each')) != 1:
                raise PackageError('Each step has exactly one sampling, derivation, emit or loop operation')
            if 'when' in step:
                self._condition(step['when'])
            if 'for_each' in step:
                each = step['for_each']
                binding = each['binding']
                if not binding.startswith('group.') or binding not in self.fields:
                    raise PackageError('Loop binding must be a declared group field')
                source = self.expression(each['from']).result_kind
                if source.name not in ('array', 'set'):
                    raise PackageError('Loop source must be a collection')
                self._claim(binding, sid)
                self._validate_steps(step['steps'], loop=True)
                continue
            target = step.get('target')
            self._claim(target, sid)
            definition = self.fields[target]
            if 'emit' in step:
                if not loop or definition['type'] != 'array':
                    raise PackageError('emit requires a loop and array target')
                for text in step['emit'].values():
                    self.expression(text)
                continue
            if loop and not target.startswith('group.'):
                raise PackageError('Loop draws may only write local group fields; use emit for global records')
            if 'derive' in step:
                result = self.expression(step['derive']).result_kind
                if not compatible(result, kind(definition)):
                    raise PackageError(f'Derivation has incompatible target type/units: {target}')
            elif step.get('sample') not in METHODS:
                raise PackageError(f'Unknown sampler {step.get("sample")}')
            else:
                self._compile_parameters(step)
                if 'weights' in step:
                    self._weights(step['weights'])
                if step.get('sample') == 'weighted_choice':
                    if 'weights' not in step and 'weights_from' not in step:
                        raise PackageError('Choice needs weights')
                    values = step.get('values', step.get('values_expr'))
                    if values is not None and 'weights' in step and set(values) != set(step['weights']):
                        raise PackageError('Joint value mapping must cover every option exactly')
                    if 'values' in step:
                        for value in step['values'].values():
                            validate_value(value, definition, target)
                if step.get('sample') == 'weighted_subset':
                    if definition['type'] != 'set':
                        raise PackageError('weighted_subset target must be a set')
                    if ('count_weights' in step) == ('count_from' in step):
                        raise PackageError('Subset needs exactly one count_weights or count_from')
                    if 'count_weights' in step:
                        self._counts(step['count_weights'])
                    if 'count_weights' in step and 'weights' in step and max(int(k) for k, v in step['count_weights'].items() if v > 0) > sum(v > 0 for v in step['weights'].values()):
                        raise PackageError('Subset count exceeds eligible pool')
                if step.get('sample') in ('uniform_int', 'uniform', 'normal'):
                    if not kind(definition).numeric:
                        raise PackageError('Numeric sampler needs numeric target')
                    required = ('min', 'max', 'mean', 'sd', 'bounds_mode', 'round_to') if step['sample'] == 'normal' else ('min', 'max')
                    if any(key not in step for key in required):
                        raise PackageError('Missing numeric distribution parameter')
                    if step['sample'] == 'normal' and step['bounds_mode'] not in ('clip', 'truncate'):
                        raise PackageError('Explicit normal bounding mode required')
                if step['sample'] == 'rating':
                    if definition['type'] != 'integer' or not {'execution', 'concentration'} <= set(step):
                        raise PackageError('rating requires integer target, execution and concentration')
                if step['sample'] == 'review_topics':
                    if definition['type'] != 'set' or not {'execution', 'positioning_from', 'eligible_from', 'length_weights'} <= set(step):
                        raise PackageError('review_topics requires a set, profile, eligible topics and length weights')
                    self.expression(step['positioning_from'])
            if 'when' in step:
                self._condition(step['when'])

    def _step_refs(self, step):
        refs = set()
        for key in ('derive', 'when', 'weights_from', 'values_from', 'eligible_from', 'count_from', 'positioning_from'):
            if key in step:
                refs |= self.expression(step[key]).references
        for key in ('min', 'max', 'mean', 'sd', 'round_to', 'execution', 'concentration'):
            if isinstance(step.get(key), str):
                refs |= self.expression(step[key]).references
        for adjustment in step.get('adjustments', []):
            refs |= self.expression(adjustment['when']).references
        for case in step.get('cases', []):
            refs |= self._step_refs(case)
        for text in (*step.get('values_expr', {}).values(), *step.get('emit', {}).values()):
            refs |= self.expression(text).references
        target = step.get('target')
        if target and 'applicable_when' in self.fields[target]:
            refs |= self.expression(self.fields[target]['applicable_when']).references
        return refs

    @staticmethod
    def _available(path, available):
        return any(path == p or path.startswith(p+'.') for p in available)

    def _check_dependencies(self, steps, available):
        available = set(available)
        for step in steps:
            if 'for_each' in step:
                each = step['for_each']
                refs = self.expression(each['from']).references | (self.expression(step['when']).references if 'when' in step else set())
                if any(not self._available(p, available) for p in refs):
                    raise PackageError(f'{step["id"]}: unresolved loop source/order')
                nested = self._check_dependencies(step['steps'], available | {each['binding']})
                available |= {p for p in nested if not p.startswith('group.')}
            else:
                missing = [p for p in self._step_refs(step) if not self._available(p, available)]
                if missing:
                    raise PackageError(f'{step["id"]}: missing/cyclic/later dependencies {missing}')
                available.add(step['target'])
        return available

    @staticmethod
    def _weights(weights, *, allow_zero=False):
        if not isinstance(weights, dict) or not weights or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in weights.values()):
            raise PackageError('Weights must be finite nonnegative numbers')
        if not allow_zero and sum(weights.values()) <= 0:
            raise PackageError('Weights have no positive mass')
        return weights

    def _counts(self, weights):
        self._weights(weights)
        if any(not isinstance(k, str) or not k.isdecimal() or str(int(k)) != k for k in weights):
            raise PackageError('Counts must be canonical nonnegative integer keys')

    def _validate_language(self):
        ids = set()
        for pool in self.document.get('language', []):
            if pool['id'] in ids:
                raise PackageError('Duplicate language-pool ID')
            ids.add(pool['id'])
            meaning = pool.get('meaning', {})
            if meaning.get('kind') not in {'catalog_fact', 'customer_experience', 'task_requirement', 'memory_preference', 'name'}:
                raise PackageError('Explicit language meaning kind required')
            if meaning['kind'] == 'customer_experience' and not {'aspect', 'polarity', 'context', 'source'} <= set(meaning):
                raise PackageError('Experience needs aspect, polarity, context and provenance')
            if 'predicate' in meaning:
                self._condition(meaning['predicate'])
            if 'when' in pool:
                self._condition(pool['when'])
            slots = pool.get('slots', {})
            for text in slots.values():
                self.expression(text)
            if not pool.get('formulations'):
                raise PackageError('Empty formulation pool')
            used_slots = set()
            for form in pool['formulations']:
                text = form if isinstance(form, str) else form['text']
                fields = list(Formatter().parse(text))
                names = {f for _, f, _, _ in fields if f is not None}
                used_slots |= names
                if names - set(slots) or any(conv or (fmt and (fmt != 'g' or not self.expression(slots[name]).result_kind.numeric)) for _, name, fmt, conv in fields if name is not None):
                    raise PackageError('Formulation slots require simple typed bindings')
                if any('.' in name or '[' in name or name.startswith('_') for name in slots):
                    raise PackageError('Template slots are simple names, never attribute expressions')
                weight = 1 if isinstance(form, str) else form.get('weight', 1)
                self._weights({'form': weight}, allow_zero=True)
            if used_slots != set(slots):
                raise PackageError('Unused formulation slot binding')
            self._weights({str(i): 1 if isinstance(f, str) else f.get('weight', 1) for i, f in enumerate(pool['formulations'])})

    def _validate_presentation(self):
        for path, field in self.fields.items():
            if 'retail_presentation' in field and not path.startswith(('product.', 'sku.')):
                raise PackageError('Retail content may only bind public product/SKU fields')

    def rng(self, seed, key):
        namespace = self.document.get('random_namespace', ALGORITHM)
        return random.Random(int.from_bytes(hashlib.sha256(f'{namespace}/{seed}/{key}'.encode()).digest(), 'big'))

    def _eval(self, text, context):
        return self.expression(text).evaluate(context, strict=True)

    def _numeric(self, value, context):
        result = self._eval(value, context) if isinstance(value, str) else value
        if isinstance(result, bool) or not isinstance(result, (int, float)) or not math.isfinite(result):
            raise PackageError('Distribution parameter must be a finite number')
        return result

    def resolve(self, step, context):
        params = deepcopy(step)
        matches = [c for c in params.get('cases', []) if self._eval(c['when'], context)]
        if len(matches) > 1:
            raise PackageError('Multiple conditional parameter cases match')
        if matches:
            params.update({k: v for k, v in matches[0].items() if k != 'when'})
        for key in ('min', 'max', 'mean', 'sd', 'round_to', 'execution', 'concentration'):
            if key in params:
                params[key] = self._numeric(params[key], context)
        if 'weights_from' in params:
            params['weights'] = deepcopy(self._eval(params['weights_from'], context))
        if 'values_from' in params:
            params['resolved_values'] = self._eval(params['values_from'], context)
        if 'weights' in params:
            weights = dict(self._weights(params['weights']))
            if 'eligible_from' in params:
                eligible = self._eval(params['eligible_from'], context)
                if not isinstance(eligible, (list, set)) or len(eligible) != len(set(eligible)) or set(eligible)-set(weights):
                    raise PackageError('Invalid eligible option pool')
                weights = {k: weights[k] for k in eligible}
            for adjustment in params.get('adjustments', []):
                if set(adjustment['multiply'])-set(weights):
                    raise PackageError('Adjustment references unknown resolved option')
                if self._eval(adjustment['when'], context):
                    weights = {k: v*adjustment['multiply'].get(k, 1) for k, v in weights.items()}
            self._weights(weights)
            params['effective_weights'] = weights
            total = sum(weights.values())
            params['probabilities'] = {k: v/total for k, v in weights.items()}
        return params

    def draw(self, params, seed, stream, context):
        method = params['sample']
        random = self.rng(seed, stream)
        record = {'method': method, 'stream': stream, 'algorithm': ALGORITHM}
        if method == 'weighted_choice':
            weights = params['effective_weights']
            key = random.choices(list(weights), weights=list(weights.values()))[0]
            if 'values_expr' in params:
                value = self._eval(params['values_expr'][key], context)
            else:
                value = deepcopy(params.get('values', {}).get(key, key))
            record.update(option=key, probabilities=params['probabilities'])
        elif method == 'weighted_subset':
            counts = params.get('count_weights')
            weights = dict(params['effective_weights'])
            eligible = sum(v > 0 for v in weights.values())
            if counts is not None:
                self._counts(counts)
                maximum = max(int(k) for k, v in counts.items() if v > 0)
            else:
                maximum = self._eval(params['count_from'], context)
                if type(maximum) is not int or maximum < 0:
                    raise PackageError('Subset count_from must resolve to nonnegative integer')
            if maximum > eligible:
                raise PackageError('Subset count exceeds resolved eligible pool')
            streams = params.get('streams', {})
            count_stream = streams.get('count', stream+'/count').format(**context.get('group', {}))
            count = int(self.rng(seed, count_stream).choices(list(counts), weights=list(counts.values()))[0]) if counts is not None else maximum
            value, selections = [], []
            for i in range(count):
                total = sum(weights.values())
                probs = {k: v/total for k, v in weights.items()}
                item_stream = streams.get('item', stream+'/item_{index}').format(index=i, **context.get('group', {}))
                key = self.rng(seed, item_stream).choices(list(weights), weights=list(weights.values()))[0]
                selections.append({'stream': item_stream, 'selected': key, 'conditional_probabilities': probs})
                value.append(key); del weights[key]
            record.update(count=count, count_probabilities={k: v/sum(counts.values()) for k, v in counts.items()} if counts else None, selections=selections)
            # Authoring representation is a canonical unordered set. In the pilot
            # compatibility adapter, trace selections restore legacy loop order.
            record['result_semantics'] = 'unordered_set; selection_order_is_not_priority'
            value.sort()
        elif method == 'uniform_choice':
            options = params['resolved_values']
            if not isinstance(options, list) or not options or len(options) > 10000:
                raise PackageError('uniform_choice needs a bounded nonempty list')
            value = deepcopy(random.choice(options))
            record.update(option_count=len(options), probability=1/len(options))
        elif method == 'rating':
            from .review_rating_sampling import sample_rating
            details = sample_rating(random, params['execution'], params['concentration'])
            value = details['rating']; record.update(details)
        elif method == 'review_topics':
            from .review_topic_sampling import topic_policy
            eligible = self._eval(params['eligible_from'], context)
            policy = topic_policy(positioning=self._eval(params['positioning_from'], context),
                                  execution=params['execution'], eligible=eligible,
                                  length_weights=params['length_weights'], config=params.get('topic_config'),
                                  topic_multipliers=params.get('topic_multipliers'))
            lengths = params['length_weights']
            length = int(self.rng(seed, stream+'/length').choices(list(lengths), weights=list(lengths.values()))[0])
            weights = {k: v for k, v in policy['effective_weights'].items() if k != 'value'}
            value = []
            if length and 'value' in eligible and self.rng(seed, stream+'/value').random() < policy['value_probability_given_comment']:
                value.append('value')
            for i in range(length-len(value)):
                topic = self.rng(seed, stream+f'/other/{i}').choices(list(weights), weights=list(weights.values()))[0]
                value.append(topic); del weights[topic]
            value.sort(); record.update(policy=policy, length=length)
        else:
            lo, hi = params['min'], params['max']
            if lo > hi:
                raise PackageError('Reversed distribution bounds')
            if method == 'uniform_int':
                if type(lo) is not int or type(hi) is not int:
                    raise PackageError('Integer bounds required')
                value = random.randint(lo, hi)
                record['probability'] = 1/(hi-lo+1)
            elif method == 'uniform':
                value = random.uniform(lo, hi)
            elif method == 'normal':
                sd, mean = params['sd'], params['mean']
                if sd <= 0 or lo >= hi:
                    raise PackageError('Normal requires positive spread and interval')
                if params['bounds_mode'] == 'clip':
                    value = max(lo, min(hi, random.gauss(mean, sd)))
                else:
                    dist = NormalDist(mean, sd)
                    a, b = dist.cdf(lo), dist.cdf(hi)
                    if b-a <= 1e-15:
                        raise PackageError('Truncated interval has insufficient numeric probability mass')
                    p = max(1e-15, min(1-1e-15, random.uniform(a, b)))
                    value = max(lo, min(hi, dist.inv_cdf(p)))
                record.update(mean=mean, sd=sd, bounds_mode=params['bounds_mode'])
            record.update(min=lo, max=hi, raw=value)
            increment = params.get('round_to')
            if increment is not None:
                if increment <= 0:
                    raise PackageError('Rounding increment must be positive')
                value = round(value/increment)*increment
                if not lo <= value <= hi:
                    raise PackageError('Quantized result outside bounds; fix range/grid')
                record.update(round_to=increment, rounding='nearest_ties_to_even_after_bounding')
        record['outcome'] = dumpable(value)
        return value, record

    def sample(self, seed, *, inputs=None, overrides=None):
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise PackageError('Seed must be a nonnegative integer')
        context = deepcopy(inputs or {})
        overrides = overrides or {}
        if set(overrides)-set(self.producers):
            raise PackageError('Override references an unknown generated field')
        trace, statuses = [], {}
        for path, definition in self.fields.items():
            if definition.get('input'):
                value = get_path(context, path)
                if unresolved(value) and not definition.get('optional'):
                    raise PackageError(f'Missing required input {path}')
                validate_value(value, definition, path)
            if 'constant' in definition:
                set_path(context, path, deepcopy(definition['constant']))
        def run(steps, indices=()):
            for step in steps:
                sid = step['id']
                if 'for_each' in step:
                    if 'when' in step and not self._eval(step['when'], context):
                        continue
                    each = step['for_each']
                    values = self._eval(each['from'], context)
                    if not isinstance(values, (list, set)) or len(values) > 10000:
                        raise PackageError('Loop source must be a bounded collection')
                    saved = deepcopy(context.get('group', {}))
                    values = sorted(values) if isinstance(values, set) else list(values)
                    for i, value in enumerate(values):
                        context['group'] = deepcopy(saved)
                        validate_value(value, self.fields[each['binding']], each['binding'])
                        set_path(context, each['binding'], value)
                        run(step['steps'], (*indices, i))
                    context['group'] = saved
                    continue
                target = step['target']; definition = self.fields[target]
                conditions = [c for c in (definition.get('applicable_when'), step.get('when')) if c is not None]
                if conditions and not all(self._eval(c, context) for c in conditions):
                    set_path(context, target, NOT_APPLICABLE)
                    statuses[target] = 'not_applicable'
                    trace.append({'id': sid, 'target': target, 'status': 'not_applicable'})
                    continue
                key = step.get('stream', sid)
                if '{' in key:
                    key = key.format(**context.get('group', {}))
                elif indices:
                    key += '/'+'/'.join(map(str, indices))
                if 'emit' in step:
                    value = {k: self._eval(v, context) for k, v in step['emit'].items()}
                    validate_value(value, definition['items'], target+'[]')
                    rows = get_path(context, target)
                    if unresolved(rows):
                        rows = []; set_path(context, target, rows)
                    rows.append(value)
                    continue
                if 'derive' in step:
                    value = self._eval(step['derive'], context)
                    record = {'method': 'derive', 'expression': step['derive'], 'inputs': {p: dumpable(get_path(context, p)) for p in self.expression(step['derive']).references}, 'outcome': dumpable(value)}
                else:
                    params = self.resolve(step, context)
                    value, record = self.draw(params, seed, key, context)
                    record['parameters'] = {k: dumpable(v) for k, v in params.items() if k in {'min', 'max', 'mean', 'sd', 'bounds_mode', 'round_to', 'effective_weights'}}
                if target in overrides:
                    record['sampled_before_override'] = dumpable(value)
                    value = deepcopy(overrides[target]); record['overridden'] = True; record['outcome'] = dumpable(value)
                validate_value(value, definition, target)
                set_path(context, target, value)
                statuses[target] = 'unknown' if value in definition.get('unknown_values', []) else 'known'
                record.update(id=sid, target=target)
                trace.append(record)
        run(self.document.get('steps', []))
        for path, definition in self.fields.items():
            if path.startswith('group.'):
                continue
            value = get_path(context, path)
            if unresolved(value) and path in self.producers and not definition.get('optional') and value is not NOT_APPLICABLE:
                raise PackageError(f'Required producer emitted no value: {path}')
            if not unresolved(value):
                validate_value(value, definition, path)
                statuses.setdefault(path, 'unknown' if value in definition.get('unknown_values', []) else 'known')
        for rule in self.document.get('rules', []):
            if 'when' not in rule or self._eval(rule['when'], context):
                if not self._eval(rule['require'], context):
                    raise PackageError(f'Hard restriction failed: {rule["id"]}; no hidden retries')
        for rows in [v for k, v in context.get('product', {}).items() if k == 'skus']:
            ids = [x['sku_id'] for x in rows]
            if len(ids) != len(set(ids)):
                raise PackageError('Duplicate manufactured SKU identity')
            if any(x.get('product_id') != context['product']['product_id'] for x in rows):
                raise PackageError('SKU references a different product')
        return {'schema_version': VERSION, 'concept_id': self.document['concept_id'],
                'seed': seed, 'entities': dumpable(context), 'field_status': statuses, 'trace': trace,
                'bindings': deepcopy(self.document.get('bindings', []))}

    def formulate(self, pool_id, entities, *, seed, occurrence=0, usage=None):
        pool = next((p for p in self.document.get('language', []) if p['id'] == pool_id), None)
        if pool is None:
            raise PackageError('Unknown meaning/formulation pool')
        if 'when' in pool and not self._eval(pool['when'], entities):
            raise PackageError('Meaning is inapplicable to this context')
        meaning = deepcopy(pool['meaning'])
        if meaning['kind'] == 'catalog_fact' and 'predicate' in meaning and not self._eval(meaning['predicate'], entities):
            raise PackageError('Catalog statement contradicts generated facts')
        forms = pool['formulations']
        weights = {str(i): 1 if isinstance(f, str) else f.get('weight', 1) for i, f in enumerate(forms)}
        if usage is not None:
            weights = {k: w/(1+usage.get((pool_id, int(k)), 0)) for k, w in weights.items()}
        index = int(self.rng(seed, f'language/{pool_id}/{occurrence}').choices(list(weights), weights=list(weights.values()))[0])
        form = forms[index]; text = form if isinstance(form, str) else form['text']
        names = {f for _, f, _, _ in Formatter().parse(text) if f is not None}
        slots = {k: self._eval(pool['slots'][k], entities) for k in names}
        if usage is not None:
            usage[(pool_id, index)] = usage.get((pool_id, index), 0) + 1
        subject = get_path(entities, 'sku.sku_id')
        return {'meaning_id': pool_id, 'meaning': meaning, 'text': text.format(**slots),
                'formulation_id': f'{pool_id}/{index}', 'slot_values': dumpable(slots),
                'sku_id': None if unresolved(subject) else subject}

    def group_listings(self, entities, listings, policy):
        """Canonical SKU grouping includes sold-out listings and sparse grids."""
        canonical = {s['sku_id']: s for s in entities['product']['skus']}
        if len({r['sku_id'] for r in listings}) != len(listings):
            raise PackageError('Duplicate retailer listing')
        variant_fields = {p.split('.', 1)[1]: f for p, f in self.fields.items() if p.startswith('sku.') and 'retail_presentation' in f}
        if set(policy) != set(variant_fields):
            raise PackageError('Policy must cover variant presentation fields')
        for field, mode in policy.items():
            if mode not in variant_fields[field]['retail_presentation']['allowed']:
                raise PackageError('Ineligible retailer presentation')
        groups = {}
        for row in listings:
            if row['sku_id'] not in canonical:
                raise PackageError('Retailer references a nonexistent SKU')
            sku = canonical[row['sku_id']]
            if any(k in row and row[k] != v for k, v in sku.items()):
                raise PackageError('Listing conflicts with canonical SKU facts')
            key = tuple((f, sku[f]) for f, role in sorted(policy.items()) if role == 'separate_page')
            groups.setdefault(key, []).append({**sku, **row})
        return [{'page_key': dict(key), 'selectors': {f: sorted({r[f] for r in rows}) for f, role in policy.items() if role == 'selector'},
                 'listings': rows, 'sold_out': all(r.get('stock', 0) == 0 for r in rows)}
                for key, rows in sorted(groups.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--compile-only', action='store_true')
    parser.add_argument('--program', help='Run a named self-contained stage, e.g. review')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    package = ProductPackage.load(args.package)
    if args.program:
        if args.program not in package.programs:
            parser.error('Unknown package program')
        package = package.programs[args.program]
    if args.compile_only:
        result = {'status': 'compiled', 'concept_id': package.document['concept_id'], 'fields': len(package.fields), 'steps': len(package._ids), 'programs': list(package.programs)}
    else:
        inputs = json.loads(args.inputs.read_text()) if args.inputs else {}
        result = package.sample(args.seed, inputs=inputs)
    raw = json.dumps(result, indent=2, ensure_ascii=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(raw)
    else:
        print(raw, end='')


if __name__ == '__main__':
    main()
