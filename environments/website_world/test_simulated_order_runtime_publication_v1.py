"""Actual retailer publication prefix controls without starting a Runtime/server."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest


def publication_prefix(source):
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Runtime')
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    loop = next(n for n in ast.walk(init) if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
                and [v.id for v in n.target.elts] == ['sid', 'retailer'])
    # Composition assignment can precede catalog construction. Retain every
    # statement through all three bindings, including the actual local public
    # assignment: truncating that assignment changes UnboundLocalError to
    # NameError and can bypass catalog construction in the corrected source.
    positions = {}
    for index, node in enumerate(loop.body):
        for assignment in (v for v in ast.walk(node) if isinstance(v, ast.Assign)):
            for target in assignment.targets:
                if ast.unparse(target) == 'self.compositions[sid]': positions['composition'] = index
                if ast.unparse(target) == "public['simulatedOrders']": positions['capability'] = index
                if (isinstance(target, ast.Name) and target.id == 'public' and
                        isinstance(assignment.value, ast.Call) and
                        ast.unparse(assignment.value.func) == 'self.adapter.catalog'):
                    positions['catalog'] = index
    assert set(positions) == {'composition', 'capability', 'catalog'}
    loop.body = loop.body[:max(positions.values()) + 1]
    fn = ast.FunctionDef(name='exercise', args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='self')],
        kwonlyargs=[], kw_defaults=[], defaults=[]), body=[loop], decorator_list=[])
    namespace = {'site_plan': lambda *a, **kw: {'config': {}}, 'option_order_catalogs': {}}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<publication-prefix>', 'exec'), namespace)
    return namespace['exercise']


class PublicationTests(unittest.TestCase):
    def source(self):
        return Path(os.environ.get('WEBSITE_RUNTIME_SOURCE_CANDIDATE',
            Path(__file__).with_name('runtime.py'))).read_text()

    def test_every_fresh_retailer_catalog_exists_before_capability_assignment(self):
        catalogs = []
        def catalog(sid, config, **kwargs):
            value = {'siteId': sid}; catalogs.append(value); return value
        runtime = SimpleNamespace(adapter=SimpleNamespace(retailers={'one': {}, 'two': {}},
            catalog=catalog, delivery_orders={}), presentation=None, coupons=None, baskets=None,
            page_variations={}, compositions={}, world={})
        publication_prefix(self.source())(runtime)
        self.assertEqual(catalogs, [{'siteId': 'one', 'simulatedOrders': True},
                                    {'siteId': 'two', 'simulatedOrders': True}])
        self.assertEqual(set(runtime.compositions), {'one', 'two'})

    def test_empty_retailer_population_is_not_fabricated(self):
        runtime = SimpleNamespace(adapter=SimpleNamespace(retailers={}), compositions={})
        publication_prefix(self.source())(runtime)
        self.assertEqual(runtime.compositions, {})


if __name__ == '__main__': unittest.main()
