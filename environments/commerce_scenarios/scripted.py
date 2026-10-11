"""Scripted episodes: an authored tool sequence through the ordinary runner.

No model or provider is involved. Each "completion" is one tool call computed
from the live page and returned by an in-process `httpx.MockTransport`. The
recording is tagged `scripted` and graded by whatever contract the caller gives.
"""
import json

VERSION = 'website-commerce-scenario-scripted-v1'


def click(node):
    """Tool call that clicks a live element through its current browser id."""
    return 'click', {'bid': _bid(node)}


def fill(node, value):
    return 'fill', {'bid': _bid(node), 'value': value}


def say(text):
    """Final message to the user; ends the episode."""
    return 'send_msg_to_user', {'text': text}


def _bid(node):
    bid = node.get_attribute('bid')
    if not bid:
        raise ValueError('Scripted control has no current browser id')
    return bid


def run(episode, next_action, output, *, contract, finalize=None, metadata=None,
        max_steps=40, max_input_tokens=32000, model='scripted-commerce-scenario'):
    """Run `next_action(page) -> (tool, arguments)` to its final message and grade it.

    `contract` is an `AutomaticGrading` with phase 'external'. The episode (and
    its Runtime) is closed before `finalize(trace_directory)` runs; by default
    that is the harness's `finalize_external` for the same contract.
    """
    import httpx
    from intent_browser.backend import ChatCompletionsBackend
    from intent_browser.runner import run_episode
    if getattr(contract, 'phase', None) != 'external':
        raise ValueError('Scenario grading seals after Runtime cleanup; use an external-phase contract')
    holder, actions = {}, []

    def make_env(video=None):
        holder['env'] = episode.task.make_env(video)
        return holder['env']

    def transport(request):
        tool, arguments = next_action(holder['env'].unwrapped.page)
        actions.append({'tool': tool, 'arguments': arguments})
        return httpx.Response(200, json={'model': model, 'choices': [{
            'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [{
                'id': 'call-' + str(len(actions)), 'type': 'function',
                'function': {'name': tool, 'arguments': json.dumps(arguments)}}]}}]})

    backend = ChatCompletionsBackend('https://offline.invalid/v1', model, supports_images=True)
    backend.client.close()
    backend.client = httpx.Client(transport=httpx.MockTransport(transport))
    backend.requires_browser_thread = True  # next_action reads the live page
    metadata = dict(metadata or {})
    metadata['tags'] = list(dict.fromkeys([*metadata.get('tags', []), 'scripted']))
    metadata.update(driver='offline HTTP mock', training_eligible=False)
    try:
        with episode:
            trace, summary = run_episode(
                make_env, backend, metadata, output=output, episode_task=episode.task,
                harness_profile=episode.profile, site_discovery=episode.site_discovery,
                observation_pipeline='native', automatic_grading=contract,
                max_steps=max_steps, max_input_tokens=max_input_tokens, trace_screenshots=False)
    finally:
        backend.close()
    if finalize is None:
        from intent_browser.automatic_grading import finalize_external
        finalize = lambda directory: finalize_external(directory, contract)
    return {'schema': VERSION, 'trace': str(trace), 'policy_summary': summary,
            'summary': finalize(trace), 'actions': actions}
