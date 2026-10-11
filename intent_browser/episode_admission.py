"""Opt-in runner parking boundary; scheduling and cancellation wakeups are caller-owned."""
from dataclasses import dataclass
from pathlib import Path
import time

from .trace import write_json

VERSION = 'environment-admission-v1'


@dataclass(frozen=True)
class EpisodeReady:
    """Identity-only notification, safe to share with a scheduler thread."""
    episode_id: str
    directory: Path
    ready_monotonic: float


class EpisodeAdmissionCancelled(Exception):
    """Cancel a parked episode without dispatching or reporting a task verdict."""
    def __init__(self, reason='Cancelled before episode activation'):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('Cancellation requires a nonempty reason')
        super().__init__(reason)


def await_activation(callback, trace, refresh):
    """Wait on the browser owner thread, then capture real current state once."""
    started = time.monotonic()
    ready = EpisodeReady(trace.episode_id, trace.directory, started)
    trace.event('environment_ready_for_admission', version=VERSION)
    try:
        if callback(ready) is not None:
            raise TypeError('environment_admission must return None on admission')
        admitted = time.monotonic()
        trace.event('episode_admitted', version=VERSION, wait_seconds=admitted-started,
                    admission_monotonic=admitted)
        observation = refresh()
        trace.event('activation_observation_refreshed', version=VERSION,
                    capture_seconds=time.monotonic()-admitted)
        trace.metadata['environment_admission'] = {
            'version': VERSION, 'status': 'activated', 'wait_seconds': admitted-started,
            'admission_monotonic': admitted, 'reset_repeated': False}
        write_json(trace.directory/'metadata.json', trace.metadata)
        return observation
    except (Exception, KeyboardInterrupt) as exc:
        trace.event('episode_admission_cancelled' if isinstance(exc, EpisodeAdmissionCancelled)
                    else 'episode_admission_failed', version=VERSION,
                    error=f'{type(exc).__name__}: {exc}', elapsed_seconds=time.monotonic()-started)
        raise
