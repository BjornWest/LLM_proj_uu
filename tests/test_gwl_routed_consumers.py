"""Real helper-routed consumer boundaries, no browser/provider/verdict fixtures."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from environments.website_world import (simulated_order_address_runner as address,
    task_instance_cart as cart, review_saved_runner as review,
    atomic_product_execution_consumer as atomic)
from intent_browser import automatic_grading, evaluation
import agent_trace.adapters.browsergym as viewer

ROOT = Path(__file__).resolve().parents[1]
CALLER = runpy.run_path(str(ROOT/'scripts/comparison_suite.py'))
MODULES = [(address, 'AddressOnlyOrderEpisode'), (cart, 'CartEpisode'),
           (review, 'SavedReviewEpisode'), (atomic, 'AtomicProductEpisode')]


@pytest.mark.parametrize('module,constructor', MODULES)
@pytest.mark.parametrize('mode', ['native', 'auto'])
@pytest.mark.parametrize('steps', [None, 7])
def test_actual_routed_run_forwards_caller_options_before_any_policy_action(
        tmp_path, module, constructor, mode, steps):
    recipe = tmp_path/'recipe'
    recipe.mkdir()
    public = {'task_id': 'offline-boundary', 'user_message': 'Original request',
              'memories': [], 'kind': 'read_listed_price'}
    names = ['pin/world.private.json', 'catalog-review-task.private.json',
             'catalog-review-reference.private.json', 'surrounding.private.json',
             'simulated-order-task.private.json', 'order-address-reference.private.json',
             'simulated-order-setup.private.json', 'catalog-cart-task.private.json',
             'catalog-cart-reference.private.json', 'cart-initial-storage.private.json',
             'checkout-domain.private.json', 'atomic-product-task.private.json',
             'atomic-product-reference.private.json', 'atomic-product-catalog.private.json',
             'atomic-product-bindings.private.json', 'atomic-product-runtime-options.private.json',
             'atomic-product-assets.private.json']
    for name in names:
        path = recipe/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(public if 'task.private' in name else {}))
    (recipe/'atomic-product-scoring-scope.private.json').write_text(json.dumps('observed_atomic_state'))
    (recipe/'execution.private.json').write_text(json.dumps({'answer_grading': {
        'mode': 'subscription-post-run', 'model': 'scripted', 'reasoning_effort': 'low'}}))
    manifest = {'files': {str(p.relative_to(recipe)): sha256(p.read_bytes()).hexdigest()
                         for p in recipe.rglob('*') if p.is_file()}}
    events, forwarded = [], []

    class Episode:
        def __init__(self, output, **kwargs):
            self.output, self.manifest = recipe, deepcopy(manifest)
            self.public, self.native_task = deepcopy(public), deepcopy(public)
            files = {str(recipe/name): digest for name, digest in manifest['files'].items()}
            for owned in (module, automatic_grading, evaluation, viewer):
                path = Path(owned.__file__).resolve()
                files[str(path)] = sha256(path.read_bytes()).hexdigest()
            files.update(kwargs.get('additional_source_files', {}))
            self.task = SimpleNamespace(make_env=lambda: None, files=files)
            self.profile, self.site_discovery = SimpleNamespace(name='offline-boundary'), None
            self.runtime = SimpleNamespace(navigation_origins=['https://offline.test'])

        def export_private_runtime(self, destination):
            destination.mkdir()
            (destination/'manifest.json').write_text('{}')
            (destination/'site-registry.private.json').write_text('{}')
            return {'files': {'site-registry.private.json': sha256(b'{}').hexdigest()}}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append('runtime_closed')

    @contextmanager
    def session(**kwargs):
        events.append('policy_open')
        try:
            yield object()
        finally:
            events.append('policy_closed')

    options = {'max_steps': steps, 'max_input_tokens': 250000,
               **{k: v for k, v in CALLER['capture_options']({'observation_pipeline': mode}).items()
                  if k != 'recording_capture'}}
    original = deepcopy(options)

    def runner(*args, automatic_grading, **kwargs):
        assert automatic_grading.phase == 'external'
        forwarded.append({key: kwargs[key] for key in options})
        events.append('runner')
        # This is a dispatch-boundary control, not a synthetic task success.
        raise RuntimeError('zero-provider dispatch boundary')

    with patch.object(module, constructor, Episode), patch.object(atomic.shared, 'load', return_value=manifest):
        result = module.run(recipe, tmp_path/'run', policy_session=session,
            metadata={'tags': ['scripted']}, runner_options=options, runner=runner,
            viewer_projection=lambda **_: None, quota_guard=lambda: None)
    assert forwarded == [original], result
    assert options == original
    assert result['status'] == 'system_failure'
    assert result['reason'] == 'zero-provider dispatch boundary'
    assert events == ['policy_open', 'runner', 'policy_closed', 'runtime_closed']


@pytest.mark.parametrize('module,constructor', MODULES)
@pytest.mark.parametrize('reserved', ['episode_task', 'automatic_grading', 'allow_ungraded', 'agent_actor'])
def test_auto_does_not_relax_original_task_grade_or_actor_bindings(tmp_path, module, constructor, reserved):
    options = {'max_steps': None, 'max_input_tokens': 250000, 'observation_pipeline': 'auto', reserved: True}
    with patch.object(module, constructor) as episode, pytest.raises(ValueError, match='bindings'):
        module.run('absent-recipe', tmp_path/'run', policy_session=lambda: None,
            metadata={'tags': ['scripted']}, runner_options=options,
            viewer_projection=lambda **_: None, quota_guard=lambda: None)
    episode.assert_not_called()
    assert not (tmp_path/'run').exists()
