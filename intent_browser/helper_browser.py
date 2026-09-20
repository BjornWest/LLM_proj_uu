"""Separate browser for trusted open-ended or server-authoritative local tasks.

Do not use this for browser-local grader journals: it deliberately does not rerun
benchmark setup, install hidden patches, or copy privileged task state.
"""
def openended_helper_factory(parent, goal):
    import gymnasium as gym
    from .actions import make_action_set
    base=parent.unwrapped
    page=base.page
    start_url=page.url
    storage=page.context.storage_state()
    # This helper is for ordinary local pages, not proxy/lease-based benchmarks.
    # Callers for those tasks must supply their own reviewed setup instead.
    def create(video):
        return gym.make('browsergym/openended',task_kwargs={'start_url':start_url,'goal':goal},
            headless=True,wait_for_user_message=False,action_mapping=make_action_set().to_python_code,
            viewport=page.viewport_size or {'width':1280,'height':720},
            pw_context_kwargs={'storage_state':storage},record_video_dir=video)
    return create
