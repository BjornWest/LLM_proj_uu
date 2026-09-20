"""Native Chat Completions tools, independent of BrowserGym execution.

JSON schemas constrain the interface, not the selected action's correctness.
All calls are validated locally before any action. Batching is explicitly opt-in;
historical single-call profiles retain their parser and request options.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import math

from jsonschema import Draft202012Validator

from .actions import parse_decision, Decision
from .ax_explorer import AX_TOOLS
from .ax_context import CONTEXT_TOOLS
from .harness import BrowserTools, EvidenceConversation

STRING = {'type': 'string'}
BID = {'type': 'string', 'minLength': 1, 'description': 'Element ID from the current accessibility observation.'}
NUMBER = {'type': 'number'}
SPECS = {
    'screenshot': ('Inspect a current native-resolution viewport image when AX is insufficient. '
        'Position a known target with scroll_into_view first if needed. No full-page capture.', {}, []),
    'release_image': ('Optionally remove a previously delivered image from future context, retaining agent-written takeaways. '
        'Explicitly changes the cached prefix; prefer early release or keep the image. Fixed retain profiles report disabled. '
        'Trace originals remain. Notes are unverified agent observations.',
        {'image_id': {'type':'string','minLength':1,'maxLength':80},
         'keep_notes': {'type':'string','minLength':1,'maxLength':2000}}, ['image_id','keep_notes']),
    'scroll_into_view': ('Scroll a known current element into the viewport without clicking. '
        'May trigger lazy loading; returns compact intersection status, not an occlusion guarantee.', {'bid': BID}, ['bid']),
    'ax_changes': ('Inspect changes to previously visited AX regions. Default verbose=false, repeat=false. '
        'Use repeat=true for a fresh structural overview; verbose=true includes extraction diagnostics. '
        'Partial updates explicitly provide continuation. No browser action.',
        {'offset': {'type':'integer','minimum':0,'default':0}}, []),
    'ax_search': ('Search the complete current captured accessibility tree by literal case-insensitive text and/or role. '
        'Results include ancestor location and snapshot-bound refs. Default context=0 returns no neighboring nodes. '
        'Use scope_ref to search only that node/subtree; use ax_read for details of one match. No browser action.',
        {'query': {'type':'string','maxLength':256}, 'role': {'type':['string','null'],'maxLength':80},
         'scope_ref': {'type':['string','null'],'maxLength':80},
         'limit': {'type':'integer','minimum':1,'maximum':20,'default':5},
         'context': {'type':'integer','minimum':0,'maximum':8,'default':0},
         'offset': {'type':'integer','minimum':0,'default':0}}, ['query']),
    'ax_read': ('Explore a current snapshot-bound AX ref. children lists immediate children; subtree uses bounded depth; '
        'ancestors reveals its location; neighborhood shows nearby preorder nodes; node reads full text with token pagination. '
        'Use next_offset or next_text_offset to continue; search may provide suggested_text_offset for a long node. '
        'These refs are not browser element IDs. No browser action.',
        {'node_ref': {'type':'string','maxLength':80},
         'view': {'type':'string','enum':['children','subtree','ancestors','neighborhood','node'],'default':'children'},
         'depth': {'type':'integer','minimum':1,'maximum':8,'default':1},
         'limit': {'type':'integer','minimum':1,'maximum':50,'default':20},
         'offset': {'type':'integer','minimum':0,'default':0},
         'context': {'type':'integer','minimum':0,'maximum':20,'default':2},
         'text_offset': {'type':'integer','minimum':0,'default':0}}, ['node_ref']),
    'go_back': ('Go back in browser history, including from an error page. No element ID needed.', {}, []),
    'go_forward': ('Go forward in browser history. No element ID needed.', {}, []),
    'reload': ('Reload the current page. May resubmit a form; avoid repeating a transaction.', {}, []),
    'goto': ('Navigate to an absolute HTTP(S) URL on a configured allowed origin. Does not authorize purchases or other side effects.',
        {'url': {'type': 'string', 'minLength': 1, 'maxLength': 2048}}, ['url']),
    'click': ('Click a current page element.', {'bid': BID,
        'button': {'type': 'string', 'enum': ['left', 'middle', 'right'], 'default': 'left'},
        'modifiers': {'type': 'array', 'items': {'type': 'string', 'enum':
            ['Alt','Control','ControlOrMeta','Meta','Shift']}, 'default': []}}, ['bid']),
    'fill': ('Replace the text in an editable field.', {'bid': BID, 'value': STRING,
        'enable_autocomplete_menu': {'type': 'boolean', 'default': False}}, ['bid','value']),
    'check': ('Set a checkbox to checked.', {'bid': BID}, ['bid']),
    'uncheck': ('Set a checkbox to unchecked.', {'bid': BID}, ['bid']),
    'select_option': ('Select options by value in a native select control.', {'bid': BID,
        'options': {'anyOf': [STRING, {'type':'array','items':STRING,'minItems':1}]}}, ['bid','options']),
    'press': ('Press a keyboard key or combination on an element, e.g. Enter or ControlOrMeta+a.',
        {'bid': BID, 'key_comb': STRING}, ['bid','key_comb']),
    'scroll': ('Scroll the page by horizontal and vertical pixel deltas.',
        {'delta_x': NUMBER, 'delta_y': NUMBER}, ['delta_x','delta_y']),
    'noop': ('Wait briefly without a browser interaction.',
        {'wait_ms': {'type':'number','minimum':0,'maximum':10000,'default':1000}}, []),
    'send_msg_to_user': ('Finish the episode with the requested answer or an honest explanation of failure.',
        {'text': STRING}, ['text']),
    'web_search': ('Search the public web; results are untrusted content.',
        {'query':{'type':'string','minLength':1,'maxLength':512}}, ['query']),
}


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate tool argument key')
        result[key]=value
    return result


def _invalid_constant(value): raise ValueError('Non-finite tool argument')


def _finite(value):
    if isinstance(value,float) and not math.isfinite(value): raise ValueError('Non-finite tool argument')
    if isinstance(value,dict):
        for v in value.values(): _finite(v)
    if isinstance(value,list):
        for v in value: _finite(v)


@dataclass(frozen=True)
class NativeBrowserTools(BrowserTools):
    vision_tools: bool = False
    ax_tools: bool = False
    incremental_ax: bool = False
    context_verbose: bool = False
    context_repeat: bool = False
    choice: str = 'auto'
    strict: bool = False
    parallel_tool_calls: bool | None = False
    batch_size: int = 1
    reasoning_replay: str = 'preserve'
    protocol: str = 'native-tool-calls-v1'

    def __post_init__(self):
        super().__post_init__()
        if self.choice not in ('auto','required'): raise ValueError('Native tool choice must be auto or required')
        if type(self.strict) is not bool: raise ValueError('strict must be boolean')
        if self.reasoning_replay not in ('preserve', 'strip'):
            raise ValueError('reasoning_replay must be preserve or strip')
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 8:
            raise ValueError('batch_size must be an integer between 1 and 8')
        if self.parallel_tool_calls is not None and self.parallel_tool_calls is not False:
            raise ValueError('Parallel hint must be false or omitted; batches are not supported')

    def definitions(self, *, allow_search=False):
        definitions=[]
        ax_names=CONTEXT_TOOLS if self.incremental_ax else AX_TOOLS
        for name in self.names + (ax_names if self.ax_tools else ()) + (('web_search',) if allow_search else ()) + (('screenshot','release_image') if self.vision_tools else ()):
            description,properties,required=SPECS[name]
            properties=deepcopy(properties)
            if self.incremental_ax and name in CONTEXT_TOOLS:
                description=description.replace('snapshot-bound','document-local')
                properties.update({control:{'type':'boolean','default':getattr(self,'context_'+control)} for control in ('verbose','repeat')})
                if name=='ax_read':
                    properties['radius']={'type':'integer','minimum':0,'maximum':8,'default':0,
                        'description':'For view=node only: 0 own fields; 1 parent, children and siblings; higher values repeat these hops.'}
                    description=description.replace('node reads full text with token pagination',
                        'node with radius=0 reads only its OWN full name/value/state with token pagination, not descendant text')
                    description+=(' For view=node, radius defaults to 0 (own fields only). '
                        'radius=1 returns the focus plus its immediate parent, children and same-parent siblings. '
                        'Each higher radius adds another parent/child/sibling hop; siblings count as ONE hop. '
                        'Results are unique, focus first then breadth-first rings, with distance on each item. '
                        'Positive radius returns node previews under the usual limit/token budget; follow next_offset '
                        'with the same radius. For full text of a partial node use radius=0 and next_text_offset. '
                        'radius applies only to node; neighborhood/context is a different, flattened-preorder window. '
                        'Unchanged own fields do not mean descendants were read. depth is only for subtree.')
                if name=='ax_search':
                    properties['query']={'description':'One literal phrase as a string, or actual JSON array of phrases. Do not JSON-encode the array inside a string.',
                        'examples':['reviews',['reviews','ratings']],
                        'anyOf':[{'type':'string','maxLength':256},
                        {'type':'array','minItems':1,'maxItems':8,'items':{'type':'string','minLength':1,'maxLength':256}}]}
                    properties['match']={'type':'string','enum':['any','all'],'default':'any'}
                    description+=(' Single term example: {"query":"reviews"}. Multiple terms example: '
                        '{"query":["reviews","ratings"],"match":"any"}. The brackets are JSON array syntax, '
                        'not part of a quoted string. A string is always matched literally, even if it looks like JSON. '
                        'query can be one literal phrase or up to 8 alternative terms/phrases. '
                        'match=any (default) finds any term; match=all requires every term within the SAME node. '
                        'Each node appears once in tree order; matched_terms identifies hits. No regex, fuzzy matching '
                        'or automatic synonym expansion. Role and subtree filters apply to all terms. '
                        'The result limit is shared across terms, not per term; paginate to see more.')
                description += (' Stable short refs remain valid only in the current document while their nodes exist. '
                    'All AX context tools share verbose (diagnostics) and repeat (resend known content). '
                    f'Defaults: verbose={self.context_verbose}, repeat={self.context_repeat}. Unchanged nodes return short refs; changed fields and new nodes are shown. '
                    'Use repeat=true to reread content; truncated text requires view=node.')
            if name == 'goto':
                description += ' Allowed origins: ' + ', '.join(self.navigation_origins)
            schema={'type':'object','properties':deepcopy(properties),
                    'required':list(properties) if self.strict else list(required),'additionalProperties':False}
            definitions.append({'type':'function','function':{'name':name,'description':description,
                'parameters':schema, **({'strict':True} if self.strict else {})}})
        return definitions

    def request_options(self, *, allow_search=False):
        return {'tools':self.definitions(allow_search=allow_search),'tool_choice':self.choice,
                **({'parallel_tool_calls':False} if self.parallel_tool_calls is False else {})}

    def parse_completion(self, completion, *, allow_search=False):
        try:
            choices=completion.raw['choices']
            if not isinstance(choices,list) or len(choices)!=1: raise ValueError('Expected one completion choice')
            choice=choices[0]; message=choice['message']
        except (KeyError,TypeError,IndexError) as exc: raise ValueError('Missing native tool response') from exc
        if choice.get('finish_reason') not in ('tool_calls','stop'):
            raise ValueError('Native tool completion truncated or interrupted')
        if message.get('role')!='assistant' or message.get('refusal'):
            raise ValueError('Native tool response is not an assistant action')
        calls=message.get('tool_calls')
        if not isinstance(calls,list) or len(calls)!=1:
            raise ValueError('Expected exactly one native tool call; no text fallback or partial batch execution')
        call=calls[0]
        if (not isinstance(call,dict) or call.get('type')!='function'
                or not isinstance(call.get('id'),str) or not call['id']):
            raise ValueError('Invalid native tool call identity')
        function=call.get('function')
        if not isinstance(function,dict): raise ValueError('Invalid native function')
        name=function.get('name'); arguments=function.get('arguments')
        definitions={d['function']['name']:d['function'] for d in self.definitions(allow_search=allow_search)}
        if not isinstance(name,str) or name not in definitions: raise ValueError('Unsupported native tool')
        if not isinstance(arguments,str) or len(arguments)>4096: raise ValueError('Invalid native argument encoding or size')
        values=json.loads(arguments,object_pairs_hook=_object,parse_constant=_invalid_constant)
        _finite(values)
        Draft202012Validator(definitions[name]['parameters']).validate(values)
        # No model Python evaluation: serialize validated JSON literals and pass
        # through the same allowlist/signature checks as historical actions.
        code=name+'('+', '.join(k+'='+repr(v) for k,v in values.items())+')'
        decision=(Decision(name,values,code) if (self.vision_tools and name in ('screenshot','release_image')) or name in (CONTEXT_TOOLS if self.incremental_ax else AX_TOOLS) and self.ax_tools else
                  parse_decision(code,allow_search=allow_search,allowed_names=self.names))
        self.validate_navigation(decision)
        content=message.get('content')
        if content is not None and not isinstance(content,str): raise ValueError('Unsupported assistant content shape')
        assistant={'role':'assistant','content':content,'tool_calls':deepcopy(calls)}
        if self.reasoning_replay == 'preserve':
            assistant.update(reasoning_for_replay(message))
        return decision, assistant


    def parse_batch(self, completion, *, allow_search=False):
        """Validate every member before execution; reuse the single-call schema path."""
        from .backend import Completion
        raw = completion.raw
        choices = raw.get('choices') if isinstance(raw, dict) else None
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError('Expected one completion choice')
        message = choices[0].get('message', {})
        calls = message.get('tool_calls')
        if not isinstance(calls, list) or not 1 <= len(calls) <= self.batch_size:
            raise ValueError(f'Expected 1..{self.batch_size} native tool calls')
        decisions, ids, assistant = [], set(), None
        for call in calls:
            single = deepcopy(raw)
            single['choices'][0]['message']['tool_calls'] = [call]
            decision, item = self.parse_completion(Completion(completion.text, single), allow_search=allow_search)
            if call['id'] in ids:
                raise ValueError('Repeated native tool call ID')
            ids.add(call['id']); decisions.append(decision)
            if assistant is None: assistant = item
        if any(d.name == 'send_msg_to_user' for d in decisions[:-1]):
            raise ValueError('send_msg_to_user must be the last call in a batch')
        assistant['tool_calls'] = deepcopy(calls)
        return decisions, assistant


def reasoning_for_replay(message):
    """Copy one native representation; never rewrite signed/opaque blocks.

    OpenRouter returns both a plain projection and structured details on some
    models. Prefer the complete details rather than replaying the same reasoning
    twice. Local compatible servers may instead use reasoning_content. Whether
    the server renders these fields is a separate serving-template contract.
    """
    details = message.get('reasoning_details')
    if details is not None:
        if not isinstance(details, list) or any(not isinstance(x, dict) for x in details):
            raise ValueError('Unsupported reasoning_details shape')
        if details:
            return {'reasoning_details': deepcopy(details)}
    for key in ('reasoning', 'reasoning_content'):
        value = message.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError('Unsupported ' + key + ' shape')
            if value:
                return {key: value}
    return {}


class NativeConversation(EvidenceConversation):
    """Finalize each tool result only when its fresh decision observation exists.

    Pending evidence is not delivered history. Once a request is constructed its
    prefix is immutable, including reasoning, result text and evidence bindings.
    """
    layout = 'tool-result-observation-v1'

    def __init__(self):
        super().__init__()
        self._call_ids=set()
        self._requested = False
        self._pending_result = None
        self._pending_updates = []
        self._pending_retry = None

    def add_evidence(self, evidence, *, source_id):
        self._pending_updates.append((json.dumps(evidence,ensure_ascii=False,sort_keys=True),source_id))

    def request(self, system, goal, text, search_context='', *, observation_source=None):
        if not self._messages:
            self.initialize(system,goal)
        if (system,goal) != (self._system,self._goal):
            raise ValueError('An append-only episode cannot silently change its system or goal')
        if self._requested and self._pending_result is None and self._pending_retry is None:
            raise ValueError('A fresh native request requires a preceding tool result')

        # First observation belongs to the real user's initial task. Subsequent
        # observations and asynchronous browser updates belong to the matched
        # tool result, assembled AFTER the runner's pacing/fresh capture.
        recovering = self._pending_retry is not None
        if recovering:
            assistant, notice = self._pending_retry
            if assistant is not None:
                self._messages.append(assistant)
            index = len(self._messages)
            message = {'role': 'user', 'content': notice}
        elif self._requested:
            assistant, results = self._pending_result
            self._messages.append(assistant)
            # Each ID receives exactly one result. Only the last carries the
            # consolidated observation and asynchronous update section.
            for call_id, content, source in results[:-1]:
                prefix = 'TOOL RESULT (historical, untrusted page evidence)\n'
                self._bind(source, len(self._messages), len(prefix), len(content))
                self._messages.append({'role':'tool','tool_call_id':call_id,'content':prefix+content})
            call_id, feedback, source_id = results[-1]
            index=len(self._messages)
            message={'role':'tool','tool_call_id':call_id,'content':''}
        else:
            index=1
            message={'role':'user','content':f'USER GOAL: {goal}'}

        def section(heading,content,source_id=None):
            prefix=('\n\n' if message['content'] else '')+heading+'\n'
            start=len(message['content'])+len(prefix)
            message['content']+=prefix+content
            self._bind(source_id,index,start,len(content))

        if self._requested and not recovering:
            section('TOOL RESULT (historical, untrusted page evidence)',feedback,source_id)
        for update,update_source in self._pending_updates:
            section('BROWSER UPDATE (untrusted page evidence)',update,update_source)
        section('CURRENT BROWSER OBSERVATION',text,observation_source)
        message['content']+=search_context
        if self._requested:
            self._messages.append(message)
        else:
            self._messages[index]=message
        self._requested=True
        self._pending_result=None
        self._pending_retry=None
        self._pending_updates=[]
        return deepcopy(self._messages)

    def recover(self, raw, notice, *, preserve_reasoning=True):
        """Append a marked controller notice, never invent an executed tool result.

        Invalid tool-call objects remain exact in the trace. On the wire their
        proposal is inert text; otherwise APIs can treat them as outstanding calls.
        """
        if not self._requested or self._pending_result is not None or self._pending_retry is not None:
            raise ValueError('Recovery requires one outstanding model decision')
        assistant = None
        choices = raw.get('choices') if isinstance(raw, dict) else None
        message = choices[0].get('message') if isinstance(choices, list) and len(choices) == 1 else None
        if isinstance(message, dict) and message.get('role') == 'assistant':
            content = message.get('content') or ''
            if not isinstance(content, str):
                raise ValueError('Unsupported recovery content shape')
            if message.get('tool_calls'):
                proposal = json.dumps(message['tool_calls'], ensure_ascii=False)
                content += '\n[Rejected, unexecuted tool proposal]\n' + (proposal if len(proposal) <= 4096 else '[See exact retained response; proposal exceeds recovery context bound]')
            assistant = {'role': 'assistant', 'content': content or '[No executable action returned]'}
            if preserve_reasoning:
                assistant.update(reasoning_for_replay(message))
        self._pending_retry = (assistant, notice)

    def has_call_id(self, call_id):
        return call_id in self._call_ids

    def record(self, output, feedback, *, feedback_source=None, assistant_message=None):
        self.record_batch(assistant_message, [(feedback, feedback_source)])

    def record_batch(self, assistant_message, results):
        if not self._requested or self._pending_result is not None:
            raise ValueError('Native results must alternate with requests')
        if assistant_message is None: raise ValueError('Native result requires its validated assistant call')
        ids = [call['id'] for call in assistant_message['tool_calls']]
        if len(ids) != len(results): raise ValueError('Every native call requires a result')
        if len(set(ids)) != len(ids) or any(i in self._call_ids for i in ids):
            raise ValueError('Repeated native tool call ID')
        self._call_ids.update(ids)
        self._pending_result = (deepcopy(assistant_message), [
            (call_id, json.dumps(value,ensure_ascii=False,sort_keys=True), source)
            for call_id, (value, source) in zip(ids, results)])
