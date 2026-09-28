"""Opt-in wrappers around native OpenEnv sessions; no GRPO or generation changes."""
import threading
import time

from .outcomes import require
from .policy_sessions import current_episode, fail_current_episode


def unavailable(status):
    return dict(status=status, goal_completed=None, constraints_satisfied=None,
                unauthorized_effect=None, reward=None)


class MonitoredSessionFactory:
    def __init__(self, delegate, monitor, *, group_size, extractor):
        self.delegate, self.monitor, self.group_size, self.extractor = delegate, monitor, group_size, extractor

    def create(self, task, seed=None, episode_id=None):
        reservation = current_episode()
        require(reservation is not None and reservation["episode_id"] == episode_id,
                "Monitored sessions require the existing policy reservation context")
        draw = self.monitor.begin(native_group_id=reservation["group_id"], episode_id=episode_id,
                                  policy_version=reservation["policy_version"], group_size=self.group_size)
        try:
            session = self.delegate.create(draw["task_id"], seed=draw["seed"], episode_id=episode_id)
        except BaseException:
            self.monitor.finish(episode_id, unavailable("infra_error"))
            raise
        return MonitoredSession(session, self.monitor, episode_id, self.extractor)


class MonitoredSession:
    def __init__(self, delegate, monitor, episode_id, extractor):
        self.delegate, self.monitor, self.episode_id, self.extractor = delegate, monitor, episode_id, extractor
        self.outcome, self.tokens, self.steps = None, 0, None
        self.started, self.closed, self.lock = time.perf_counter(), False, threading.RLock()
        self.running, self.recorded, self.closing = False, False, False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def verify(self, transcript):
        try:
            result = self.delegate.verify(transcript)
            self.outcome = self.extractor(self.delegate, result)
            self.steps = result.metrics.get("step_count")
            return result  # TRL receives exactly the upstream verifier result.
        except BaseException:
            self.outcome = unavailable("infra_error")
            raise

    def close(self):
        with self.lock:
            if self.recorded:
                return
            try:
                if not self.closed:
                    self.closing = True
                    self.delegate.close()
            except BaseException:
                self.outcome = unavailable("infra_error")
                raise
            finally:
                self.closed = True
                # The stop watcher may close a session while its inference drains.
                # Native _run_session finally calls close again after the adapter exits.
                if not self.running:
                    try:
                        self.monitor.finish(self.episode_id, self.outcome or unavailable("cancelled"),
                            generated_tokens=self.tokens, steps=self.steps, duration_s=time.perf_counter()-self.started)
                    except Exception:
                        # Native OpenEnv logs and swallows close exceptions. Make a
                        # lost local record visible to the existing reservation guard.
                        fail_current_episode("Local outcome persistence failed; inspect ledger before resuming")
                        raise
                    self.recorded = True


class MonitoredHarnessAdapter:
    def __init__(self, delegate):
        self.delegate = delegate

    def run_white_box(self, model_step, session, limits):
        session.running = True
        def counted(messages, tools, sampling):
            result = model_step(messages, tools, sampling)
            session.tokens += len(result.completion_ids)
            return result
        try:
            return self.delegate.run_white_box(counted, session, limits)
        except BaseException:
            session.outcome = unavailable("cancelled" if session.closing else "infra_error")
            raise
        finally:
            session.running = False


def plumbing_outcome(session, verify):
    """Pinned OpenEnv 0.4.2 StepEnvSessionAdapter + our HTML test fixture only.

    Deliberately not the production/native P07 extractor. The native session's
    last StepResult is the same explicit metadata used by the fixture observer.
    """
    from .browser_metrics import fixture_verification
    from .outcomes import safe
    if not verify.done:
        return unavailable("cancelled")
    result = dict(status="completed", **fixture_verification(session._last_result))
    result["reward"] = verify.env_reward if safe(result) is not None else None
    return result
