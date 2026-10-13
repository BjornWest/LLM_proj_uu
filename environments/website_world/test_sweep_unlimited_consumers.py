"""Guard tests for the additional reachable frozen suite consumers."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from . import simulated_order_address_runner as address
from . import task_instance_cart as cart
from . import atomic_product_execution_consumer as atomic


class AdditionalLimitAdmission(unittest.TestCase):
    def test_invalid_or_missing_limits_reject_before_setup(self):
        invalid = [None, [], {}, {'max_input_tokens': 1000}, {'max_steps': None},
            {'max_steps': 1}, *[{'max_steps': v, 'max_input_tokens': 1000}
                for v in [True, False, 0, -1, 1.5, '20']],
            *[{'max_steps': None, 'max_input_tokens': v}
                for v in [None, True, False, 0, -1, 1.5, '1000']]]
        with TemporaryDirectory() as directory:
            destination = Path(directory)/'run'
            for module in [address, cart, atomic]:
                for options in invalid:
                    with self.subTest(consumer=module.__name__, options=options):
                        with self.assertRaisesRegex(ValueError, 'max_steps'):
                            module.run('missing-recipe', destination, policy_session=lambda: None,
                                metadata={'tags': ['scripted']}, runner_options=options,
                                viewer_projection=lambda **_: None, quota_guard=lambda: None)
                        self.assertFalse(destination.exists())

    def test_reserved_bindings_reject_before_setup_with_none(self):
        for module in [address, cart, atomic]:
            for key in ['automatic_grading', 'allow_ungraded', 'episode_task', 'backend']:
                with self.subTest(consumer=module.__name__, key=key):
                    with self.assertRaisesRegex(ValueError, 'bindings'):
                        module.run('missing-recipe', 'missing-run', policy_session=lambda: None,
                            metadata={'tags': ['scripted']},
                            runner_options={'max_steps': None, 'max_input_tokens': 1000, key: True},
                            viewer_projection=lambda **_: None, quota_guard=lambda: None)
