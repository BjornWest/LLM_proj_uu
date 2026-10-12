"""Qualified factory/admission boundaries; no browser/model launch in unit tests."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from browsergym.core.env import BrowserEnv
from browsergym.core.task import OpenEndedTask
from intent_browser.chromium_pool import PoolClient, PoolError, PoolSupervisor, VERSION, installed_manifest
from intent_browser.shared_browsergym import PoolEpisode, SharedBrowserEnv, qualify_browsergym


class PoolBoundaries(unittest.TestCase):
    def test_supervisor_rejects_unbounded_or_boolean_caps(self):
        for name in ('max_servers','max_leases','per_server','pending_seconds'):
            for value in (0,-1,True,1.5,1000):
                with self.subTest(name=name,value=value), self.assertRaises(ValueError):
                    PoolSupervisor(Path('/unused'), **{name:value})

    def test_client_rejects_mismatched_manifest(self):
        manifest={'qualified':'one'}
        with patch('intent_browser.chromium_pool.installed_manifest',return_value=(None,None,manifest)):
            with self.assertRaises(PoolError):
                PoolClient({'version':VERSION,'manifest':{'qualified':'other'}})
            for timeout in (0,-1,True,31,float('inf')):
                with self.assertRaises(ValueError):PoolClient({'version':VERSION},timeout=timeout)

    def test_manifest_qualifies_shutdown_helper_before_attachment(self):
        import hashlib
        import intent_browser.browser_shutdown as shutdown
        _, _, manifest = installed_manifest()
        self.assertEqual(manifest['browsergym_shutdown_sha256'],
                         hashlib.sha256(Path(shutdown.__file__).read_bytes()).hexdigest())
        missing = dict(manifest); missing.pop('browsergym_shutdown_sha256')
        changed = dict(manifest); changed['browsergym_shutdown_sha256'] = 'different'
        for stale in (missing, changed):
            with self.subTest(stale=stale['browsergym_adapter_sha256']), self.assertRaises(PoolError):
                PoolClient({'version': VERSION, 'manifest': stale})

    def test_browsergym_changed_binding_is_rejected(self):
        qualify_browsergym()
        with patch.object(BrowserEnv,'reset',lambda *a:None),self.assertRaises(PoolError):
            qualify_browsergym()
        with patch.dict(BrowserEnv.reset.__globals__,{'_get_global_playwright':lambda:None}),self.assertRaises(PoolError):
            qualify_browsergym()

    def test_native_wrap_retains_all_constructor_options(self):
        original=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':'about:blank'},
            viewport={'width':740,'height':660},slow_mo=31,headless=True,
            pw_context_kwargs={'locale':'sv-SE','accept_downloads':False})
        episode=PoolEpisode(object(),'wrap-owner')
        pooled=SharedBrowserEnv.from_native(original,pool_episode=episode)
        for name in ('task_entrypoint','task_kwargs','viewport','slow_mo','headless','pw_context_kwargs'):
            self.assertEqual(getattr(original,name),getattr(pooled,name))
        self.assertIsNone(original.browser)
        self.assertIs(pooled._get_obs.__func__,BrowserEnv._get_obs)
        self.assertIs(pooled.step.__func__,BrowserEnv.step)

    def test_custom_or_used_env_is_not_silently_adopted(self):
        class Custom(BrowserEnv):pass
        episode=PoolEpisode(object(),'reject-owner')
        for env in (Custom(task_entrypoint=OpenEndedTask),BrowserEnv(task_entrypoint=OpenEndedTask)):
            env.page=object()
            with self.assertRaises(PoolError):SharedBrowserEnv.from_native(env,pool_episode=episode)
        env=BrowserEnv(task_entrypoint=OpenEndedTask);env.reset=lambda *a:None
        with self.assertRaises(PoolError):SharedBrowserEnv.from_native(env,pool_episode=episode)
        env=BrowserEnv(task_entrypoint=OpenEndedTask);env.custom_reference='do not discard'
        with self.assertRaises(PoolError):SharedBrowserEnv.from_native(env,pool_episode=episode)

    def test_explicit_owner_and_background_types(self):
        for owner in ('',None,'x'*129):
            with self.assertRaises(ValueError):PoolEpisode(object(),owner)
        with self.assertRaises(ValueError):PoolEpisode(object(),'owner',background=1)

    def test_closed_episode_refuses_new_factory_binding(self):
        episode=PoolEpisode(object(),'closed-owner');episode.close();episode.close()
        with self.assertRaises(PoolError):episode.playwright('task')


if __name__=='__main__':unittest.main()
