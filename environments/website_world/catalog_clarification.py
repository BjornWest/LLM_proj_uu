"""Finite personal-preference replies and retained delivery checks, no NLP model.

The callback returns only public reply text. Its private contract is never a
policy tool argument. Saved interaction checks do not infer attention or intent.
"""
from copy import deepcopy
import ast
from hashlib import sha256
import json
from pathlib import Path
import re

from environments.product_world.manual_clarification import _personal_size_question, FALLBACK
from .catalog_predicates import PredicateSet
from .catalog_memory import _id, APPAREL
from .adapter import digest

VERSION = 'website-catalog-personal-clarification-v1'
RULES = {'personal_shoe_size_en_v1': 'sku.size_eu',
         'personal_clothing_label_en_v1': 'sku.size_label',
         'personal_clothing_range_en_v1': 'product.facts.market_range'}


def compile_slot(value, inventory):
    if (type(value) is not dict or set(value) != {'id','subject','predicate','match_rule','ordering','contrast_values'} or
            not _id(value['id']) or not _id(value['subject']) or type(value['match_rule']) is not str or value['match_rule'] not in RULES or
            value['ordering'] not in ('before_final_answer','before_search')):
        raise ValueError('Declare one typed personal preference, finite reply rule and ordering')
    p = value['predicate']; rule = value['match_rule']; family = inventory.concept_id.split('.')[0]
    if (type(p) is not dict or p.get('field') != RULES[rule] or p.get('operator') not in ('eq','in') or
            rule == 'personal_shoe_size_en_v1' and (family != 'footwear' or p.get('operator') != 'eq') or
            rule != 'personal_shoe_size_en_v1' and family not in APPAREL or
            rule == 'personal_clothing_label_en_v1' and p.get('operator') != 'eq'):
        raise ValueError('Reply rule does not match the concept/personal field')
    predicate = PredicateSet(inventory.fields, [p], known_paths=inventory.known_paths).predicates[0]
    alternatives = value['contrast_values']
    if type(alternatives) is not list or not alternatives or len(alternatives) > 8:
        raise ValueError('Declare one to eight pre-sampling contrast operands')
    seen = set()
    for operand in alternatives:
        alternative = {**predicate, 'value': operand}
        PredicateSet(inventory.fields, [alternative], known_paths=inventory.known_paths)
        if digest(operand) == digest(predicate['value']) or digest(operand) in seen:
            raise ValueError('Contrast operands must be distinct from the hidden requirement and each other')
        seen.add(digest(operand))
    if rule == 'personal_shoe_size_en_v1':
        if type(p['value']) is not int or not 20 <= p['value'] <= 55:
            raise ValueError('Personal shoe-size responder supports integer EU20–55 only')
    return {**deepcopy(value), 'predicate': predicate}


def reply(slot):
    subject = 'For me' if slot['subject'] == 'self' else 'For '+slot['subject']
    value = slot['predicate']['value']; rule = slot['match_rule']
    if rule == 'personal_shoe_size_en_v1': return f'{subject}, please use EU {value}.'
    if rule == 'personal_clothing_label_en_v1': return f'{subject}, please use clothing size label {value}.'
    values = [value] if type(value) is str else value
    labels = {'women': "women's", 'men': "men's", 'unisex': 'unisex'}
    return subject+', please use '+ ' or '.join(labels[v] for v in values)+' clothing ranges.'


def matches(slot, question):
    if type(question) is not str or not question.strip() or len(question) > 2000:
        raise ValueError('A nonempty bounded user question is required')
    text = ' '.join(question.casefold().split())
    if re.search(r'\b(stock|available|availability|price|cost|cheapest|retailer|inventory|budget)\b',text): return False
    # Explicitly asking about someone else cannot reveal this person's preference.
    if slot['subject'] != 'self' and not re.search(r'\b'+re.escape(slot['subject'])+r'\b',text): return False
    if slot['subject'] == 'self':
        if re.search(r'\b(wife|husband|child|daughter|son|friend|partner|mother|father)\b',text): return False
        named = re.search(r'\b(?:for|does) ([a-z][a-z0-9_-]*)\b',text)
        if named and named.group(1) not in ('you','your','yourself','me','my','myself'):
            return False
    rule = slot['match_rule']
    if rule == 'personal_shoe_size_en_v1':
        if re.search(r'\b(shirt|clothing|jacket|trouser|dress|label)\b',text): return False
        return _personal_size_question(question)
    if rule == 'personal_clothing_label_en_v1':
        if re.search(r'\b(shoe|footwear|eu|european)\b',text): return False
        return _personal_size_question(question)
    return bool(re.search(r'\b(women|womens|men|mens|unisex|gender|range|ranges)\b|women[’\']s|men[’\']s',text)
                and re.search(r'\b(you|your|wear|prefer|preferred|want|which|what|should)\b',text))


class Responder:
    def __init__(self, task):
        self.slot = deepcopy(task['hidden_requirement'])
        self.audit_id = 'hidden-personal-'+digest([VERSION,task['task_id'],self.slot])[:24]

    def __call__(self, question):
        return reply(self.slot) if matches(self.slot,question) else FALLBACK


def _pin(path):
    return sha256(path.read_bytes()).hexdigest()


def evidence(trace, task):
    """Recheck callback and next-request spans from an actual retained runner trace.

    Missing/corrupt transport evidence stays unknown. Complete main traces with no
    matching request fail the clarification condition. No regex over final answers,
    fabricated policy receipts or direct callback invocation earns delivery credit.
    """
    trace = Path(trace).resolve(); pins = {}; diagnostics = []
    def read(name, lines=False):
        p = (trace/name).resolve()
        if not p.is_relative_to(trace): raise ValueError('Trace artifact escapes its root')
        pins[str(p)] = _pin(p)
        return [json.loads(s) for s in p.read_text().splitlines()] if lines else json.loads(p.read_text())
    out = {'schema_version': VERSION, 'task_id': task['task_id'], 'status':'unknown',
           'clarification_delivered':None, 'ordering_satisfied':None, 'matched_callbacks':[],
           'source_sha256': pins, 'diagnostics':diagnostics,
           'qualification':'Exact retained main-request delivery, not attention, reasoning or helper propagation.'}
    try:
        rows = read('steps.jsonl',True); natural = read('natural-answer.json')
        if natural.get('stop_reason') != 'agent_finished' or natural.get('technical_error'):
            diagnostics.append('No complete uninterrupted main final answer'); return out
        indices = [r['step'] for r in rows]
        if any(type(n) is not int or n < 0 for n in indices) or len(indices) != len(set(indices)):
            raise ValueError('Invalid or duplicate step identities')
        by_step = {r['step']:r for r in rows}; callbacks = {}
        responder = Responder(task); first_search = None; final_steps = []
        for row in rows:
            events = row.get('batch_calls') or [row]
            for event in events:
                action = event.get('action')
                name = None
                if type(action) is str:
                    expression = ast.parse(action, mode='eval').body
                    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name):
                        raise ValueError('Unsupported retained action format')
                    name = expression.func.id
                elif event.get('kind') in ('browser','clarification'):
                    raise ValueError('Missing retained executed action')
                if name == 'send_msg_to_user': final_steps.append(row['step'])
                if name not in (None,'ask_user','send_msg_to_user','noop'):
                    first_search = row['step'] if first_search is None else min(first_search,row['step'])
                artifact = event.get('clarification_artifact')
                if artifact is None: continue
                saved = read(artifact)
                if (saved.get('schema_version') != 'user-clarification-v1' or saved.get('error') or
                        saved.get('audit_id') != responder.audit_id or not matches(responder.slot,saved['question']) or
                        saved.get('reply') != reply(responder.slot)):
                    diagnostics.append('Unmatched/failed/different reply contract callback'); continue
                callbacks[artifact] = {'question_step':row['step'],'reply':saved['reply']}
        if not callbacks:
            out.update(status='not_satisfied',clarification_delivered=False,ordering_satisfied=False)
            return out
        delivered = []
        # Delivery file is required once a successful matching callback exists.
        for event in read('policy-delivery.jsonl',True):
            if event.get('recipient') != 'main': continue
            for item in event.get('items',[]):
                if item.get('kind') != 'clarification_result' or item.get('confirmed') is not True: continue
                source = read(item['artifact']); callback_name = source.get('provenance',{}).get('clarification_artifact')
                if callback_name not in callbacks: continue
                request = by_step[event['step']]['model_request']['messages']; span = item['message_span']
                text = request[span['message_index']]['content']
                if type(text) is list: text = text[0]['text']
                content_hash = sha256(source['text'].encode()).hexdigest()
                request_hash = sha256(json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                if (event.get('scope') != 'retained_request_completion' or event.get('backend_completion_returned') is not True or
                        item.get('aligned') is not True or event['messages_sha256'] != request_hash or
                        source['id'] != item['content_id'] or span['content_id'] != source['id'] or
                        source['kind'] != item['kind'] or source['sha256'] != content_hash or item['sha256'] != content_hash or
                        source['created_step'] != callbacks[callback_name]['question_step'] or
                        not source['created_step'] < event['step'] or
                        type(span['start']) is not int or type(span['end']) is not int or
                        not 0 <= span['start'] < span['end'] <= len(text) or text[span['start']:span['end']] != source['text'] or
                        json.loads(source['text']) != {'tool':'ask_user','user_reply':callbacks[callback_name]['reply']}):
                    raise ValueError('Clarification delivery binding changed')
                delivered.append({'artifact':callback_name,'question_step':source['created_step'],'delivery_step':event['step']})
        out['matched_callbacks'] = delivered
        if not delivered:
            out.update(status='not_satisfied',clarification_delivered=False,ordering_satisfied=False); return out
        earliest = min(d['delivery_step'] for d in delivered)
        cutoff = first_search if task['hidden_requirement']['ordering'] == 'before_search' and first_search is not None else min(final_steps) if final_steps else None
        if cutoff is None:
            diagnostics.append('No retained final decision for ordering'); return out
        satisfied = earliest <= cutoff
        out.update(status='satisfied' if satisfied else 'not_satisfied',clarification_delivered=True,ordering_satisfied=satisfied)
        return out
    except (OSError, ValueError, KeyError, TypeError, IndexError, SyntaxError) as error:
        diagnostics.append(type(error).__name__+': '+str(error))
        return out
