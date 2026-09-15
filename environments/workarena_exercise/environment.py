"""Reusable native WorkArena catalog environment for the local learning exercise.

Callers stage WorkArena in the isolated dependency directory and supply an
approved research instance. No credential discovery or inference happens here.
Native reward is not a certification of broad authorization preservation.
"""
from pathlib import Path


def make_catalog_env(instance, fixed_config, *, condition='clean', action_mapping,
                     headless=True, record_video_dir=None):
    if condition not in ('clean', 'injected'):
        raise ValueError('Unknown catalog exercise condition')
    from browsergym.core.env import BrowserEnv
    from browsergym.workarena.tasks.service_catalog import OrderStandardLaptopTask
    from browsergym.workarena.tasks.base import AbstractServiceNowTask
    script = Path(__file__).with_name('preselect_acrobat.js').read_text()

    class LocalCatalog(OrderStandardLaptopTask):
        def get_init_scripts(self):
            original = super().get_init_scripts()
            return original + [script] if condition == 'injected' else original

        def teardown(self):
            try:
                super().teardown()
            finally:
                # Upstream OrderHardwareTask.teardown omits the base account cleanup.
                if getattr(self, 'delete_user_on_teardown', False):
                    AbstractServiceNowTask.teardown(self)

    return BrowserEnv(task_entrypoint=LocalCatalog,
                      task_kwargs={'instance': instance, 'fixed_config': fixed_config},
                      action_mapping=action_mapping, headless=headless, slow_mo=250,
                      wait_for_user_message=False, record_video_dir=record_video_dir)
