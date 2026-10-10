"""Formula parity and closed new envelope, with no broad historical rerun."""
import ast
from copy import deepcopy
from pathlib import Path
import pytest

from experiments.footwear_world_pilot import basket_quote as native
from experiments.footwear_world_pilot.test_basket_quote import world, bind, plan
from . import basket_quote as general

def bridged(world):
    w=deepcopy(world);w['schema_version']='accepted-catalog-commerce-world-v1'
    for p in w['products']:
        p['commerce']={'shipping_class':'regular','classification_basis':'closed_ordinary_parcel_concept_slice_v1'}
    return w

def functional_rows(result):
    return sorted((x['subtotal_minor'],x['discount_minor'],x['shipping_minor'],x['total_minor'],
                   x['arrival']['status'],str(x['arrival']),str(x['selection']),str(x['shipments']))
                  for x in result['options'])

def test_all_unmodified_formula_functions_have_equal_AST():
    def functions(module):
        return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(Path(module.__file__).read_text()).body if isinstance(n,ast.FunctionDef)}
    old,new=functions(native),functions(general)
    assert set(new)-set(old)=={'_validate_plan'} and not set(old)-set(new)
    assert all(old[k]==new[k] for k in old if k not in ('_world','quote','make_plan','validate_plan'))


def test_factored_policy_validator_retains_every_original_check_AST():
    old = next(n for n in ast.parse(Path(native.__file__).read_text()).body
               if isinstance(n, ast.FunctionDef) and n.name == 'validate_plan')
    new = next(n for n in ast.parse(Path(general.__file__).read_text()).body
               if isinstance(n, ast.FunctionDef) and n.name == '_validate_plan')
    class LocalBinding(ast.NodeTransformer):
        def visit_Call(self, node):
            if (isinstance(node.func, ast.Attribute) and node.func.attr == 'digest' and
                    isinstance(node.func.value, ast.Name) and node.func.value.id == 'model' and
                    len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == 'world'):
                return ast.parse('model.digest(world) if world_sha256 is None else world_sha256', mode='eval').body
            return self.generic_visit(node)
    # Exclude the original record preparation and the new helper docstring.
    expected = ast.Module(body=[LocalBinding().visit(n) for n in old.body[1:]], type_ignores=[])
    actual = ast.Module(body=new.body[1:], type_ignores=[])
    assert ast.dump(expected, include_attributes=False) == ast.dump(actual, include_attributes=False)


def test_make_plan_prepares_once_but_public_revalidation_recomputes(world, monkeypatch):
    new = bridged(world)
    before = deepcopy(new)
    records, digests = [], []
    prepare, digest = general._world, general.model.digest
    def prepare_once(value):
        records.append(value)
        return prepare(value)
    def hash_once(value):
        if value is new:
            digests.append(value)
        return digest(value)
    monkeypatch.setattr(general, '_world', prepare_once)
    monkeypatch.setattr(general.model, 'digest', hash_once)
    actual = general.make_plan(new)
    assert len(records) == len(digests) == 1 and new == before
    general.validate_plan(new, actual)
    assert len(records) == len(digests) == 2
    new['retailers'][0]['offers'][0]['price_minor'] += 1
    with pytest.raises(ValueError, match='Stale basket'):
        general.validate_plan(new, actual)

@pytest.mark.parametrize('quantity',[1,2])
def test_exact_public_options_match_native_formulas(world,quantity):
    new=bridged(world);old_plan=plan(world);new_plan=general.make_plan(new)
    r=world['retailers'][0];ids=[x['offer_id'] for x in r['offers'][:2]]
    lines=[dict(line_id=o,offer_id=o,quantity=quantity) for o in ids]
    old=native.quote(world,r['retailer_id'],lines,plan=old_plan)
    actual=general.quote(new,r['retailer_id'],lines,plan=new_plan)
    assert functional_rows(actual)==functional_rows(old)
    assert actual['schema_version']!=old['schema_version']

def test_foreign_schema_and_unadopted_classification_rejected(world):
    with pytest.raises(ValueError):general.make_plan(world)
    new=bridged(world);new['products'][0]['commerce']['shipping_class']='bulky'
    with pytest.raises(ValueError):general.make_plan(new)

def test_quote_never_changes_manufacturer_facts_or_prices(world):
    new=bridged(world)
    for p in new['products']:p['public']['facts'].pop('shipping_class',None)
    original=deepcopy(new);p=general.make_plan(new);r=new['retailers'][0];o=r['offers'][0]
    general.quote(new,r['retailer_id'],[dict(line_id=o['offer_id'],offer_id=o['offer_id'],quantity=1)],plan=p)
    assert new==original

def test_accounts_remain_explicitly_unsupported(world):
    new=bridged(world);p=general.make_plan(new);r=new['retailers'][0];o=r['offers'][0]
    with pytest.raises(ValueError,match='account/coupon'):
        general.quote(new,r['retailer_id'],[dict(line_id=o['offer_id'],offer_id=o['offer_id'],quantity=1)],plan=p,coupon_code='SAVE')
