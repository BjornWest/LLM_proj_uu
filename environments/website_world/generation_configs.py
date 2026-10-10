"""Versioned local generation recipes and private generation/run provenance.

Saving/exporting a recipe never samples a world or invokes a model. Original
requests, resolved defaults and immutable generated artifacts stay distinct.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import fcntl
import json
import re

VERSION = 'website-generation-config-v1'
RECORD = 'website-generation-record-v1'
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY = ROOT / '.local/website-generation-configs'


def json_value(value):
    return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def grading_options(value=None):
    """The shared grading recipe validator; storage needs only the standard library."""
    if value is None:
        return {'mode': 'off'}
    if type(value) is not dict or set(value) - {'mode', 'model', 'reasoning_effort'}:
        raise ValueError('Unknown answer-grading execution option')
    mode = value.get('mode')
    if mode == 'off' and set(value) == {'mode'}:
        return {'mode': 'off'}
    if mode != 'subscription-post-run':
        raise ValueError('Answer grading mode must be off or subscription-post-run')
    result = {'mode': mode, 'model': 'gpt-6.1-sol', 'reasoning_effort': 'low', **deepcopy(value)}
    if type(result['model']) is not str or not result['model'].strip():
        raise ValueError('Declare an extraction model')
    if result['reasoning_effort'] not in ('low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        raise ValueError('Unknown extraction reasoning effort')
    return result


def execution_options(value=None):
    value = {} if value is None else json_value(value)
    if type(value) is not dict or set(value) - {'validation', 'lazy_publication', 'answer_grading'}:
        raise ValueError('Unknown generation execution option')
    validation = value.get('validation', 'off')
    if validation not in ('off', 'full'):
        raise ValueError('Validation must be off or full')
    lazy = value.get('lazy_publication', False)
    if type(lazy) is not bool:
        raise ValueError('lazy_publication must be a bool')
    return {'validation': validation, 'lazy_publication': lazy,
            'answer_grading': grading_options(value.get('answer_grading'))}


def config(request, execution=None):
    request = json_value(request)
    if (type(request) is not dict or request.get('schema') not in
            ('website-world-generation-v1', 'website-world-generation-v2')
            or type(request.get('seed')) is not int):
        raise ValueError('Supply a versioned generation request with an integer seed')
    return {'request': request, 'execution': execution_options(execution)}


def unpack(value):
    """Raw historical requests remain accepted alongside complete saved recipes."""
    if value.get('schema') == VERSION:
        result = config(**value['config'])
        if digest(result) != value['config_sha256']:
            raise ValueError('Saved generation config digest differs')
        return result
    if value.get('schema') == RECORD:
        result = config(value['request'], value['execution'])
        if digest(result) != value['config_sha256']:
            raise ValueError('Generation record config digest differs')
        return result
    return config(value)


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as file:
        json.dump(value, file, indent=2, ensure_ascii=False, allow_nan=False)
        file.write('\n')


def artifact(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def provenance(directory):
    """Bound links only; do not infer old missing defaults using today's code."""
    directory = Path(directory).resolve()
    names = ('manifest.json', 'request.json', 'generation-config.private.json',
             'execution.private.json', 'basic-offer-task.private.json',
             'order-set-task.private.json', 'episode.json', 'sampling-audit.private.json')
    record = directory/'generation-config.private.json'
    return {'generation_directory': str(directory),
            'config_sha256': json.loads(record.read_text())['config_sha256'] if record.is_file() else None,
            'artifacts': {name: artifact(directory/name) for name in names if (directory/name).is_file()},
            'resolved_defaults_recorded': (directory/'generation-config.private.json').is_file()}


def capture(request, resolved, *, world_id, selected_seed):
    bundle = config(request)
    return {'schema': RECORD, 'config_sha256': digest(bundle), **bundle,
            'resolved': json_value(resolved), 'selected_seed': selected_seed, 'world_id': world_id,
            'task_source': ('structured_template' if 'basic_offer_selection' in resolved else 'manual_prose')}


class Library:
    def __init__(self, root=DEFAULT_LIBRARY):
        self.root = Path(root).resolve()

    @contextmanager
    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root/'.lock').open('a') as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            yield

    def records(self):
        result = []
        for path in sorted((self.root/'recipes').glob('*.json')):
            value = json.loads(path.read_text())
            unpack(value)  # Detect mutation rather than returning altered recipes.
            result.append(value)
        return result

    def put(self, name, request, execution=None, *, tags=(), notes=''):
        if type(name) is not str or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', name):
            raise ValueError('Config name must be a short path-free name')
        if type(tags) not in (list, tuple) or any(type(t) is not str or not t.strip() for t in tags) or type(notes) is not str:
            raise ValueError('Tags and notes must be text')
        tags = sorted(set(tags))
        bundle = config(request, execution)
        with self._lock():
            previous = [r for r in self.records() if r['name'] == name]
            if previous:
                latest = max(previous, key=lambda r: r['version'])
                if latest['config'] == bundle and latest['tags'] == tags and latest['notes'] == notes:
                    return deepcopy(latest)
            record = {'schema': VERSION, 'name': name,
                      'version': max((r['version'] for r in previous), default=0)+1,
                      'config_sha256': digest(bundle), 'config': bundle, 'tags': tags, 'notes': notes,
                      'saved_at': datetime.now(timezone.utc).isoformat()}
            folder = self.root/'recipes'; folder.mkdir(exist_ok=True)
            save(folder/f'{name}--{record["version"]:06d}.json', record)
            return record

    def get(self, selector):
        name, at, revision = selector.partition('@')
        matches = [r for r in self.records() if r['name'] == name or r['config_sha256'] == selector]
        if at:
            if not revision.isdigit():
                raise ValueError('Use name@version to select a revision')
            matches = [r for r in matches if r['version'] == int(revision)]
        if not matches:
            raise ValueError('Generation config not found: '+selector)
        return deepcopy(max(matches, key=lambda r: (r['saved_at'], r['version'])))

    def search(self, *, query='', tag=None, history=False):
        records = self.records()
        if not history:
            latest = {}
            for r in records:
                if r['name'] not in latest or r['version'] > latest[r['name']]['version']:
                    latest[r['name']] = r
            records = list(latest.values())
        return [r for r in records if (tag is None or tag in r['tags']) and
                query.lower() in json.dumps(r, ensure_ascii=False).lower()]

    def import_generation(self, directory, name, *, run_directories=(), tags=(), notes='', source_recipe=None):
        directory = Path(directory).resolve()
        request = json.loads((directory/'request.json').read_text())
        execution = {}
        policy = directory/'execution.private.json'
        if policy.exists():
            old = json.loads(policy.read_text())
            execution = {'validation': old.get('validation', 'off'),
                         **old.get('runtime_options', {}), 'answer_grading': old.get('answer_grading')}
        record = None
        if source_recipe is not None:
            if type(source_recipe) is not dict or source_recipe.get('name') != name:
                raise ValueError('Source recipe identity differs')
            unpack(source_recipe)
            # The selected revision must still be an actual immutable library
            # member. A concurrently added revision must not change this use.
            with self._lock():
                selected = self.get(f"{name}@{source_recipe['version']}")
            if selected != source_recipe:
                raise ValueError('Source recipe changed after selection')
            if (selected['config'] == config(request, execution) and
                    selected['tags'] == sorted(set(tags)) and selected['notes'] == notes):
                record = selected
        if record is None:
            # Explicit imports and effective CLI overrides retain the documented
            # new-version behavior; replaying an old unchanged recipe does not.
            record = self.put(name, request, execution, tags=tags, notes=notes)
        evidence = provenance(directory)
        evidence['config_sha256'] = record['config_sha256']
        evidence['name'] = name; evidence['version'] = record['version']
        evidence['runs'] = []
        for path in run_directories:
            run = Path(path).resolve()
            names = ('execution-plan.private.json', 'execution-result.json', 'policy-result.json')
            evidence['runs'].append({'directory': str(run), 'artifacts': {
                n: artifact(run/n) for n in names if (run/n).is_file()}})
        with self._lock():
            folder = self.root/'uses'; folder.mkdir(exist_ok=True)
            target = folder/(digest(evidence)+'.json')
            if not target.exists():
                save(target, evidence)
        return record, evidence


def render_report(library, output):
    """Small human index; configs/contracts are escaped and remain downloadable."""
    from html import escape
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    rows=[]
    for record in library.search():
        request=record['config']['request'];world=request.get('world',{});controls=world.get('controls',{})
        filename=record['name']+'--'+str(record['version'])+'.json'
        target=output/filename
        target.write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
        task=request.get('task',{})
        cells=[record['name']+'@'+str(record['version']),str(request['seed']),
               str(len(world['concept_ids'])) if 'concept_ids' in world else 'default',
               *(str(controls.get(k,'default')) for k in ('world_size','product_concentration',
                   'retailer_concentration','within_store_task_concentration','unrelated_store_assortment_weight')),
               str(task.get('concept_id') or 'seed-selected'),', '.join(record['tags'])]
        rows.append('<tr>'+''.join('<td>'+escape(v)+'</td>' for v in cells)+
                    '<td><a href="'+escape(filename,quote=True)+'">Full JSON</a></td></tr>')
    uses=[]
    for file in sorted((library.root/'uses').glob('*.json')):
        use=json.loads(file.read_text());links=[]
        for name,item in use['artifacts'].items():
            if name not in ('request.json','basic-offer-task.private.json','order-set-task.private.json','generation-config.private.json'):
                continue
            source=Path(item['path'])
            if source.is_file() and sha256(source.read_bytes()).hexdigest()==item['sha256']:
                filename=file.stem[:16]+'-'+name
                (output/filename).write_bytes(source.read_bytes())
                links.append('<a href="'+escape(filename,quote=True)+'">'+escape(name)+'</a>')
        uses.append('<li><strong>'+escape(use['name'])+'</strong>: '+escape(use['generation_directory'])+
                    '<p>Resolved defaults '+('recorded' if use['resolved_defaults_recorded'] else 'not separately recorded in this historical generation')+
                    '. '+ ' · '.join(links)+'</p></li>')
    headers=('Config','Seed','Concepts','World size','Product concentration','Retailer concentration',
             'Within-store concentration','Other assortment','Task concept','Tags','Download')
    document=('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Saved generation configs</title>
<style>body{font:16px system-ui;max-width:1400px;margin:32px auto;padding:0 20px;color:#18202c}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd3dc;padding:9px;text-align:left;vertical-align:top}th{background:#edf1f6}input{font:inherit;padding:8px;width:min(500px,90%)}.scroll{overflow:auto}li{margin:16px 0}p{line-height:1.5}</style>
<h1>Saved world and task configs</h1><p>Immutable named versions; full JSON includes the original generation request and execution settings. Size1/2/4 presets derive from the recorded38-concept baseline and were not separately sampled. Changing a preset does not change generator defaults.</p>
<label>Find a config <input id="filter" type="search" placeholder="Name, concept, tag or setting"></label>
<div class="scroll"><table><thead><tr>'''+''.join('<th>'+escape(h)+'</th>' for h in headers)+
            '</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><h2>Recorded generation requirements</h2><p>Original structured task contracts and requests are retained. Some fixed conventions remain in prose and pinned task/grader code; this is not a general requirement-to-prose compiler. Historical files are copied for reading only when their retained hashes match.</p><ul>'+''.join(uses)+'''</ul>
<script>document.getElementById('filter').addEventListener('input',event=>{const q=event.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(q))});</script></html>''')
    (output/'index.html').write_text(document)
    return {'output':str(output.resolve()),'configs':len(rows),'generation_records':len(uses)}
