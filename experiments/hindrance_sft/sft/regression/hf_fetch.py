"""Tiny, dependency-free access to Hugging Face dataset rows (no auth, no full downloads).

Uses the public datasets-server API (`/size`, `/rows`, `/filter`), which serves the
dataset's current revision as parquet. We record the Hub revision (`sha`) and license
at fetch time and freeze the fetched rows locally, so later runs never depend on the Hub.
"""
import json
import time
import urllib.parse
import urllib.request

API = 'https://datasets-server.huggingface.co'


def _get(url, tries=10):
    delay = 5.0
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'sft-regression/1'}),
                                        timeout=60) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001 - retry transient HTTP/network errors
            if attempt == tries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 120)


def dataset_info(dataset):
    """Hub revision + license as recorded at fetch time."""
    info = _get('https://huggingface.co/api/datasets/' + dataset)
    lic = [t.split(':', 1)[1] for t in info.get('tags', []) if t.startswith('license:')]
    card = (info.get('cardData') or {}).get('license')
    return {'dataset': dataset, 'revision': info.get('sha'), 'gated': info.get('gated'),
            'license_tags': lic, 'card_license': card, 'last_modified': info.get('lastModified')}


def num_rows(dataset, config, split):
    size = _get(f'{API}/size?dataset={urllib.parse.quote(dataset)}')
    for s in size['size']['splits']:
        if s['config'] == config and s['split'] == split:
            return s['num_rows']
    raise KeyError((dataset, config, split))


def rows(dataset, config, split, offset, length=1):
    q = urllib.parse.urlencode({'dataset': dataset, 'config': config, 'split': split,
                                'offset': offset, 'length': length})
    out = _get(f'{API}/rows?{q}')
    return [(r['row_idx'], r['row']) for r in out['rows']]


def filtered(dataset, config, split, where, offset=0, length=1):
    q = urllib.parse.urlencode({'dataset': dataset, 'config': config, 'split': split,
                                'where': where, 'offset': offset, 'length': length})
    out = _get(f'{API}/filter?{q}')
    return out['num_rows_total'], [(r['row_idx'], r['row']) for r in out['rows']]


def rows_at(dataset, config, split, indices, page=100):
    """Fetch exactly the given row indices, one /rows page request per touched page (sequential: the API rate-limits)."""
    want = sorted(set(indices))
    got = {}
    pages = sorted({i // page for i in want})
    for p in pages:
        for idx, row in rows(dataset, config, split, p * page, page):
            got[idx] = row
        time.sleep(0.3)
    missing = [i for i in want if i not in got]
    if missing:
        raise RuntimeError(f'{dataset}: rows not returned: {missing[:5]}')
    return [(i, got[i]) for i in want]
