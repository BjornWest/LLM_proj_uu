"""Korp "flock" mode: the main agent runs helper agents in parallel.

Each helper is an ordinary Korp episode in its own process (own model connection and
browser tab/window). The main agent and helpers talk through the Korp backend
(/api/flock/*): helpers report with message_main_agent and then wait until the main
agent replies (message_helper) or closes them (close_helper).
"""
import json
import time
import urllib.request

from intent_browser.native_tools import register_host_tool

MAX_HELPERS = 4

register_host_tool('spawn_helper',
    'Start a helper agent that works in parallel with you on a self-contained subtask, in its own browser tab '
    'or window, with the same browsing tools (but no helpers of its own). It does not see this conversation or '
    'the user\'s memory: put every needed detail (product, size, location, currency, constraints, what to report) '
    'in task. window="new_window": a separate background window (best for most parallel research); '
    'window="this_window": a new tab in the user\'s current window so they can watch it. Returns helper_id.',
    {'task': {'type': 'string', 'minLength': 1, 'maxLength': 3000},
     'name': {'type': 'string', 'minLength': 1, 'maxLength': 40,
              'description': 'Short label shown to the user, e.g. "Store A" or "Berlin hotels".'},
     'window': {'type': 'string', 'enum': ['new_window', 'this_window']}},
    ['task', 'name', 'window'])
register_host_tool('wait_for_helpers',
    'Wait until at least one helper reports (or the timeout passes) and return their new messages and every '
    'helper\'s state. A helper that reported is paused until you message or close it.',
    {'timeout_seconds': {'type': 'number', 'minimum': 5, 'maximum': 120, 'default': 60}}, [])
register_host_tool('message_helper',
    'Reply to a paused helper (answer its question or give it a follow-up task); it continues working.',
    {'helper_id': {'type': 'string', 'minLength': 1, 'maxLength': 80},
     'text': {'type': 'string', 'minLength': 1, 'maxLength': 3000}}, ['helper_id', 'text'])
register_host_tool('close_helper',
    'End a helper\'s conversation once you have what you need from it (its window closes). '
    'Close every helper before you answer the user.',
    {'helper_id': {'type': 'string', 'minLength': 1, 'maxLength': 80}}, ['helper_id'])
register_host_tool('message_main_agent',
    'Send your findings or a question to the main agent that started you. You then pause until it replies '
    '(the reply is returned) or ends your conversation.',
    {'text': {'type': 'string', 'minLength': 1, 'maxLength': 6000}}, ['text'])

MAIN_TOOLS = ('spawn_helper', 'wait_for_helpers', 'message_helper', 'close_helper')
HELPER_TOOLS = ('message_main_agent',)

MAIN_POLICY = (
    "Flock mode (chosen by the user): you lead a flock of up to %d helper agents that browse in parallel, and "
    "the user wants to see you use them. Before browsing yourself, split the request into its independent "
    "parts (each store, product, city, date, site or question to check) and call spawn_helper once per part "
    "in the same response, with a complete, self-contained task each (helpers do not see this conversation "
    "or the user's memory: include location, sizes, budget, currency and what to report). Prefer "
    "window=\"new_window\"; use window=\"this_window\" for one helper the user should watch. While they work "
    "you may check something yourself; then call wait_for_helpers until every helper has reported, answer "
    "their questions with message_helper, and close_helper each one once you have its result. Treat reports "
    "as claims with links. Close all helpers, then combine everything into one answer with send_msg_to_user. "
    "Work alone only when the request truly has a single part, or to ask the user a follow-up question first."
    % MAX_HELPERS)

HELPER_POLICY = (
    "You are a helper agent named \"%s\" working for a main Korp agent, not directly for the user. Do the task "
    "below with your browser tools, then report with message_main_agent: concrete findings, prices, links to "
    "the pages you inspected and any uncertainty. If you need a decision, ask the main agent with "
    "message_main_agent. Never ask the user, never call send_msg_to_user, do not hand tabs over and do not "
    "change stored memory. If a site blocks you with a bot check, report that to the main agent instead. "
    "After reporting, wait for the main agent's reply and follow it.")


class FlockClient:
    """Host-tool handler of one Korp episode (main or helper)."""

    def __init__(self, port, run_id, emit, pump=None):
        self.base = f'http://127.0.0.1:{port}/api/flock/'
        self.run_id, self.emit = run_id, emit
        # Every agent's request filter on the shared browser must keep answering while this one
        # waits, or the other agents' page loads stall: waits are short polls that pump browser events.
        self.pump = pump or (lambda: time.sleep(0.2))

    def call(self, action, timeout=30, **data):
        request = urllib.request.Request(self.base + action, json.dumps(data).encode(),
            {'Content-Type': 'application/json'}, method='POST')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read())
            except Exception:
                return {'error': f'HTTP {exc.code}'}

    def __call__(self, name, args):
        if name == 'spawn_helper':
            return self.call('spawn', parent=self.run_id, task=args['task'], name=args['name'],
                             window=args['window'])
        if name == 'wait_for_helpers':
            deadline = time.monotonic() + float(args.get('timeout_seconds', 60))
            while True:
                result = self.call('wait_main', parent=self.run_id, timeout_seconds=1)
                if (result.get('error') or result.get('messages') or time.monotonic() >= deadline
                        or not any(h.get('state') == 'working' for h in result.get('helpers', []))):
                    return result
                self.pump()
        if name == 'message_helper':
            return self.call('message', parent=self.run_id, helper=args['helper_id'], text=args['text'])
        if name == 'close_helper':
            return self.call('close', parent=self.run_id, helper=args['helper_id'])
        if name == 'message_main_agent':
            sent = self.call('to_main', helper=self.run_id, text=args['text'])
            if sent.get('error'):
                return sent
            self.emit('step', summary='Waiting for the main agent', page=False)
            while True:  # Paused until the main agent replies or ends this conversation.
                reply = self.call('wait_reply', helper=self.run_id, timeout_seconds=1)
                if reply.get('reply') or reply.get('closed') or reply.get('error'):
                    return reply
                self.pump()
        return {'error': 'Unknown flock tool ' + name}
