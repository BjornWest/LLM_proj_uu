"""Verify frozen input bytes before creating an isolated connected runtime."""
from pathlib import Path
import hashlib,json


def load_pin(directory):
    root=Path(directory);pins=json.loads((root/'pins.json').read_text())
    for name,h in pins['file_sha256'].items():
        p=root/name
        if Path(name).name!=name:raise ValueError('Unexpected pin path')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('Pinned input changed: '+name)
    # Rendering-only and authoring additions can evolve separately; geographic and
    # identity semantics used at runtime must still match the reviewed fixture.
    scenario=json.loads((root/'scenario.private.json').read_text())
    modules=['stores','locations','geography','travel','generator','validation','config','areas']
    if 'branch_shipping' in scenario.get('locations',{}).get('public',{}):modules.append('branch_shipping')
    if scenario.get('accounts') is not None:modules.append('accounts')
    for module in modules:
        path='environments/product_world/'+module+'.py'
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=pins['source_sha256'].get(path):raise ValueError('Pinned semantic source changed: '+path)
    return scenario,pins
