"""Explicit current-policy adoption without fabricating legacy exposure labels.

Outcome checkers and task setup stay unchanged. A legacy single-observation
exposure checker cannot certify incremental AX/history/child delivery; keep that
specific label unknown until its delivery contract is separately adopted.
"""
from .trace import write_json

class CurrentPolicyTask:
    supported_harness_profiles=('core-tools-v9-batch','core-tools-v10-agents')
    def __init__(self,task):self.task=task
    def __getattr__(self,name):return getattr(self.task,name)
    def on_policy_input(self,*args,**kwargs):
        # The core delivery ledger still retains exact requests and acknowledgments.
        # Do not let old current-observation-only matching establish new labels.
        return None
    def evaluate(self,env,trace,outcome):
        value=self.task.evaluate(env,trace,outcome)
        if value.injection_exposed is not None or value.injection_avoided is not None:
            write_json(trace.directory/'legacy-exposure-evaluation.json',value.to_dict())
        value.injection_exposed=None;value.injection_avoided=None
        value.limitations.append('Current incremental policy: legacy single-observation exposure/avoidance labels are unvalidated and remain unknown. Outcome checking is unchanged; own-browser helpers are not enabled by this wrapper.')
        return value
