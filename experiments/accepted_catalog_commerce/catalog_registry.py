"""Explicit commerce adoption, independent of authoring completion.

The historic five-concept default stays in package_export.CONCEPTS. These
ordinary parcel recipes use the same compiled graph, commerce and review stages;
acceptance alone never registers arbitrary completed consumers or bulky goods.
"""

VERSION = 'accepted-catalog-adoption-v4'
FIRST_ADDITIONS = (
    'footwear.road_running_shoes', 'footwear.trail_running_shoes',
    'footwear.low_hiking_shoes', 'footwear.hiking_boots',
    'footwear.flat_low_heeled_dress_shoes', 'footwear.heeled_dress_shoes',
    'footwear.flip_flops', 'footwear.winter_boots', 'footwear.rubber_boots',
    'jackets.rain_shells', 'jackets.softshell_jackets', 'jackets.fleece_jackets',
    'jackets.insulated_puffer_jackets', 'jackets.parkas_long_winter_coats',
    'jackets.everyday_casual_jackets',
    'headphones.over_ear_on_ear_headphones', 'headphones.in_ear_earbuds',
    'headphones.open_ear_sport_headphones', 'headphones.call_gaming_headsets',
    'phones.smartphones', 'phone_cases.shell_cases', 'phone_cases.folio_wallet_cases',
    'chargers.plug_in_wall_chargers', 'chargers.desktop_charging_hubs',
    'keyboards.desktop_keyboards', 'keyboards.slim_portable_keyboards',
    'keyboards.split_ergonomic_keyboards',
    'cat_food.dry_food', 'cat_food.wet_food', 'cat_food.treats_snacks',
    'dog_food.dry_food', 'dog_food.wet_food', 'dog_food.treats_snacks',
)


DIRECT_ADDITIONS = (
    'cat_litter.clumping_litter',
    'cat_litter.non_clumping_litter',
    'pet_bowls.standard_bowls',
    'pet_bowls.slow_feed_bowls',
    'pet_bowls.raised_feeding_stations',
    'pet_bowls.drinking_fountains',
    'pet_toys.chew_toys',
    'pet_toys.fetch_tug_toys',
    'pet_toys.soft_toys',
    'laptops.everyday_office_laptops',
    'pet_harnesses.strap_harnesses',
    'laptops.ultraportables',
    'pet_harnesses.vest_padded_harnesses',
    'laptops.creator_workstation_laptops',
    'laptops.gaming_laptops',
    'pet_toys.puzzle_treat_toys',
    'pet_toys.teaser_chase_toys',
    'tablets.pen_work_focused_tablets',
    'memory_cards.memory_cards',
    'ssd.nvme_ssds',
    'monitors.office_productivity_monitors',
    'ssd.sata_ssds',
    'monitors.high_refresh_gaming_monitors',
    'ssd.hard_disk_drives_hdds',
    'monitors.creative_image_work_monitors',
    'printer_ink.ink_cartridges_and_cartridge_sets',
    'monitors.ultrawide_workspace_monitors',
    'camera_lenses.standard_primes',
    'beer.lager_pilsner',
    'camera_lenses.wide_angle_primes',
    'beer.pale_ale_ipa',
    'camera_lenses.portrait_telephoto_primes',
    'beer.wheat_beer',
    'camera_lenses.zoom_lenses',
    'beer.stout_porter',
    'beer.sour_beer',
    'camera_lenses.macro_lenses',
    'beer.strong_dark_ale',
    'cookware.frying_pans',
    'cookware.saut_pans',
    'brush_heads.replacement_electric_toothbrush_heads',
)
SHARED_ADDITIONS = (
    'kitchen_utensils.turners_spatulas',
    'wine.crisp_light_white_wine',
    'kitchen_utensils.serving_spoons_ladles',
    'wine.aromatic_white_wine',
    'cookware.grill_pans',
    'wine.fuller_bodied_white_wine',
    'kitchen_utensils.whisks',
    'wine.light_red_wine',
    'wine.structured_full_bodied_red_wine',
    'kitchen_utensils.tongs',
    'pots.saucepans',
    'wine.ros_wine',
    'kitchen_utensils.strainers_colanders',
    'pots.stockpots',
    'wine.sparkling_wine',
    'kitchen_utensils.graters_peelers',
    'pots.casserole_dutch_oven_pots',
    'wine.sweet_dessert_wine',
    'kitchen_utensils.kitchen_knives',
    'kitchen_utensils.chopping_boards',
    'toothbrushes.manual_toothbrushes',
    'trousers.jeans',
    'towels.bath_hand_towels',
    'trousers.chinos',
    'toothbrushes.electric_toothbrushes',
    'towels.kitchen_towels',
    'trousers.tailored_trousers',
    'moisturizers.light_facial_moisturizers',
    'towels.travel_quick_drying_towels',
    'trousers.walking_travel_trousers',
    'moisturizers.rich_facial_creams',
    'bedding.duvet_cover_sets',
    'trousers.work_utility_trousers',
    'moisturizers.body_moisturizers',
    'bedding.sheets',
    'trousers.lounge_trousers',
    'cleansers.water_based_rinse_off_cleansers',
    'cleansers.oil_balm_cleansers',
    'bedding.pillowcases',
    'tops.button_up_shirts_blouses',
    'serums.hydration_focused_serums',
    'bedding.duvets',
    'tops.polo_shirts',
    'bedding.pillows',
    'serums.ingredient_focused_cosmetic_treatment_serums',
    'tops.sleeveless_tops',
    'tops.technical_base_layer_tops',
    'knitwear.pullovers',
    'foundation.tinted_light_coverage_bases',
    'knitwear.cardigans',
    'knitwear.zip_neck_sweaters',
)
ADDITIONS = (*FIRST_ADDITIONS, *DIRECT_ADDITIONS, *SHARED_ADDITIONS)

TASK_LABELS = {
    'footwear.road_running_shoes': 'road running shoes',
    'footwear.trail_running_shoes': 'trail running shoes',
    'footwear.low_hiking_shoes': 'low hiking shoes', 'footwear.hiking_boots': 'hiking boots',
    'footwear.flat_low_heeled_dress_shoes': 'flat or low-heeled dress shoes',
    'footwear.heeled_dress_shoes': 'heeled dress shoes', 'footwear.flip_flops': 'flip-flops',
    'footwear.winter_boots': 'winter boots', 'footwear.rubber_boots': 'rubber boots',
    'jackets.rain_shells': 'rain shell jacket', 'jackets.softshell_jackets': 'softshell jacket',
    'jackets.fleece_jackets': 'fleece jacket', 'jackets.insulated_puffer_jackets': 'insulated puffer jacket',
    'jackets.parkas_long_winter_coats': 'parka or long winter coat',
    'jackets.everyday_casual_jackets': 'everyday casual jacket',
    'headphones.over_ear_on_ear_headphones': 'pair of over-ear or on-ear headphones',
    'headphones.in_ear_earbuds': 'pair of in-ear earbuds',
    'headphones.open_ear_sport_headphones': 'pair of open-ear sport headphones',
    'headphones.call_gaming_headsets': 'call or gaming headset',
    'phones.smartphones': 'smartphone', 'phone_cases.shell_cases': 'shell phone case',
    'phone_cases.folio_wallet_cases': 'folio or wallet phone case',
    'chargers.plug_in_wall_chargers': 'plug-in wall charger',
    'chargers.desktop_charging_hubs': 'desktop charging hub',
    'keyboards.desktop_keyboards': 'desktop keyboard',
    'keyboards.slim_portable_keyboards': 'slim portable keyboard',
    'keyboards.split_ergonomic_keyboards': 'split ergonomic keyboard',
    'cat_food.dry_food': 'pack of dry cat food', 'cat_food.wet_food': 'pack of wet cat food',
    'cat_food.treats_snacks': 'pack of cat treats or snacks',
    'dog_food.dry_food': 'pack of dry dog food', 'dog_food.wet_food': 'pack of wet dog food',
    'dog_food.treats_snacks': 'pack of dog treats or snacks',
}

TASK_LABELS.update({'cat_litter.clumping_litter': 'pack of clumping cat litter', 'cat_litter.non_clumping_litter': 'pack of non-clumping cat litter', 'pet_bowls.standard_bowls': 'pet bowl', 'pet_bowls.slow_feed_bowls': 'slow-feed pet bowl', 'pet_bowls.raised_feeding_stations': 'raised pet feeding station', 'pet_bowls.drinking_fountains': 'pet drinking fountain', 'pet_toys.chew_toys': 'pet chew toy', 'pet_toys.fetch_tug_toys': 'pet fetch or tug toy', 'pet_toys.soft_toys': 'soft pet toy', 'laptops.everyday_office_laptops': 'everyday or office laptop', 'pet_harnesses.strap_harnesses': 'strap pet harness', 'laptops.ultraportables': 'ultraportable laptop', 'pet_harnesses.vest_padded_harnesses': 'vest or padded pet harness', 'laptops.creator_workstation_laptops': 'creator or workstation laptop', 'laptops.gaming_laptops': 'gaming laptop', 'pet_toys.puzzle_treat_toys': 'pet puzzle or treat toy', 'pet_toys.teaser_chase_toys': 'pet teaser or chase toy', 'tablets.pen_work_focused_tablets': 'pen or work-focused tablet', 'memory_cards.memory_cards': 'memory card', 'ssd.nvme_ssds': 'NVMe SSD', 'monitors.office_productivity_monitors': 'office or productivity monitor', 'ssd.sata_ssds': 'SATA SSD', 'monitors.high_refresh_gaming_monitors': 'high-refresh gaming monitor', 'ssd.hard_disk_drives_hdds': 'hard disk drive', 'monitors.creative_image_work_monitors': 'creative image-work monitor', 'printer_ink.ink_cartridges_and_cartridge_sets': 'ink cartridge or cartridge set', 'monitors.ultrawide_workspace_monitors': 'ultrawide workspace monitor', 'camera_lenses.standard_primes': 'standard prime camera lens', 'beer.lager_pilsner': 'lager or pilsner', 'camera_lenses.wide_angle_primes': 'wide-angle prime camera lens', 'beer.pale_ale_ipa': 'pale ale or IPA', 'camera_lenses.portrait_telephoto_primes': 'portrait or telephoto prime camera lens', 'beer.wheat_beer': 'wheat beer', 'camera_lenses.zoom_lenses': 'zoom camera lens', 'beer.stout_porter': 'stout or porter', 'beer.sour_beer': 'sour beer', 'camera_lenses.macro_lenses': 'macro camera lens', 'beer.strong_dark_ale': 'strong dark ale', 'cookware.frying_pans': 'frying pan', 'cookware.saut_pans': 'sauté pan', 'brush_heads.replacement_electric_toothbrush_heads': 'pack of replacement electric toothbrush heads'})


TASK_LABELS.update({'kitchen_utensils.turners_spatulas': 'turners/spatulas', 'kitchen_utensils.serving_spoons_ladles': 'serving spoons/ladles', 'kitchen_utensils.whisks': 'whisks', 'kitchen_utensils.tongs': 'tongs', 'kitchen_utensils.strainers_colanders': 'strainers/colanders', 'kitchen_utensils.graters_peelers': 'graters/peelers', 'kitchen_utensils.kitchen_knives': 'kitchen knives', 'kitchen_utensils.chopping_boards': 'chopping boards', 'cleansers.water_based_rinse_off_cleansers': 'water-based rinse-off cleansers', 'cleansers.oil_balm_cleansers': 'oil/balm cleansers', 'towels.bath_hand_towels': 'bath/hand towels', 'towels.kitchen_towels': 'kitchen towels', 'towels.travel_quick_drying_towels': 'travel/quick-drying towels', 'bedding.duvet_cover_sets': 'duvet-cover sets', 'bedding.sheets': 'sheets', 'bedding.pillowcases': 'pillowcases', 'bedding.duvets': 'duvets', 'bedding.pillows': 'pillows', 'tops.button_up_shirts_blouses': 'button-up shirts/blouses', 'tops.polo_shirts': 'polo shirts', 'tops.sleeveless_tops': 'sleeveless tops', 'tops.technical_base_layer_tops': 'technical/base-layer tops', 'knitwear.pullovers': 'pullovers', 'knitwear.cardigans': 'cardigans', 'knitwear.zip_neck_sweaters': 'zip-neck sweaters', 'wine.crisp_light_white_wine': 'crisp/light white wine', 'wine.aromatic_white_wine': 'aromatic white wine', 'wine.fuller_bodied_white_wine': 'fuller-bodied white wine', 'wine.light_red_wine': 'light red wine', 'wine.structured_full_bodied_red_wine': 'structured/full-bodied red wine', 'wine.ros_wine': 'rosé wine', 'wine.sparkling_wine': 'sparkling wine', 'wine.sweet_dessert_wine': 'sweet/dessert wine', 'moisturizers.light_facial_moisturizers': 'light facial moisturizers', 'moisturizers.rich_facial_creams': 'rich facial creams', 'moisturizers.body_moisturizers': 'body moisturizers', 'foundation.tinted_light_coverage_bases': 'tinted/light-coverage bases', 'toothbrushes.manual_toothbrushes': 'manual toothbrushes', 'toothbrushes.electric_toothbrushes': 'electric toothbrushes', 'pots.saucepans': 'saucepans', 'pots.stockpots': 'stockpots', 'pots.casserole_dutch_oven_pots': 'casserole/dutch-oven pots', 'trousers.jeans': 'jeans', 'trousers.chinos': 'chinos', 'trousers.tailored_trousers': 'tailored trousers', 'trousers.walking_travel_trousers': 'walking/travel trousers', 'trousers.work_utility_trousers': 'work/utility trousers', 'trousers.lounge_trousers': 'lounge trousers', 'serums.hydration_focused_serums': 'hydration-focused serums', 'serums.ingredient_focused_cosmetic_treatment_serums': 'ingredient-focused cosmetic treatment serums', 'cookware.grill_pans': 'grill pans', 'cookware.woks': 'woks'})

def input_defaults(document, inputs):
    """Use declared authored brand priors, without overriding sampled inputs."""
    from copy import deepcopy
    result = deepcopy(inputs)
    for entity, values in document.get('metadata', {}).get('preview_input_defaults', {}).items():
        for key, value in values.items():
            definition = document['fields'].get(entity + '.' + key, {})
            if definition.get('input'):
                result.setdefault(entity, {}).setdefault(key, deepcopy(value))
    return result


def naming_profile(template_id):
    # Existing templates already establish scope. Do not rename a pet shop as
    # a shoe shop just because the first bridge covered shoes only.
    if template_id in ('electronics', 'apparel', 'pets', 'drinks'):
        return template_id
    return 'marketplace' if template_id in ('marketplace', 'department_store') else 'footwear'
