"""Capability-gated current capture defaults; explicit configurations stay explicit."""
from .observation_pipeline import ObservationPipelineConfig

RUNTIME_DEFAULTS_VERSION='browser-runtime-defaults-v2'


def select_observation_pipeline(value, *, profile, backend, task, trace_screenshots):
    """Return (config, provenance) before browser/model work.

    'auto' adopts only the reviewed live-web custody/adapter/backend closure.
    'native' retains full native observations. None and concrete configs preserve
    explicit caller intent, including frozen experiment configurations.
    """
    if trace_screenshots is not None and type(trace_screenshots) is not bool:
        raise ValueError('trace_screenshots must be boolean or None')
    record={'version':RUNTIME_DEFAULTS_VERSION,'requested':value if isinstance(value,str) else 'explicit',
            'selected':None,'reason':None}
    if not isinstance(value,str):
        record.update(selected='explicit_pipeline' if value is not None else 'native',reason='caller_configuration')
        return value,record
    if value not in ('auto','native'):raise ValueError('observation_pipeline must be auto, native, None or ObservationPipelineConfig')
    tools=getattr(profile,'tools',None)
    human=bool(getattr(tools,'human_handover_tools',False))
    full=ObservationPipelineConfig((),full_capture_only=True,
            trace_screenshots=True if trace_screenshots is None else trace_screenshots) if human else None
    record.update(selected='native',reason='explicit_native' if value=='native' else 'requires_live_web_tab_tracking')
    if value=='native':return full,record
    if not human:return _agent_custody(profile,backend,task,trace_screenshots,record)
    checks=(
        (bool(getattr(tools,'open_internet',False)) and bool(getattr(tools,'stable_frame_capture',False)),
            'requires_stable_live_web_frames'),
        (getattr(profile,'agent_limits',None) is None and bool(getattr(getattr(profile,'ax_config',None),'incremental',False)),
            'requires_incremental_ax_without_helpers'),
        (type(backend).__dict__.get('supports_background_completion') is True and
            not getattr(backend,'requires_browser_thread',False),'backend_not_background_certified'),
        (task is None or (getattr(task,'supports_observation_pipeline',False) in (True,'native_full_only') and
            getattr(task,'supports_dynamic_preview',False) is True and
            getattr(task,'supports_targeted_observations',False) is True),'adapter_not_fast_capture_certified'),
    )
    for accepted,reason in checks:
        if not accepted:
            record['reason']=reason;return full,record
    screenshots=False if trace_screenshots is None else trace_screenshots
    selected=ObservationPipelineConfig((),full_capture_only=True,dynamic_preview=True,
        shallow_depth=2,preview_node_limit=64,preview_bids=True,
        trace_screenshots=screenshots,targeted_actions=not screenshots)
    record.update(selected='preview_full_post_action' if screenshots else 'preview_targeted',
        reason='explicit_screenshots_require_full_post_action' if screenshots else 'reviewed_capabilities')
    return selected,record


def _agent_custody(profile,backend,task,trace_screenshots,record):
    """Generated-world fast capture without any policy-visible handover tools.

    Requires an adapter that explicitly declares agent-custody fast capture (its
    grader must not consume complete transition observations), a certified
    background-completion backend, incremental AX and no helper runtime.
    """
    tools=getattr(profile,'tools',None)
    if task is None or getattr(task,'supports_agent_fast_capture',False) is not True:
        return None,record  # Neither reviewed path applies: requires_live_web_tab_tracking.
    checks=(
        (getattr(task,'supports_observation_pipeline',False) in (True,'native_full_only') and
            getattr(task,'supports_dynamic_preview',False) is True and
            getattr(task,'supports_targeted_observations',False) is True,'adapter_not_agent_fast_capture_certified'),
        (not getattr(tools,'open_internet',False),'open_internet_requires_live_web_tab_tracking'),
        (getattr(profile,'agent_limits',None) is None and bool(getattr(getattr(profile,'ax_config',None),'incremental',False))
            and hasattr(tools,'parse_completion'),'requires_incremental_ax_without_helpers'),
        (type(backend).__dict__.get('supports_background_completion') is True and
            not getattr(backend,'requires_browser_thread',False),'backend_not_background_certified'),
    )
    for accepted,reason in checks:
        if not accepted:
            record['reason']=reason;return None,record
    screenshots=False if trace_screenshots is None else trace_screenshots
    selected=ObservationPipelineConfig((),full_capture_only=True,dynamic_preview=True,
        preview_bids=True,trace_screenshots=screenshots,targeted_actions=not screenshots,
        agent_custody=True,decision_capture='budgeted_overview')
    record.update(selected='agent_budgeted_full_post_action' if screenshots else 'agent_budgeted_targeted',
        reason='explicit_screenshots_require_full_post_action' if screenshots else 'reviewed_capabilities')
    return selected,record
