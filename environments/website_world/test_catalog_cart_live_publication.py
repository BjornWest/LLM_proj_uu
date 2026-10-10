from copy import deepcopy
import json
from pathlib import Path

import pytest
from environments.website_world import catalog_cart_live_publication as publication

FIXTURE = Path(__file__).resolve().parents[2]/'.local/coordination/task-support-expansion-20261007/cart-world-v1'


@pytest.mark.parametrize('fault', ['kind', 'field', 'quantity', 'extra'])
def test_invalid_task_rejects_before_sampling(fault):
    request = json.loads((FIXTURE/'request.json').read_text())
    if fault == 'kind': request['task']['kind'] = 'cheapest_available'
    if fault == 'field': request['task']['requirements'][0]['predicates'][0]['field'] = 'unknown'
    if fault == 'quantity': request['task']['requirements'][0]['quantity'] = 0
    if fault == 'extra': request['task']['unexpected'] = True
    def forbidden(*args, **kwargs): raise AssertionError('Invalid task reached sampler')
    with pytest.raises(ValueError): publication.generate(request, world_factory=forbidden)


def test_new_generation_preserves_native_fields_and_old_guard(monkeypatch):
    request = json.loads((FIXTURE/'request.json').read_text())
    config = publication.compile_request(request)
    native = {'catalog_cart_task': {'memories': []}, 'resolved_configuration': {}}
    factory = object(); seen = []
    def generate(request, *, world_factory=None):
        seen.append(world_factory)
        return deepcopy(native)
    monkeypatch.setattr(publication.cart.native, 'generate', generate)
    result = publication.generate(request, world_factory=factory)
    assert result['cart_field_inventory'] == config['publication_inventory']
    assert result['catalog_cart_task'] == native['catalog_cart_task'] and seen == [factory]
    assert not publication.cart.RUNTIME_RELEASED
    with pytest.raises(RuntimeError): publication.cart.require_release()


def test_prepare_adds_explicit_identity_without_flipping_old_guard(tmp_path, monkeypatch):
    def freeze(request, output, **kwargs):
        output.mkdir()
        (output/'generation-config.private.json').write_text('{}')
        return {'recipe': publication.cart.VERSION, 'files': {}}
    monkeypatch.setattr(publication.cart, 'prepare', freeze)
    target = tmp_path/'recipe'
    result = publication.prepare({}, target)
    assert result['recipe'] == publication.cart.VERSION
    assert result['cart_live_recipe'] == publication.VERSION
    assert json.loads((target/'generation-config.private.json').read_text())['cart_live_recipe'] == publication.VERSION
    assert not publication.cart.RUNTIME_RELEASED and result['automatic_grader_supported'] is False


def test_answer_formatter_rejects_before_creating_output(tmp_path):
    with pytest.raises(ValueError, match='answer extraction'):
        publication.prepare({}, tmp_path/'recipe', answer_grading={'mode': 'subscription-post-run'})
    assert not (tmp_path/'recipe').exists()
