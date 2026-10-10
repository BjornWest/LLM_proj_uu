"""The public policy receives the authoritative frozen date, not wall-clock time."""
from types import SimpleNamespace

import pytest

from environments.website_world import generation, unified_generation
from intent_browser.connected_world_task import policy_goal


@pytest.mark.parametrize('binder', [generation.bind_task, unified_generation.bind_task])
def test_policy_context_exposes_frozen_scenario_date(binder):
    authored = {'user_message': 'Compare delivery dates.', 'memories': []}
    runtime = SimpleNamespace(world={'world_id': 'date-test', 'quote_as_of': '2026-09-30',
                                     'task': authored},
                              index_origin='http://localhost:12345', origins={})
    public = binder(runtime, {'start': {'kind': 'directory'}, 'manual_task': authored})
    assert public['environment_context']['scenario_date'] == '2026-09-30'
    assert '"scenario_date": "2026-09-30"' in policy_goal(public)
    assert public['memories'] == authored['memories'] == []
