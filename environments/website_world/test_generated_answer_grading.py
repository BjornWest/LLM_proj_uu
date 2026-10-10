"""Actual GeneratedEpisode wiring with a saved-world runtime stub; no draws."""
import json
from types import SimpleNamespace
import pytest

from environments.website_world import generation, unified_generation
from environments.website_world.test_listed_offer_grading import fixture, answer
from intent_browser.graded_world_task import GradedWorldTask


@pytest.mark.parametrize('lazy', [None, False, True])
def test_generated_episode_binds_grader_discovery_and_configured_extractor(tmp_path, monkeypatch, lazy):
    world, task, reference, bindings = fixture()
    public = {'schema_version': 'fixture', 'task_id': task['task_id'], 'user_message': task['user_message'],
              'memories': [], 'environment_context': {}, 'start_url': 'https://a.test/'}
    def save(name, value): (tmp_path/name).write_text(json.dumps(value))
    save('episode.json', {'start': {'kind': 'tool_discovery'}})
    save('presentation.json', {})
    save('compositions.private.json', {})
    save('basic-offer-task.private.json', task)
    save('basic-offer-reference.private.json', reference)
    monkeypatch.setattr(generation, 'load', lambda path: {'schema': 'website-world-generation-v2', 'files': {}, 'source_sha256': {}})
    monkeypatch.setattr(unified_generation, 'bind_task', lambda runtime, episode: public)
    closed = []
    runtime = SimpleNamespace(world=world, bindings=bindings, compositions={}, origin_map=None,
                              navigation_origins=['https://a.test/'], site_discovery=SimpleNamespace(search=lambda **kw: {}),
                              close=lambda: closed.append(True))
    from environments.website_world import runtime as module
    forwarded = []
    def make_runtime(*a, **kw):
        forwarded.append(kw['lazy_publication'])
        return runtime
    monkeypatch.setattr(module, 'Runtime', make_runtime)
    def extractor(grader, public, text, output): return grader.grade(answer()[1], text)
    kwargs = {} if lazy is None else {'lazy_publication': lazy}
    with generation.GeneratedEpisode(tmp_path, answer_extractor=extractor, **kwargs) as ep:
        assert isinstance(ep.task, GradedWorldTask)
        assert ep.task.answer_extractor is extractor
        assert ep.site_discovery == runtime.site_discovery.search
        text, claims = answer()
        assert ep.grade_answer_claims(claims, text)['structured_claims_correct'] is True
        trace = tmp_path/'trace'; trace.mkdir()
        env = SimpleNamespace(unwrapped=SimpleNamespace(chat=SimpleNamespace(messages=[{'role': 'assistant', 'message': text}])))
        evaluation = ep.task.evaluate(env, SimpleNamespace(directory=trace), {'stop_reason': 'agent_finished', 'error': None})
        assert evaluation.task_completed is True
    assert closed == [True]
    assert forwarded == [lazy is True]


@pytest.mark.parametrize('value', [None, 0, 1, 'true', {}])
def test_invalid_lazy_flag_rejects_before_loading_or_startup(tmp_path, monkeypatch, value):
    monkeypatch.setattr(generation, 'load', lambda *a: pytest.fail('Loaded invalid recipe'))
    with pytest.raises(ValueError, match='must be a bool'):
        generation.GeneratedEpisode(tmp_path, lazy_publication=value)
