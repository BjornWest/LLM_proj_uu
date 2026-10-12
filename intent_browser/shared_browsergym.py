"""Pinned, instance-local BrowserGym factories for shared Chromium connections.

Native observation, action, task and chat methods remain unchanged. Reset creates
fresh contexts; context identity is read from a target created in that context,
never from a browser-wide before/after set difference.
"""
from __future__ import annotations

import hashlib
import inspect
from importlib.metadata import version
from pathlib import Path
from types import FunctionType, SimpleNamespace

from playwright.sync_api import Error as PlaywrightError

from browsergym.core import _get_global_playwright
from browsergym.core.env import BrowserEnv
from browsergym.core.chat import Chat

from .chromium_pool import PoolError, VERSION

_PINS = (
    (BrowserEnv.reset, '3251c80a8ba05683ba64cc291c257a22b0bd037a653f9b097094d3dac47e445f'),
    (BrowserEnv.close, 'f8ecb729634b9b0c56876d3bee8a3205620ec517c66c5f39173f6860bbc55a45'),
    (Chat.__init__, '05710d3584d0e05647b209d937740766803212e439151f559ed301668a1eb6d5'),
    (Chat.close, 'c49a92cf0b91c845e2daa7217435c9b09137142ce9b62d93fa3905bc53930f7b'),
)


def qualify_browsergym():
    if version('browsergym-core') != '0.14.3':
        raise PoolError('Shared Chromium requires qualified BrowserGym0.14.3')
    current = (BrowserEnv.reset, BrowserEnv.close, Chat.__init__, Chat.close)
    if current != tuple(function for function, _ in _PINS):
        raise PoolError('BrowserGym lifecycle binding changed')
    if (BrowserEnv.reset.__globals__['_get_global_playwright'] is not _get_global_playwright
            or BrowserEnv.reset.__globals__['Chat'] is not Chat
            or Chat.__init__.__globals__['_get_global_playwright'] is not _get_global_playwright):
        raise PoolError('Existing global browser/chat launch adapter requires separate qualification')
    for function, digest in _PINS:
        if hashlib.sha256(inspect.getsource(function).encode()).hexdigest() != digest:
            raise PoolError('BrowserGym factory/cleanup source changed: '+function.__qualname__)


def _scoped(function, **bindings):
    scope = {**function.__globals__, **bindings}
    result = FunctionType(function.__code__, scope, function.__name__,
                          function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


class _BrowserLease:
    def __init__(self, episode, pw, role, options):
        self.episode, self.browser, self.context = episode, None, None
        self.closed = False
        self.record = episode.client.request('acquire',
            {'owner': episode.owner, 'role': role, 'options': options})
        try:
            if self.record['manifest'] != episode.client.descriptor['manifest']:
                raise PoolError('Acquired server qualification differs')
            # Native launch slow_mo is already applied by the server; adding it
            # to this transport would delay actions a second time.
            self.browser = pw.chromium.connect(self.record['endpoint'], timeout=10000)
            if self.browser.contexts:
                raise PoolError('New pool connection unexpectedly contains previous contexts')
            if self.browser.version != self.record['manifest']['chromium_version']:
                raise PoolError('Connected Chromium version differs')
        except BaseException:
            self.close()
            raise
        episode.leases.append(self)

    def __getattr__(self, name):
        return getattr(self.browser, name)

    def new_context(self, **kwargs):
        if self.closed or self.context is not None:
            raise PoolError('Each pool connection owns exactly one fresh context')
        self.context = self.browser.new_context(**kwargs)
        original = self.context.new_page
        video_directory = kwargs.get('record_video_dir')
        videos, saved_videos = {}, set()
        self.recordings = []
        def register_video(page):
            if not video_directory or page in videos: return
            video = page.video
            filename = Path(video_directory)/(self.record['lease_id']+'-'+str(len(videos))+'.webm')
            videos[page] = (video, filename)
            # Video.path() normally throws for a remote connection. Bind only this
            # video object's public accessor to its future local save_as path.
            video.path = lambda: filename
        def identify(page):
            session = self.context.new_cdp_session(page)
            try:
                identity = session.send('Target.getTargetInfo')['targetInfo'].get('browserContextId')
                if not identity: raise PoolError('Missing direct context identity')
                self.context_id = identity
            finally: session.detach()
        browser_session = None
        if self.episode.background:
            probe = original()
            try: identify(probe)
            finally: probe.close()
            if video_directory: videos[probe] = (probe.video, None)
            browser_session = self.browser.new_browser_cdp_session()
        # The disposable identity probe is infrastructure, not an episode page.
        # Closing it before a first video frame must not fail episode recording.
        if video_directory: self.context.on('page', register_video)
        def new_page():
            if browser_session is not None:
                with self.context.expect_page() as event:
                    browser_session.send('Target.createTarget', {'url': 'about:blank',
                        'browserContextId': self.context_id, 'background': True})
                page = event.value
            else:
                page = original()
                if not getattr(self, 'context_id', None): identify(page)
            register_video(page)
            return page
        self.context.new_page = new_page
        original_close = self.context.close
        def close_context(*args, **kwargs):
            original_close(*args, **kwargs)
            errors = []
            for page, (video, filename) in videos.items():
                if page in saved_videos: continue
                try:
                    if filename is not None: video.save_as(filename)
                    video.delete()
                    saved_videos.add(page)
                    self.recordings.append({'kind': 'episode_page' if filename is not None else 'probe',
                                            'path': filename.name if filename is not None else None,
                                            'status': 'saved' if filename is not None else 'probe_deleted'})
                except PlaywrightError as error:
                    # The pinned public API reports this exact failure when a
                    # page closes before Playwright receives any video artifact.
                    # No transfer/network/target errors are treated as empty video.
                    if page.is_closed() and error.message in ('Page closed', 'Page did not produce any video frames'):
                        saved_videos.add(page)
                        self.recordings.append({'kind': 'episode_page' if filename is not None else 'probe',
                                                'path': filename.name if filename is not None else None,
                                                'status': 'no_video_frame'})
                    else: errors.append(error)
                except Exception as error: errors.append(error)
                if errors and page not in saved_videos:
                    self.recordings.append({'kind': 'episode_page' if filename is not None else 'probe',
                        'path': filename.name if filename is not None else None, 'status': 'failed',
                        'error': type(errors[-1]).__name__+': '+str(errors[-1])})
            if errors: raise PoolError('Video finalization failed: '+
                '; '.join(type(error).__name__+': '+str(error) for error in errors)) from errors[0]
        self.context.close = close_context
        return self.context

    def metadata(self):
        return {key: self.record[key] for key in ('owner', 'role', 'group', 'generation',
                'profile_sha256', 'lease_id')} | {'context_id': getattr(self, 'context_id', None),
                                               'released': self.closed,
                                               'recordings': getattr(self, 'recordings', [])}

    def close(self):
        if self.closed: return
        errors = []
        try:
            if self.context is not None: self.context.close()
        except Exception as error: errors.append(error)
        try:
            if self.browser is not None: self.browser.close()
        except Exception as error: errors.append(error)
        try:
            self.episode.client.request('release', {'lease_id': self.record['lease_id'],
                'owner': self.episode.owner, 'release_token': self.record['release_token']})
            self.closed = True
        except Exception as error: errors.append(error)
        if errors: raise PoolError('Owned connection cleanup failed: '+
                                   '; '.join(type(e).__name__+': '+str(e) for e in errors))


class PoolEpisode:
    def __init__(self, client, owner, *, background=False):
        if not isinstance(owner, str) or not owner or len(owner) > 128:
            raise ValueError('Pool episode needs an explicit unique owner ID')
        if type(background) is not bool: raise ValueError('background must be boolean')
        qualify_browsergym()
        self.client, self.owner, self.background = client, owner, background
        self.leases = []
        self.closed = False

    def playwright(self, role):
        if self.closed: raise PoolError('Episode browser binding is closed')
        pw = _get_global_playwright()
        def launch(**options): return _BrowserLease(self, pw, role, options)
        return SimpleNamespace(selectors=pw.selectors, chromium=SimpleNamespace(launch=launch))

    def wrap(self, env_factory):
        """Wrap an existing unused native factory without changing task constructors."""
        def factory(video=None):
            return SharedBrowserEnv.from_native(env_factory(video), pool_episode=self)
        return factory

    def metadata(self):
        return {'version': VERSION, 'manifest': self.client.descriptor['manifest'],
                'owner': self.owner, 'background': self.background,
                'ownership': 'fresh task/chat contexts and client connections; supervisor owns Chromium',
                'contexts': [lease.metadata() for lease in self.leases],
                'shared_world_state': False}

    def close(self):
        errors = []
        for lease in self.leases:
            try: lease.close()
            except Exception as error: errors.append(error)
        if errors: raise PoolError('Episode lease cleanup failed') from errors[0]
        self.closed = True

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class SharedChat(Chat):
    def __init__(self, pool_episode, *args, **kwargs):
        self.pool_episode = pool_episode
        constructor = _scoped(Chat.__init__, _get_global_playwright=lambda: pool_episode.playwright('chat'))
        try: constructor(self, *args, **kwargs)
        except BaseException:
            for lease in pool_episode.leases:
                if lease.record['role'] == 'chat': lease.close()
            raise

    def close(self):
        errors = []
        for resource in (getattr(self, 'context', None), getattr(self, 'browser', None)):
            if resource is not None:
                try: resource.close()
                except Exception as error: errors.append(error)
        if errors: raise PoolError('Chat context/connection cleanup failed: '+
            '; '.join(type(error).__name__+': '+str(error) for error in errors)) from errors[0]


class SharedBrowserEnv(BrowserEnv):
    def __init__(self, *args, pool_episode, **kwargs):
        qualify_browsergym()
        if not isinstance(pool_episode, PoolEpisode): raise TypeError('Explicit PoolEpisode required')
        self.pool_episode = pool_episode
        super().__init__(*args, **kwargs)

    @classmethod
    def from_native(cls, env, *, pool_episode):
        # Reconstruct an unused factory instance only. Do not steal live contexts,
        # silently discard custom overrides, or transfer another caller's state.
        if type(env) is not BrowserEnv or any(getattr(env, name) is not None
                                            for name in ('task', 'browser', 'context', 'chat', 'page')):
            raise PoolError('Only unused exact native BrowserEnv factories can be pooled')
        names = list(inspect.signature(BrowserEnv.__init__).parameters)[1:]
        if any(name in vars(env) for name in ('reset','close','step','_get_obs','_wait_dom_loaded')):
            raise PoolError('Custom instance lifecycle cannot be pooled')
        pooled = cls(pool_episode=pool_episode, **{name: getattr(env, name) for name in names})
        if set(vars(env)) != set(vars(pooled)) - {'pool_episode'}:
            raise PoolError('Custom unused environment state cannot be discarded')
        return pooled

    def reset(self, *args, **kwargs):
        qualify_browsergym()
        if self.pool_episode.closed: raise PoolError('Episode binding is closed')
        if self.task is not None or self.browser is not None or self.chat is not None:
            self.close()
        from .chat_ui import create_chat
        def chat(*args, **kwargs):
            return create_chat(lambda *a, **kw: SharedChat(self.pool_episode, *a, **kw), *args, **kwargs)
        reset = _scoped(BrowserEnv.reset,
            _get_global_playwright=lambda: self.pool_episode.playwright('task'), Chat=chat)
        try: return reset(self, *args, **kwargs)
        except BaseException:
            self.close()
            raise

    def close(self):
        from .browser_shutdown import close_resources
        failures = close_resources(self, lambda name, fn, **kwargs: fn())
        if failures: raise PoolError('Shared environment close failed: '+repr(failures))
        self.page = None


def supported_shared(env):
    if type(env) is not SharedBrowserEnv or getattr(env.close, '__func__', None) is not SharedBrowserEnv.close:
        return False
    qualify_browsergym()
    return isinstance(env.pool_episode, PoolEpisode)
