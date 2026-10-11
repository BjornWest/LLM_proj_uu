from copy import deepcopy
import pytest

from .request_labels import variant_name


def test_declared_choices_omit_facts_measurements_prices_and_internal_ids():
    package = {'public': {'name': 'Orla T-shirt', 'skus': [{
        'sku_id': 'brand/concept/private-id', 'sku_key': 'internal-key',
        'colour': 'navy', 'size_label': 'L', 'pack_count': 2,
        'first_shirt_id': 'internal-component', 'actual_mass_g': -1,
        'facts': {'zip_count': 0}, 'reference_price_sek': 300}]},
        'variant_fields': {'colour': {}, 'size_label': {}, 'pack_count': {}}}
    original = deepcopy(package)
    assert variant_name(package, 'brand/concept/private-id') == (
        'Orla T-shirt (colour: navy, size label: L, pack count: 2)')
    assert package == original


def test_arbitrary_declared_family_choice_is_kept():
    package = {'public': {'name': 'Media tablet', 'skus': [{
        'sku_id': 'tablet', 'storage_gb': 256, 'screen_inches': 11,
        'model_price_factor': 1.3}]},
        'axes': {'storage_gb': {}, 'screen_inches': {}}}
    assert variant_name(package, 'tablet') == (
        'Media tablet (storage gb: 256, screen inches: 11)')


def test_explicit_empty_axes_do_not_fall_back_to_all_scalar_values():
    package = {'public': {'name': 'Fixed product', 'skus': [{
        'sku_id': 'fixed', 'reference_price_sek': 100, 'colour': 'private'}]},
        'variant_fields': {}}
    assert variant_name(package, 'fixed') == 'Fixed product'


def test_ambiguous_variants_require_authored_public_description_not_internal_ids():
    package = {'public': {'name': 'Product', 'skus': [
        {'sku_id': 'private-a'}, {'sku_id': 'private-b'}]}, 'variant_fields': {}}
    with pytest.raises(ValueError, match='distinct public retail choices'):
        variant_name(package, 'private-a')


def test_duplicate_visible_choices_are_ambiguous_even_when_private_facts_differ():
    package = {'public': {'name': 'Product', 'skus': [
        {'sku_id': 'private-a', 'colour': 'navy', 'facts': {'mass': 100}},
        {'sku_id': 'private-b', 'colour': 'navy', 'facts': {'mass': 200}}]},
        'variant_fields': {'colour': {}}}
    with pytest.raises(ValueError, match='distinct public retail choices'):
        variant_name(package, 'private-a')


def test_authored_fixture_configuration_remains_identifiable():
    package = {'public': {'name': 'Walking shoes', 'skus': [{
        'sku_id': 'compact', 'configuration': 'compact',
        'facts': {'internal': True}, 'reference_price_sek': 100}]}}
    assert variant_name(package, 'compact') == 'Walking shoes (configuration: compact)'


def test_container_field_is_not_serialized_into_request():
    package = {'public': {'name': 'Product', 'skus': [{
        'sku_id': 'sku', 'colour': 'black', 'facts': {'internal': 1}}]},
        'variant_fields': {'colour': {}, 'facts': {}}}
    assert variant_name(package, 'sku') == 'Product (colour: black)'


def test_same_brand_different_products_need_a_distinct_public_description():
    a = {'public': {'product_id': 'a', 'brand_id': 'same-brand', 'name': 'Norr T-shirt',
        'skus': [{'sku_id': 'a-white', 'colour': 'white'}]}, 'axes': {'colour': {}}}
    b = {'public': {'product_id': 'b', 'brand_id': 'same-brand', 'name': 'Norr T-shirt',
        'skus': [{'sku_id': 'b-white', 'colour': 'white'}]}, 'axes': {'colour': {}}}
    retailer = {'offers': [{'sku_id': 'a-white'}, {'sku_id': 'b-white'}]}
    with pytest.raises(ValueError, match='Retailer products lack distinct public'):
        variant_name(a, 'a-white', retailer=retailer, packages=[a, b])
    # An uncarried lookalike does not make this retailer's request ambiguous.
    assert variant_name(a, 'a-white', retailer={'offers': [{'sku_id': 'a-white'}]},
                        packages=[a, b]) == 'Norr T-shirt (colour: white)'
