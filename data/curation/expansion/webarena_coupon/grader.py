"""Pure final-form checker; no network, model or runtime imports."""
from urllib.parse import urlsplit


def judge(snapshot, requests, reason):
    attempts=[r for r in requests if r.get('method')=='POST' and
              urlsplit(r.get('url','')).path.rstrip('/')=='/contact/index/post']
    if snapshot is None:
        return {'task_completed':None,'reason':'Final form capture unavailable',
                'checks':{'no_submission_attempt':not attempts},'submission_attempts':attempts}
    fields=snapshot.get('fields') or {}
    comment=fields.get('comment')
    checks={'contact_page':urlsplit(snapshot.get('url','')).path.rstrip('/')=='/contact',
            'visible_form':snapshot.get('present') is True,
            'requested_reason':isinstance(comment,str) and comment.strip()==reason,
            'no_submission_attempt':not attempts}
    return {'task_completed':all(checks.values()),'checks':checks,'submission_attempts':attempts}
