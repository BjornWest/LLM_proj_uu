"""Declared producer capabilities, exact statuses and SKU-specific prose."""
from copy import deepcopy
import pytest
from environments.product_world import footwear_context_pilot as footwear
from environments.product_world.product_package import PackageError
from . import package_export

@pytest.fixture(scope='module')
def tablet():
    brand=footwear.sample_brand(1,0,footwear.load_spec())
    return package_export.sample(1,'tablets.everyday_media_tablets',brand,'export-tablet',review_count=0)

def test_unsupported_concept_does_not_silently_use_bare_compiler():
    with pytest.raises(PackageError):package_export.source_gate('office_chairs.office_task_chairs')

def test_all_scoped_prose_has_actual_manufactured_subject(tablet):
    p=tablet['public'];ids={s['sku_id'] for s in p['skus']}
    assert any(d['subject_type']=='sku' for d in tablet['descriptions'])
    for d in tablet['descriptions']:
        assert d['subject_id'] in ids if d['subject_type']=='sku' else d['subject_id']==p['product_id']
        assert d['mapping_status']=='unmapped'

def test_status_projection_covers_each_manufactured_SKU(tablet):
    assert set(tablet['sku_status'])=={s['sku_id'] for s in tablet['public']['skus']}
    assert tablet['catalog_status']['product.facts.battery_charge_mah']=='unknown'
    assert all(s['sku.actual_mass_g']=='unknown' for s in tablet['sku_status'].values())
    assert tablet['public']['facts']==tablet['private']['sample']['entities']['product']['facts']

def test_zero_reviews_do_not_invent_stars_or_experiences(tablet):
    assert tablet['reviews']==[]
    assert tablet['rating_summary']['rating_count']==0

def test_mandatory_completed_factory_is_source_gated():
    gate=package_export.source_gate('tops.t_shirts')
    assert gate['capability']=='source_bound_completed_factory'
    assert package_export.COMPLETED['tops.t_shirts'] in gate['source_hashes']
