import json
from pathlib import Path
from types import SimpleNamespace

from environments.website_world.test_listed_offer_grading import fixture, answer
from environments.website_world.listed_offer_grading import ListedOfferGrader
from intent_browser.graded_world_task import GradedWorldTask


PUBLIC = {'schema_version': 'test', 'task_id': 'test', 'user_message': 'Find shoes.',
          'memories': [], 'environment_context': {}, 'start_url': 'https://a.test/'}


def task(extractor=None):
    return GradedWorldTask(PUBLIC, origins=['https://a.test/'], answer_grader=ListedOfferGrader(*fixture()),
                           answer_extractor=extractor)


def env(text):
    return SimpleNamespace(unwrapped=SimpleNamespace(chat=SimpleNamespace(messages=[{'role': 'assistant', 'message': text}])))


def test_automatic_terminal_evaluation_and_pending_extraction(tmp_path):
    text, c = answer()
    def extract(grader, public, text, output):
        assert public == PUBLIC
        return grader.grade(c, text)
    t = task(extract)
    result = t.evaluate(env(text), SimpleNamespace(directory=tmp_path), {'stop_reason': 'agent_finished', 'error': None})
    assert result.task_completed is True and result.to_dict()['safe_success'] is None
    assert json.loads((tmp_path/'natural-answer.json').read_text())['text'] == text
    other = tmp_path/'pending'; other.mkdir()
    assert task().evaluate(env(text), SimpleNamespace(directory=other),
                          {'stop_reason': 'agent_finished', 'error': None}).trust == 'pending-extraction'


def test_interruption_or_extractor_error_never_becomes_answer_failure(tmp_path):
    def bad(*args): raise RuntimeError('Provider unavailable')
    t = task(bad)
    result = t.evaluate(env(answer()[0]), SimpleNamespace(directory=tmp_path), {'stop_reason': 'agent_finished', 'error': None})
    assert result.task_completed is None and result.trust == 'extraction-failed'
    assert (tmp_path/'answer-grading-error.json').is_file()
    other = tmp_path/'interrupted'; other.mkdir()
    result = t.evaluate(env(answer()[0]), SimpleNamespace(directory=other), {'stop_reason': 'interrupted', 'error': 'Interrupted'})
    assert result.task_completed is None and not (other/'answer-grade.json').exists()
