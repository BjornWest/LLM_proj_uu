"""Queryable product design proposals, isolated from live catalog generation.

Run ``python -m environments.product_world.concept_registry --help``.
The JSON files are the editable authority; this module resolves inheritance, validates
references and reports field counts. It does not implement any sampling semantics.
"""
from __future__ import annotations

import argparse
import copy
import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).parent / 'data' / 'concept_registry'
LEVELS = frozenset({'model', 'sku', 'model_or_sku'})
KINDS = frozenset({'categorical', 'integer', 'number', 'boolean', 'set', 'structured'})


class RegistryError(ValueError):
    """The design registry contains an invalid or ambiguous reference."""


def _require(test: bool, message: str) -> None:
    if not test:
        raise RegistryError(message)


def _unique(values: list[str], where: str) -> None:
    _require(isinstance(values, list) and all(isinstance(x, str) and x for x in values),
             f'{where}: expected nonempty string identifiers')
    _require(len(set(values)) == len(values), f'{where}: duplicate identifiers')


class ConceptRegistry:
    """Resolved, validated snapshot. Returned dictionaries are independent copies."""

    def __init__(self, manifest: dict[str, Any], families: list[dict[str, Any]]):
        self._manifest = copy.deepcopy(manifest)
        self._families = copy.deepcopy(families)
        self._validate()

    @classmethod
    def load(cls, root: Path | str = DEFAULT_ROOT) -> ConceptRegistry:
        root = Path(root).resolve()
        manifest = json.loads((root / 'registry.json').read_text())
        paths = manifest.get('family_files')
        _unique(paths, 'family_files')
        families = []
        for name in paths:
            path = (root / name).resolve()
            _require(path.is_relative_to(root), f'family_files: path outside registry: {name}')
            families.append(json.loads(path.read_text()))
        return cls(manifest, families)

    def _validate(self) -> None:
        m = self._manifest
        _require(m.get('schema_version') == 'product-concept-registry-v1', 'unknown registry schema_version')
        _require(m.get('status') == 'proposed_not_runtime', 'registry must remain proposed_not_runtime')
        _require(isinstance(m.get('counting_policy'), str) and bool(m['counting_policy']), 'missing counting_policy')
        modules = m.get('modules', [])
        _unique([x['id'] for x in modules], 'modules')
        _require(bool(modules), 'modules must not be empty')
        known_modules = {x['id'] for x in modules}
        _unique([f['id'] for f in self._families], 'families')
        _unique([f['review_id'] for f in self._families], 'family review references')
        concept_ids = []
        for f in self._families:
            fid = f['id']
            _require(f.get('schema_version') == 'product-concept-family-v1', f'{fid}: unknown family schema_version')
            _require(f.get('status') == 'proposed_not_runtime', f'{fid}: invalid status')
            _unique(f['store_type_ids'], f'{fid}: stores')
            _require(bool(f['store_type_ids']), f'{fid}: no store assignment')
            _require(isinstance(f['label'], str) and bool(f['label']), f'{fid}: empty label')
            _unique([d['id'] for d in f['dimensions']], f'{fid}: dimensions')
            dims = {d['id']: d for d in f['dimensions']}
            _unique(f['shared_dimension_ids'], f'{fid}: shared dimensions')
            _require(set(f['shared_dimension_ids']) <= dims.keys(), f'{fid}: unknown shared dimension')
            for d in dims.values():
                where = f"{fid}.{d['id']}"
                _require(d['module_id'] in known_modules, f'{where}: unknown module')
                _require(d['identity_level'] in LEVELS, f'{where}: invalid identity_level')
                _require(d['value_kind'] in KINDS, f'{where}: invalid value_kind')
                _require(d.get('status') == 'proposed', f'{where}: runtime readiness is not supported')
                _require(isinstance(d['label'], str) and bool(d['label']), f'{where}: empty label')
                _require(d.get('unit') is None or isinstance(d['unit'], str), f'{where}: invalid unit')
                for key in ('value_domain', 'sampling', 'runtime_binding'):
                    _require(key in d and (d[key] is None or isinstance(d[key], dict)), f'{where}: {key} must be null or object')
                _require(isinstance(d.get('dependencies'), list), f'{where}: dependencies must be a list')
            _require(bool(f['concepts']), f'{fid}: no concepts')
            used = set()
            for c in f['concepts']:
                cid = c['id']; concept_ids.append(cid)
                _require(cid.startswith(fid + '.'), f'{cid}: wrong family prefix')
                _require(isinstance(c['label'], str) and bool(c['label']), f'{cid}: empty label')
                _require(c.get('status') == 'proposed', f'{cid}: invalid status')
                for key in ('additional_dimension_ids', 'excluded_dimension_ids', 'context_module_ids'):
                    _unique(c[key], f'{cid}: {key}')
                shared, added, excluded = (set(f['shared_dimension_ids']), set(c['additional_dimension_ids']), set(c['excluded_dimension_ids']))
                _require(not (shared & added), f'{cid}: additional dimension already inherited')
                _require(not (added & excluded), f'{cid}: cannot add and exclude the same dimension')
                _require(added <= dims.keys(), f'{cid}: unknown additional dimension')
                _require(excluded <= shared, f'{cid}: exclusion is not inherited')
                active = (shared | added) - excluded
                _require(bool(active), f'{cid}: no proposed dimensions')
                used.update(active)
                _require(isinstance(c['conditional_dimensions'], dict), f'{cid}: invalid conditions')
                _require(set(c['conditional_dimensions']) <= active, f'{cid}: condition references inactive dimension')
                _require(all(isinstance(v, str) and bool(v.strip()) for v in c['conditional_dimensions'].values()), f'{cid}: empty applicability condition')
                _require(set(c['context_module_ids']) <= known_modules, f'{cid}: unknown context module')
                _require(isinstance(c['fixed_traits'], dict), f'{cid}: fixed_traits must be an object')
                _require(not (set(c['fixed_traits']) & active), f'{cid}: fixed trait also counted as variable')
                expected = {'domains', 'dependencies', 'sampling', 'retail_bindings', 'review_bindings'}
                _require(set(c['specification_status']) == expected, f'{cid}: missing specification status')
                _require(all(v in {'pending', 'draft', 'reviewed'} for v in c['specification_status'].values()), f'{cid}: invalid specification status')
            _require(used == set(dims), f'{fid}: unused dimension definitions: {sorted(set(dims) - used)}')
        _unique(concept_ids, 'concepts')

    @property
    def modules(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._manifest['modules'])

    @property
    def counting_policy(self) -> str:
        return self._manifest['counting_policy']

    def concepts(self, *, family: str | None = None, module: str | None = None,
                 store: str | None = None) -> list[dict[str, Any]]:
        """All concepts, or the intersection of family/module/store filters.

        ``dimension_count`` includes conditional dimensions as potential fields.
        ``sku_candidate_count`` includes ``sku`` and unresolved ``model_or_sku``;
        it is not a claim of implemented page controls or valid combinations.
        """
        known_families = {f['id'] for f in self._families}
        known_stores = {s for f in self._families for s in f['store_type_ids']}
        if family is not None and family not in known_families:
            raise RegistryError(f'unknown family: {family}')
        if module is not None and module not in {m['id'] for m in self._manifest['modules']}:
            raise RegistryError(f'unknown module: {module}')
        if store is not None and store not in known_stores:
            raise RegistryError(f'unknown store: {store}')
        result = []
        for f in self._families:
            if family is not None and f['id'] != family:
                continue
            if store is not None and store not in f['store_type_ids']:
                continue
            lookup = {d['id']: d for d in f['dimensions']}
            for c in f['concepts']:
                active = [x for x in f['shared_dimension_ids'] + c['additional_dimension_ids'] if x not in c['excluded_dimension_ids']]
                dimensions = []
                for key in active:
                    d = copy.deepcopy(lookup[key])
                    d['applicability'] = 'conditional' if key in c['conditional_dimensions'] else 'always'
                    d['condition'] = c['conditional_dimensions'].get(key)
                    d['inherited'] = key in f['shared_dimension_ids']
                    dimensions.append(d)
                module_ids = sorted({d['module_id'] for d in dimensions} | set(c['context_module_ids']))
                if module is not None and module not in module_ids:
                    continue
                levels = Counter(d['identity_level'] for d in dimensions)
                conditional = len(c['conditional_dimensions'])
                result.append(dict(
                    id=c['id'], label=c['label'], family_id=f['id'], family_label=f['label'],
                    review_id=f['review_id'], section=f['section'], store_type_ids=list(f['store_type_ids']),
                    family_notes=f['source_notes'],
                    module_ids=module_ids, module_count=len(module_ids), dimension_count=len(dimensions),
                    unconditional_dimension_count=len(dimensions) - conditional, conditional_dimension_count=conditional,
                    model_dimension_count=levels['model'], sku_dimension_count=levels['sku'],
                    model_or_sku_dimension_count=levels['model_or_sku'],
                    sku_candidate_count=levels['sku'] + levels['model_or_sku'],
                    specified_domain_count=sum(d['value_domain'] is not None for d in dimensions),
                    dimensions=dimensions, fixed_traits=copy.deepcopy(c['fixed_traits']),
                    specification_status=copy.deepcopy(c['specification_status']), notes=list(c['notes']),
                ))
        return result

    def get(self, concept_id: str) -> dict[str, Any]:
        for row in self.concepts():
            if row['id'] == concept_id:
                return row
        raise RegistryError(f'unknown concept: {concept_id}')

    def family_summary(self, **filters: str) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for c in self.concepts(**filters):
            groups.setdefault(c['family_id'], []).append(c)
        return [dict(family_id=fid, label=cs[0]['family_label'], review_id=cs[0]['review_id'],
                     concept_count=len(cs), dimension_min=min(c['dimension_count'] for c in cs),
                     dimension_max=max(c['dimension_count'] for c in cs),
                     dimension_mean=round(sum(c['dimension_count'] for c in cs) / len(cs), 2),
                     module_min=min(c['module_count'] for c in cs), module_max=max(c['module_count'] for c in cs))
                for fid, cs in groups.items()]


def render_table(rows: list[dict[str, Any]], *, summary: bool = False) -> str:
    columns = (['review_id', 'family_id', 'concept_count', 'dimension_min', 'dimension_max', 'module_min', 'module_max']
               if summary else ['family_id', 'label', 'module_count', 'dimension_count', 'conditional_dimension_count', 'sku_candidate_count'])
    widths = {k: max([len(k)] + [len(str(r[k])) for r in rows]) for k in columns}
    lines = [' | '.join(k.ljust(widths[k]) for k in columns), '-+-'.join('-' * widths[k] for k in columns)]
    lines.extend(' | '.join(str(r[k]).ljust(widths[k]) for k in columns) for r in rows)
    return '\n'.join(lines) + '\n'


def render_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ''
    fields = [k for k in rows[0] if k not in {'dimensions', 'notes', 'fixed_traits', 'specification_status'}]
    buf = io.StringIO(); writer = csv.DictWriter(buf, fieldnames=fields); writer.writeheader()
    for row in rows:
        writer.writerow({k: '; '.join(row[k]) if isinstance(row[k], list) else row[k] for k in fields})
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    p.add_argument('--family'); p.add_argument('--module'); p.add_argument('--store')
    p.add_argument('--concept', help='Exact stable concept identifier; JSON includes all resolved dimensions')
    p.add_argument('--summary', action='store_true', help='Group matching concepts by family')
    p.add_argument('--sort', choices=['dimensions', 'modules', 'sku', 'family'], default='family')
    p.add_argument('--descending', action='store_true')
    p.add_argument('--limit', type=int)
    p.add_argument('--format', choices=['table', 'json', 'csv', 'html'], default='table')
    p.add_argument('--output', type=Path)
    args = p.parse_args(argv)
    try:
        registry = ConceptRegistry.load(args.root)
        if args.limit is not None and args.limit < 1:
            raise RegistryError('--limit must be positive')
        if args.concept and (args.summary or args.family or args.module or args.store):
            raise RegistryError('--concept cannot be combined with summary or filters')
        filters = {k: getattr(args, k) for k in ('family', 'module', 'store') if getattr(args, k) is not None}
        rows = [registry.get(args.concept)] if args.concept else (registry.family_summary(**filters) if args.summary else registry.concepts(**filters))
        if args.summary:
            if args.sort == 'sku':
                raise RegistryError('--sort sku is only available for concepts')
            key = {'dimensions': 'dimension_max', 'modules': 'module_max', 'family': 'family_id'}[args.sort]
        else:
            key = {'dimensions': 'dimension_count', 'modules': 'module_count', 'sku': 'sku_candidate_count', 'family': 'family_id'}[args.sort]
        rows.sort(key=lambda r: r.get('id', r['family_id']))
        rows.sort(key=lambda r: r[key], reverse=args.descending)
        if args.limit:
            rows = rows[:args.limit]
        if args.format == 'json':
            rendered = json.dumps(rows, indent=2, ensure_ascii=False) + '\n'
        elif args.format == 'csv':
            rendered = render_csv(rows)
        elif args.format == 'html':
            if args.summary:
                raise RegistryError('HTML includes its own family summary; omit --summary')
            from .concept_registry_report import render_html
            rendered = render_html(rows, registry.counting_policy)
        else:
            rendered = render_table(rows, summary=args.summary)
    except (RegistryError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        p.error(str(exc))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
