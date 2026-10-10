from copy import deepcopy
import json
from pathlib import Path

import pytest

from environments.website_world import catalog_checkout_details_publication as publication

FIXTURE = Path(__file__).resolve().parents[2]/'.local/coordination/task-support-expansion-20261007/checkout-details-world-v1'


@pytest.mark.parametrize('change', ['missing_note', 'wrong_kind', 'unknown_field', 'unsupported_field'])
def test_invalid_requirements_reject_before_population(change):
    request = json.loads((FIXTURE/'request.json').read_text())
    if change == 'missing_note': request['task'].pop('delivery_note')
    if change == 'wrong_kind': request['task']['kind'] = 'cheapest_available'
    if change == 'unknown_field': request['task']['extra'] = True
    if change == 'unsupported_field': request['task']['requirements'][0]['predicates'][0]['field'] = 'unknown'
    def forbidden(*args, **kwargs): raise AssertionError('Invalid request reached population')
    with pytest.raises(ValueError): publication.generate(request, world_factory=forbidden)


def test_generate_retains_native_memories_and_field_inventory(monkeypatch):
    request = json.loads((FIXTURE/'request.json').read_text())
    config = publication.compile_request(request)
    packet = {'checkout_details_task': {'memories': ['native address', 'native note']}}
    seen = []
    def generate(request, *, world_factory=None):
        seen.append(world_factory)
        return deepcopy(packet)
    monkeypatch.setattr(publication.native, 'generate', generate)
    factory = object()
    result = publication.generate(request, world_factory=factory)
    assert result['checkout_details_task'] == packet['checkout_details_task']
    assert result['checkout_details_field_inventory'] == config['publication_inventory']
    assert seen == [factory] and 'checkout_details_field_inventory' not in packet


def test_answer_extraction_is_not_a_state_capture(tmp_path):
    with pytest.raises(ValueError, match='actual storage'):
        publication.prepare({}, tmp_path/'recipe', answer_grading={'mode': 'subscription-post-run'})
    assert not (tmp_path/'recipe').exists()
