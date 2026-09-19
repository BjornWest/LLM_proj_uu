"""Retain bridge/checker sources outside the harness's ordinary module inventory."""
from pathlib import Path
from intent_browser.trace import write_json
from .bindings import digest


def record_sources(row, context, trace):
    root = Path(context.project_root).resolve()
    owned = Path(__file__).resolve().parent
    paths = list(owned.glob('*.py'))
    if row['family'].startswith('tricky.'):
        paths += list((root / 'data/curation/expansion/tricky').rglob('*.py'))
        paths += list((root / 'data/curation/expansion/tricky_original_remaining').glob('*.py'))
    else:
        paths += [root / 'data/curation/expansion/biography_outcome.py']
        for family in ('votes', 'wishlist', 'posts', 'coupon'):
            paths += list((root / ('data/curation/expansion/webarena_' + family)).glob('grader*.py'))
    paths += [root / row['contract']['path']]
    sources = {str(p.resolve().relative_to(root)): digest(p) for p in sorted(set(paths))}
    output = trace.directory / 'expanded-runtime-sources.json'
    write_json(output, {'scope': 'Portable bridge and retained curation checker source set; harness/package provenance recorded separately',
                        'source_sha256': sources, 'binding_revision': row['revision']})
    return {'path': output.name, 'sha256': digest(output)}
