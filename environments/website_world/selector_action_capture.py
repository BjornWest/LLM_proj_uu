"""Opt-in copied-asset observer and private retained-document capture.

Source preparation only; actual browser/source-authority acceptance is separate.
"""
from hashlib import sha256
from copy import deepcopy
import json
import math
from pathlib import Path
import re

from .adapter import digest

VERSION = 'website-selector-action-capture-proposal-v1'
START = 'function changeSelection(key,value) {'
END = "\ndocument.addEventListener('change',event=>{"
IMPORT = '\nimport {selectorJournal} from "./selector-action-capture.js";\n'


def options(value=None):
    if value is None: return None
    if type(value) is not dict or not value: raise ValueError('Declare nonempty recorder retailer targets')
    result = {}
    for rid, row in value.items():
        if (type(rid) is not str or not rid or type(row) is not dict or set(row) != {'page_id', 'control_token'}
                or type(row['page_id']) is not str or not row['page_id']
                or type(row['control_token']) is not str or not re.fullmatch(r'[0-9a-f]{32}', row['control_token'])):
            raise ValueError('Recorder needs an existing page and private control token per retailer')
        result[rid] = dict(row)
    return result


def validate_catalog(catalog, *, retailer_id, settings):
    settings = options(settings)
    if settings is None or retailer_id not in settings: return
    ids = [p['id'] for p in catalog['products']]
    if catalog['siteId'] != retailer_id or len(ids) != len(set(ids)) or settings[retailer_id]['page_id'] not in ids:
        raise ValueError('Selector recorder target is absent or ambiguous in actual catalog')


def project_assets(assets, *, expected_source_sha256, settings):
    """One known production seam, exact inverse, no shared/default edits.

    The caller must declare a new consumer/source authority. This preparation
    function is not browser or event-provenance certification.
    """
    settings = options(settings)
    if settings is None: raise ValueError('Explicit recorder settings required for copied-asset projection')
    source = assets.get('shop.js')
    if type(source) is not bytes or sha256(source).hexdigest() != expected_source_sha256:
        raise ValueError('Full composed renderer differs from its source pin')
    text = source.decode()
    if text.count(START) != 1 or text.count(END) != 1 or '__selectorJournal' in text or 'selector-action-capture.js' in assets:
        raise ValueError('Selector seam is absent, ambiguous or already observed')
    start, end = text.index(START), text.index(END)
    original = text[start:end]
    if not original.endswith('\n}') or 'resolveProduct(p.id,state.selection[p.id])' not in original:
        raise ValueError('Unsupported production selector function')
    body = original[len(START):-2]
    replacement = (START + '\n  const __page=route().id;\n'
        '  const __event=__selectorJournal?.before(__page,key,value,state.selection[__page])??null;\n'
        '  let __failed=false;\n  try {' + body + '\n  } catch(__error) {__failed=true;throw __error;}\n'
        '  finally {__selectorJournal?.after(__event,state.selection[__page],__failed);}\n}')
    tail = (IMPORT + 'const __selectorSettings=' + json.dumps(settings, ensure_ascii=True, sort_keys=True) + '[site];\n'
            'const __selectorJournal=__selectorSettings?selectorJournal(__selectorSettings.control_token):null;\n'
            'if(__selectorJournal)Object.defineProperty(window,"__websiteSelectorActionsV1",{value:Object.freeze({\n'
            '  begin:__selectorJournal.begin,seal:__selectorJournal.seal\n'
            '}),configurable:false,enumerable:false});\n')
    initialization = tail
    tail = ''
    # Initialize before registering any selector/change/hash/storage listener
    # or entering the renderer's top-level asynchronous refresh.
    changed = (text[:start] + initialization + replacement + text[end:]).encode()
    helper = Path(__file__).with_suffix('.js').read_bytes()
    evidence = {'schema': VERSION, 'before_sha256': expected_source_sha256,
                'after_sha256': sha256(changed).hexdigest(), 'original_function': original,
                'replacement_function': replacement, 'tail': tail, 'initialization': initialization,
                'helper_sha256': sha256(helper).hexdigest(), 'settings': settings,
                'scope': 'Retained-document ordinary selector-handler calls; setup excluded; authority pending'}
    if restore_source(changed, evidence) != source: raise ValueError('Observer has no exact renderer inverse')
    return {**assets, 'shop.js': changed, 'selector-action-capture.js': helper}, evidence


def restore_source(source, evidence):
    if evidence.get('schema') != VERSION or sha256(source).hexdigest() != evidence['after_sha256']:
        raise ValueError('Selector evidence differs from complete copied source')
    text = source.decode()
    tail, replacement = evidence['tail'], evidence['replacement_function']
    initialization = evidence.get('initialization', '')
    if initialization:
        inserted = initialization + replacement
        if tail or text.count(inserted) != 1: raise ValueError('Observer inverse is not unique')
        restored = text.replace(inserted, evidence['original_function']).encode()
    else:
        if not tail or not text.endswith(tail) or text.count(replacement) != 1: raise ValueError('Observer inverse is not unique')
        restored = text[:-len(tail)].replace(replacement, evidence['original_function']).encode()
    if sha256(restored).hexdigest() != evidence['before_sha256']: raise ValueError('Original renderer inverse differs')
    return restored


def native_projection(raw, *, task, main_trace_sha256, document_token, page_retained,
                      initial_selection, final_selection):
    """Fail closed on lost history. Raw actual browser evidence is caller-owned.

    Only a separately accepted actual capture can supply these arguments. A
    synthetic dict/test must never be used as a real episode's action journal.
    """
    if (type(raw) is not dict or set(raw) != {'documentToken', 'pageId', 'initialSelection', 'finalSelection', 'complete', 'events', 'faults'}
            or raw['documentToken'] != document_token or raw['pageId'] != task['page_id']
            or raw['initialSelection'] != initial_selection or raw['finalSelection'] != final_selection
            or page_retained is not True or raw['complete'] is not True or raw['faults'] != []
            or type(raw['events']) is not list or len(raw['events']) > 256):
        return None
    previous, rows = initial_selection, []
    for position, event in enumerate(raw['events']):
        if (type(event) is not dict or set(event) != {'page_id', 'axis', 'requested_value', 'before', 'after', 'sequence', 'started_at', 'finished_at'}
                or type(event['sequence']) is not int or event['sequence'] != position
                or event['page_id'] != task['page_id'] or event['before'] != previous
                or type(event['axis']) is not str or type(event['requested_value']) is not str
                or type(event['before']) is not dict or type(event['after']) is not dict):
            return None
        if any(type(event[k]) not in (int, float) or not math.isfinite(event[k]) for k in ('started_at', 'finished_at')):
            return None
        if event['started_at'] < 0 or event['finished_at'] < event['started_at'] or (position and event['started_at'] < raw['events'][position-1]['finished_at']):
            return None
        rows.append({k: event[k] for k in ('axis', 'requested_value', 'before', 'after')})
        previous = event['after']
    if previous != final_selection: return None
    return {'schema_version': 'website-selector-action-journal-v1', 'task_sha256': digest(task),
            'main_trace_sha256': main_trace_sha256, 'complete': True, 'events': deepcopy(rows)}


from .atomic_address_execution import AddressCapture
from .catalog_cart_execution import save_new


class SelectorCapture(AddressCapture):
    """Read-only actual callbacks; journal is sealed before context teardown.

    Same-document product URL updates are retained. Leaving the product,
    changing the active page/document, or losing callbacks never produces a
    complete native journal. No events are reconstructed from expected tuples.
    """
    def __init__(self, runtime, task, *, authority=None, authority_approval=None):
        super().__init__(runtime, task, authority=authority, authority_approval=authority_approval)
        evidence = runtime.selector_capture_evidence
        if (type(evidence) is not dict or evidence.get('schema') != VERSION
                or evidence.get('after_sha256') != runtime.asset_hashes.get('shop.js')
                or evidence.get('helper_sha256') != runtime.asset_hashes.get('selector-action-capture.js')):
            raise ValueError('Capture requires the actual composed recorder asset pins')
        self.settings = options(evidence['settings'])
        self.target = self.settings.get(task['retailer_id'])
        if self.target is None or self.target['page_id'] != task['page_id']:
            raise ValueError('Capture target differs from actual Runtime recorder')
        self.selector_sources = deepcopy(evidence)
        self.selector_phase = 'setup'
        self.selector_errors, self.selector_navigation, self.selector_artifacts = [], [], {}
        self.selector_page = self.selector_context = None

    def _fault(self, reason):
        if len(self.selector_errors) < 32: self.selector_errors.append(str(reason))

    def _target_url(self, url):
        from urllib.parse import urlsplit
        actual = urlsplit(url)
        origin = urlsplit(self.runtime.origins[self.task['retailer_id']])
        return (actual.scheme, actual.netloc, actual.path) == (origin.scheme, origin.netloc, '/') and actual.fragment.partition('?')[0] == '/product/' + self.task['page_id']

    def _selection(self, page):
        return page.evaluate('''({key,id})=>{
          const raw=localStorage.getItem(key);
          return raw===null?null:(JSON.parse(raw).selection?.[id]??null);
        }''', {'key': self.binding['retailers'][self.task['retailer_id']]['storage_key'],
               'id': self.task['page_id']})

    def _write_selector(self, trace, name, record):
        if name in self.selector_artifacts: raise ValueError('Selector phase already captured')
        path = trace.directory / 'manual-review-private' / ('selector-' + name + '.private.json')
        save_new(path, record)
        self.selector_artifacts[name] = {'path': str(path.resolve()), 'sha256': sha256(path.read_bytes()).hexdigest()}

    def before(self, env, trace):
        page = env.unwrapped.page
        self.selector_page, self.selector_context = page, page.context
        self.selector_phase = 'baseline'
        initial, begin = None, None
        try:
            if not self._target_url(page.url): raise ValueError('Selector baseline is outside target product')
            initial = self._selection(page)
            begin = page.evaluate('''({token,id,selection})=>
              window.__websiteSelectorActionsV1.begin(token,id,selection)''',
                {'token': self.target['control_token'], 'id': self.task['page_id'], 'selection': initial})
            if (type(begin) is not dict or set(begin) != {'documentToken', 'phase', 'pageId', 'initialSelection'}
                    or type(begin['documentToken']) is not str or not begin['documentToken']
                    or begin['phase'] != 'policy' or begin['pageId'] != self.task['page_id']
                    or begin['initialSelection'] != initial or type(initial) is not dict):
                raise ValueError('Actual recorder baseline is absent or inconsistent')
        except Exception as error:
            self._fault('Begin: ' + str(error))
        self.selector_initial = deepcopy(initial)
        self.selector_begin = deepcopy(begin)
        self._write_selector(trace, 'before', {'actual_url': page.url, 'selection': initial,
            'begin': begin, 'errors': list(self.selector_errors), 'sources': self.selector_sources,
            'scope': 'Private actual callback; browser/source authority acceptance remains separate'})

        def navigation(frame):
            if self.selector_phase != 'policy' or frame is not page.main_frame: return
            if len(self.selector_navigation) >= 256:
                self._fault('Navigation journal overflow');return
            self.selector_navigation.append({'url': frame.url})
            if not self._target_url(frame.url): self._fault('Navigation left target product')
        def new_page(_):
            if self.selector_phase == 'policy': self._fault('Another page opened during policy')
        page.on('framenavigated', navigation)
        page.context.on('page', new_page)
        baseline = super().before(env, trace)
        self.selector_phase = 'policy'
        return baseline

    def after(self, env, trace, outcome):
        self.selector_phase = 'sealing'
        page = env.unwrapped.page
        raw, final = None, None
        try:
            if page is not self.selector_page or page.context is not self.selector_context:
                raise ValueError('Active product page/context changed')
            if not self._target_url(page.url): raise ValueError('Terminal page is outside target product')
            final = self._selection(page)
            raw = page.evaluate('''({token,selection})=>
              window.__websiteSelectorActionsV1.seal(token,selection)''',
                {'token': self.target['control_token'], 'selection': final})
        except Exception as error:
            self._fault('Seal: ' + str(error))
        self._write_selector(trace, 'after', {'actual_url': page.url, 'selection': final,
            'raw_journal': raw, 'errors': list(self.selector_errors), 'navigation': self.selector_navigation})
        return super().after(env, trace, outcome)

    def seal(self, returned_trace, summary):
        capsule, completed = super().seal(returned_trace, summary)
        path = Path(returned_trace).resolve()
        records = {}
        for name in ('before', 'after'):
            pin = self.selector_artifacts.get(name)
            if pin is None: break
            artifact = Path(pin['path'])
            if not artifact.is_relative_to(path) or sha256(artifact.read_bytes()).hexdigest() != pin['sha256']:
                raise ValueError('Actual selector capture artifact changed')
            records[name] = json.loads(artifact.read_bytes())
        journal = None
        if set(records) == {'before', 'after'} and not records['before']['errors'] and not records['after']['errors']:
            begin = records['before']['begin']
            journal = native_projection(records['after']['raw_journal'], task=self.task,
                main_trace_sha256=capsule['main_trace_sha256'], document_token=begin['documentToken'],
                page_retained=True, initial_selection=records['before']['selection'],
                final_selection=records['after']['selection'])
        save_new(path / 'selector-interaction.private.json', {'schema': VERSION, 'interaction': journal,
            'captures': self.selector_artifacts, 'main_trace_sha256': capsule['main_trace_sha256'],
            'scope': 'Actual retained-document handler transitions only; no reading or external-effect claim'})
        self.interaction = deepcopy(journal)
        return capsule, completed
