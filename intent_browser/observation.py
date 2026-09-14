"""Version-pinned, observation-only BrowserGym refresh for paced decisions."""
from importlib.metadata import version


def refresh_observation(env):
    # BrowserGym 0.14.3 has no public observation-only refresh method. _get_obs
    # performs the same DOM/AX/screenshot extraction used by reset/step, without
    # taking an action, validating the task, or changing its step counter.
    installed = version('browsergym-core')
    if installed != '0.14.3':
        raise RuntimeError(f'Observation refresh requires reviewed BrowserGym 0.14.3, got {installed}')
    return env.unwrapped._get_obs()
