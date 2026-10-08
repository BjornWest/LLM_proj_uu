"""Task-bound public site-directory callback, bounded delivery and exact traces."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlsplit

KINDS = ('retailer', 'comparison', 'review')
VERSION = 'public-site-discovery-v1'


def validate_response(value, arguments):
    if not isinstance(value, dict) or set(value) != {'total','offset','limit','next_offset','sites'}:
        raise ValueError('Directory must return only total/offset/limit/next_offset/sites.')
    total, offset, limit = value['total'], value['offset'], value['limit']
    if any(type(v) is not int for v in (total,offset,limit)) or total < 0:
        raise ValueError('Invalid directory pagination types.')
    if offset != arguments['offset'] or limit != arguments['limit']:
        raise ValueError('Directory response pagination does not match request.')
    sites = value['sites']
    if not isinstance(sites, list) or len(sites) > min(limit, max(0,total-offset)):
        raise ValueError('Directory returned invalid site count.')
    expected_next = offset + len(sites) if offset + len(sites) < total else None
    if (value['next_offset'] is not None and type(value['next_offset']) is not int) or value['next_offset'] != expected_next:
        raise ValueError('Invalid next_offset.')
    if expected_next is not None and not sites:
        raise ValueError('Directory pagination made no progress.')
    ids = set()
    for site in sites:
        if not isinstance(site,dict) or set(site) != {'site_id','kind','name','url','description'}:
            raise ValueError('Directory entries must contain only public site_id/kind/name/url/description.')
        for key, maximum in [('site_id',128),('kind',32),('name',512),('url',2048),('description',8192)]:
            text = site[key]
            if not isinstance(text,str) or len(text) > maximum or '\0' in text or (key != 'description' and not text.strip()):
                raise ValueError('Invalid public site entry field.')
        if site['kind'] not in KINDS or arguments['kind'] is not None and site['kind'] != arguments['kind']:
            raise ValueError('Directory kind does not match requested scope.')
        if site['site_id'] in ids: raise ValueError('Duplicate site ID in directory page.')
        ids.add(site['site_id'])
        url = urlsplit(site['url'])
        if (url.scheme not in ('http','https') or not url.hostname or url.username is not None
                or url.password is not None or any(c.isspace() for c in site['url']) or '\\' in site['url']):
            raise ValueError('Directory URL must be an absolute credential-free HTTP(S) URL.')
    # Bound the exact retained response as well as the model-facing projection.
    if len(json.dumps(value,ensure_ascii=False).encode('utf-8')) > 256*1024:
        raise ValueError('Directory response exceeds storage bound.')


class SiteDiscoverySession:
    def __init__(self, callback, directory, tokenizer, *, audit_id=None, feedback_tokens=1500):
        self.callback, self.directory, self.tokenizer = callback, Path(directory), tokenizer
        self.audit_id, self.feedback_tokens = audit_id, feedback_tokens

    def feedback(self, response):
        result = {'tool':'discover_sites','execution':'completed',**deepcopy(response)}
        for site in result['sites']:
            for field,budget in [('description',60),('name',32)]:
                ids = self.tokenizer.encode(site[field],add_special_tokens=False).ids
                if len(ids) > budget:
                    site[field] = self.tokenizer.decode(ids[:budget],skip_special_tokens=False)
                    site[field+'_partial'] = True
        def count():
            return len(self.tokenizer.encode(json.dumps(result,ensure_ascii=False),add_special_tokens=False).ids)
        while result['sites'] and count() > self.feedback_tokens:
            result['sites'].pop()
            result['next_offset'] = result['offset'] + len(result['sites'])
            result['page_shortened'] = True
        if not result['sites'] and response['sites']:
            return {'tool':'discover_sites','execution':'failed',
                'error':'A directory entry exceeds the feedback token budget; public provider must shorten its fields.'}
        # Empty pages still carry pagination fields: enforce the bound after
        # all projection paths, including an offset beyond the final page.
        if count() > self.feedback_tokens:
            return {'tool':'discover_sites','execution':'failed',
                'error':'Directory pagination exceeds the feedback token budget; use a smaller offset.'}
        return result

    def execute(self, arguments, index):
        args = {'query':'','kind':None,'limit':5,'offset':0,**arguments}
        artifact = f'site-discovery-{index:03d}.json'
        # Reserve the artifact before invoking the callback: never replay a call
        # merely because an existing execution index was accidentally reused.
        with (self.directory/artifact).open('x',encoding='utf-8') as output:
            raw = None; error = None
            try:
                if (set(args) != {'query','kind','limit','offset'} or not isinstance(args['query'],str)
                        or len(args['query']) > 256 or args['kind'] not in (*KINDS,None)
                        or type(args['limit']) is not int or not 1 <= args['limit'] <= 20
                        or type(args['offset']) is not int or args['offset'] < 0):
                    raise ValueError('Invalid discovery arguments.')
                raw = self.callback(**deepcopy(args))
                validate_response(raw,args)
                result = self.feedback(raw)
            except Exception as exc:
                # Public provider failures do not expose traceback/private state
                # or a partially validated response to the policy.
                error = {'type':type(exc).__name__,'message':str(exc)}
                result = {'tool':'discover_sites','execution':'failed',
                    'error':'Site directory unavailable or invalid; no browser action was taken.'}
            record = {'version':VERSION,'audit_id':self.audit_id,'arguments':args,
                      'response':raw if error is None else None,'error':error,'feedback':result,
                      'scope':'Public site directory; not task grading, ranking or transaction evidence.'}
            json.dump(record,output,ensure_ascii=False,indent=2)
        return result, artifact
