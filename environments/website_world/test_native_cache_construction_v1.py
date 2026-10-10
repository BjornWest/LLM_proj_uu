"""Prepared isolated construction controls; no tasks/worlds/browser/provider.

Run only in a reviewed complete Git source/data closure. Each case uses a new
child interpreter. These are construction controls, never effect acceptance.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
CASE = r'''
import gc, json, sys
from hashlib import sha256
from pathlib import Path
from environments.website_world import native_cache_construction_v1 as helper
root=Path.cwd().resolve()
manifest=root/'.evaluation-release.json'
document=json.loads(manifest.read_bytes())
sources={str(root/name):expected for name,expected in document['source_sha256'].items()}
recipe={'path':str(manifest),'sha256':sha256(manifest.read_bytes()).hexdigest()}
name=sys.argv[1]
def create(): return helper.bootstrap(root=root,sources=sources,recipe=recipe)
def reject(call):
    try:call()
    except helper.ConstructionError:return
    raise AssertionError('Expected a fail-closed construction rejection')
if name=='issuer-entry-latch':
    # Synthetic private-state control: failed concurrent entry invalidates the
    # issuer even before a token exists; a later call must not import natives.
    locks=[cell.cell_contents for cell in helper.bootstrap.__closure__
           if type(cell.cell_contents).__module__=='_thread']
    assert len(locks)==1
    lock=locks[0]
    lock.acquire()
    try:reject(create)
    finally:lock.release()
    reject(create)
    assert not any(key.startswith('experiments.') for key in sys.modules)
elif name=='copied-issuer':
    alternate,_,_=helper._issuer()
    reject(lambda:alternate(root=root,sources=sources,recipe=recipe))
    assert not any(key.startswith('experiments.') for key in sys.modules)
elif name=='foreign-constructor':
    import _functools
    _functools._lru_cache_wrapper=lambda *args: None
    reject(create)
elif name=='preimport':
    import experiments.footwear_world_pilot.model
    reject(create)
elif name=='source-pin':
    sources[str(root/'environments/product_world/geography.py')]='0'*64
    reject(create)
elif name=='graph-pin':
    sources[str(root/'environments/product_world/data/europe_locations.json')]='0'*64
    reject(create)
elif name=='recipe-pin':
    recipe['sha256']='0'*64
    reject(create)
else:
    token=create()
    import importlib, _functools
    roles=[(importlib.import_module(module),symbol,limit) for module,symbol,limit in helper.ROLES]
    geo=importlib.import_module('environments.product_world.geography')
    model=importlib.import_module('experiments.footwear_world_pilot.model')
    shared=importlib.import_module('experiments.accepted_catalog_commerce.shared_semantics')
    if name=='no-use-interval':
        # The actual before_native_use phase completed inside create(), before
        # any caller could invoke and clear a cache to erase counters.
        reject(lambda:helper.checkpoint(token,phase='before_native_use'))
    elif name=='phase-order':
        reject(lambda:helper.checkpoint(token,phase='after_policy'))
    elif name=='fake-issuance':
        reject(lambda:helper.admits({'roles':list(helper.ROLES),'approved':True},model._route))
    elif name=='late-issuance':
        reject(create)
        reject(lambda:helper.admits(token,model._route))
        reject(lambda:helper.checkpoint(token,phase='before_policy'))
    elif name=='post-bootstrap-use-clear':
        geo.network();geo.network.cache_clear()
        helper.checkpoint(token,phase='before_policy')
        helper.checkpoint(token,phase='after_policy')
        helper.checkpoint(token,phase='sealed')
    else:
        helper.checkpoint(token,phase='before_policy')
        if name.startswith('warm-'):
            for module,symbol,limit in roles:
                assert helper.admits(token,getattr(module,symbol))
                assert getattr(module,symbol).cache_info().maxsize==limit
            if name=='warm-footwear':
                origin={'location_id':'construction-origin','city_id':'uppsala',
                    'latitude':59.86,'longitude':17.64,'local_east_km':0.0,'local_north_km':0.0}
                destination={**origin,'location_id':'construction-destination',
                    'local_east_km':0.4,'local_north_km':0.2}
                values=(json.dumps(origin,sort_keys=True),json.dumps(destination,sort_keys=True),'freight')
                expected=model._route.__wrapped__(*values)
                first=model._route(*values);second=model._route(*values)
                assert first==expected and second is first and type(first) is dict
                network=geo.network();assert geo.network() is network and type(network) is dict
                for freight in (False,True):
                    for pair in [('uppsala','uppsala'),('uppsala','stockholm'),('reykjavik','uppsala')]:
                        expected=geo.city_path.__wrapped__(*pair,freight)
                        actual=geo.city_path(*pair,freight)
                        assert actual==expected and type(actual) is type(expected)
                        assert geo.city_path(*pair,freight) is actual
                        if pair==('reykjavik','uppsala') and freight is False:
                            assert actual is None
                assert geo.city_path('uppsala','stockholm')==geo.city_path('uppsala','stockholm',False)
            else:
                from environments.product_world.shared_state import FrozenDict
                expected=shared.registration.__wrapped__()
                first=shared.registration();second=shared.registration()
                assert first==expected and second is first and type(first) is FrozenDict
            helper.checkpoint(token,phase='after_policy')
            helper.checkpoint(token,phase='sealed')
            reject(lambda:helper.checkpoint(token,phase='before_policy'))
        else:
            if name=='donor-slot': model._route=model.travel
            elif name=='wrong-maxsize':
                old=model._route
                replacement=_functools._lru_cache_wrapper(old.__wrapped__,0,False,old.cache_info().__class__)
                replacement.__dict__.update(old.__dict__)
                model._route=replacement
            elif name=='wrong-typed':
                old=model._route
                replacement=_functools._lru_cache_wrapper(old.__wrapped__,32768,True,old.cache_info().__class__)
                replacement.__dict__.update(old.__dict__)
                model._route=replacement
            elif name=='wrapped-spoof': model._route.__wrapped__=model.travel
            elif name=='parameters-spoof': model._route.cache_parameters=lambda:{'maxsize':32768,'typed':False}
            elif name=='parameter-default': model._route.cache_parameters.__defaults__=(0,)
            elif name=='native-default': geo.city_path.__wrapped__.__defaults__=(True,)
            elif name=='route-donor': model._route.__wrapped__.__globals__['route']=geo.haversine
            elif name=='json-donor': model._route.__wrapped__.__globals__['json']=object()
            elif name=='data-path': shared.REGISTRATION_PATH=root/'unknown.json'
            elif name=='helper-identity': helper._snapshot=lambda *a: None
            elif name=='capacity-metadata':
                model._route.cache_info=lambda:None
            elif name=='drift-restore':
                original=model._route.cache_parameters
                model._route.cache_parameters=lambda:{'maxsize':32768,'typed':False}
                reject(lambda:helper.checkpoint(token,phase='after_policy'))
                model._route.cache_parameters=original
            else:raise AssertionError('Unknown case '+name)
            reject(lambda:helper.checkpoint(token,phase='after_policy'))
            reject(lambda:helper.admits(token,model._route))
            reject(lambda:helper.checkpoint(token,phase='sealed'))
print(json.dumps({'case':name,'construction_control':'pass','providers':0,'world_draws':0,'browsers':0}))
'''


class FreshConstructorTests(unittest.TestCase):
    def case(self, name):
        self.assertTrue((ROOT/'.evaluation-release.json').is_file(),
                        'Use a reviewed complete source/data closure, not the dev tree')
        result = subprocess.run([sys.executable, '-B', '-c', CASE, name], cwd=ROOT,
            env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1'),
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
        self.assertEqual(json.loads(result.stdout)['construction_control'], 'pass')


def _install_case(name):
    def case(self): self.case(name)
    case.__name__ = 'test_'+name.replace('-', '_')
    setattr(FreshConstructorTests, case.__name__, case)


for _case in (
        'warm-footwear', 'warm-catalog', 'foreign-constructor', 'preimport',
        'source-pin', 'graph-pin', 'recipe-pin', 'no-use-interval', 'phase-order',
        'fake-issuance', 'late-issuance', 'donor-slot', 'wrong-maxsize', 'wrong-typed',
        'wrapped-spoof', 'parameters-spoof', 'parameter-default', 'native-default',
        'route-donor', 'json-donor', 'data-path', 'helper-identity', 'capacity-metadata',
        'post-bootstrap-use-clear', 'drift-restore', 'issuer-entry-latch', 'copied-issuer'):
    _install_case(_case)
