"""Explicit frozen-core import for offline curation rehearsals, inherited by children.

Set CURATION_FROZEN_RUNTIME to a directory containing a pinned manifest and copied
intent_browser package. Call activate before any intent_browser import. Task/site
files remain separately fingerprinted by each wrapper. Does not authorize paid runs.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys


def activate():
    value=os.environ.get('CURATION_FROZEN_RUNTIME')
    if not value:return None
    root=Path(value).resolve();manifest=json.loads((root/'manifest.json').read_text())
    pins=manifest['source_sha256']
    assert set(pins)=={'intent_browser/'+p.name for p in (root/'intent_browser').glob('*.py')}
    for name,pin in pins.items():
        assert name.startswith('intent_browser/') and Path(name).name==name.split('/')[1]
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==pin, name
    if 'intent_browser' in sys.modules:
        assert Path(sys.modules['intent_browser'].__file__).resolve().parent==root/'intent_browser','Wrong package already loaded'
    else:
        sys.path.insert(0,str(root))
        try:importlib.import_module('intent_browser')
        finally:sys.path.pop(0)
    assert Path(sys.modules['intent_browser'].__file__).resolve().parent==root/'intent_browser'
    return root


def fingerprints(root, repository):
    """Actual copied source paths, never relabel them as current checkout files."""
    paths=list((root/'intent_browser').glob('*.py'))+[root/'manifest.json']
    return {str(p.relative_to(repository)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
