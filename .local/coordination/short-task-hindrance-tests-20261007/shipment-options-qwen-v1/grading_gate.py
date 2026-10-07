"""Required automatic grading for finite evaluation dispatches."""
def require_grading(*, runner=None, grader=None, projection=None, artifact=None,
                    allow_ungraded=False, reason=None):
    if type(allow_ungraded) is not bool:
        raise ValueError('allow_ungraded must be an explicit boolean')
    if allow_ungraded:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('Ungraded escape requires an explicit recorded reason')
        return {'automatic': False, 'allow_ungraded': True, 'reason': reason}
    if not all(callable(fn) for fn in (runner, grader, projection)):
        raise ValueError('Episode launch blocked: automatic runner/grader/viewer projection required')
    if not isinstance(artifact, str) or not artifact or '/' in artifact or '\\' in artifact:
        raise ValueError('Episode launch blocked: native grading artifact required')
    return {'automatic': True, 'allow_ungraded': False, 'artifact': artifact,
            'runner': runner.__module__+'.'+runner.__qualname__,
            'grader': grader.__module__+'.'+grader.__qualname__,
            'projection': projection.__module__+'.'+projection.__qualname__}
