"""Product-language families, independent of layout, facts and task grading.

Mappings anticipate the larger shopping-intent registry; website data support is
still limited to the six families in generate.FAMILIES. A neutral fallback allows
new vocabulary to be reviewed without pretending a new family is integrated.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Vocabulary:
    item: str
    plural: str
    covered: str
    alternatives: str
    facts_title: str
    coverage_note: str


PROFILES={
    'version':Vocabulary('version','versions','Version reviewed','Other versions','Product details',
        'Check the version and included contents when comparing this review with a retailer listing.'),
    'configuration':Vocabulary('configuration','configurations','Configuration reviewed','Other configurations','Specifications',
        'Hardware specifications can differ between configurations with the same model name.'),
    'fit':Vocabulary('size and fit option','size and fit options','Pair reviewed','Other sizes and colours','Size and product details',
        'The reviewed pair has the size, width and colour shown here. Another fit option may differ.'),
    'clothing':Vocabulary('size and style','sizes and styles','Size and style reviewed','Other sizes and styles','Sizing and materials',
        'Check the size, cut and material details for the item you intend to buy.'),
    'recipe':Vocabulary('recipe and pack','recipes and packs','Recipe and pack reviewed','Other recipes and pack sizes','Recipe and pack details',
        'A different recipe can contain different ingredients. Pack size is shown separately from the recipe.'),
    'beer':Vocabulary('beer and pack','beers and packs','Beer reviewed','Other pack sizes','Beer and pack details',
        'Check the beer identity and strength as well as the number and size of cans or bottles.'),
    'wine':Vocabulary('vintage and bottle size','vintages and bottle sizes','Wine reviewed','Other vintages and bottle sizes','Wine and bottle details',
        'Vintage, bottle size and bottles per pack are separate details. Non-vintage is a valid label, not a missing year.'),
    'formula':Vocabulary('formula and size','formulas and sizes','Formula reviewed','Other formulas and sizes','Formula and product details',
        'Ingredients can vary by formula. Check the exact formula rather than relying on the range name.'),
    'shade':Vocabulary('shade and finish','shades and finishes','Shade reviewed','Other shades and finishes','Shade and product details',
        'Check the shade and finish before transferring an impression to another variant.'),
    'compatibility':Vocabulary('compatible version','compatible versions','Version reviewed','Other compatible versions','Compatibility and contents',
        'Check the supported device, connector or fitting as well as what is included.'),
    'edition':Vocabulary('edition','editions','Edition reviewed','Other editions','Edition and contents',
        'Language, edition and included material can differ even when the title is the same.'),
    'dimensions':Vocabulary('size and finish','sizes and finishes','Size reviewed','Other sizes and finishes','Dimensions and materials',
        'Check the exact dimensions, finish and included contents of the item.'),
}
FAMILY_PROFILES={
    'footwear':'fit','trousers':'clothing','jackets':'clothing','pet_harnesses':'clothing',
    'laptops':'configuration','phones':'configuration','tablets':'configuration','monitors':'configuration',
    'memory_cards':'configuration','ssd':'configuration','keyboards':'configuration',
    'dog_food':'recipe','cat_food':'recipe','beer':'beer','wine':'wine',
    'moisturizers':'formula','cleansers':'formula','serums':'formula','shampoo':'formula','fragrance':'formula',
    'foundation':'shade','lip_colour':'shade',
    'phone_cases':'compatibility','chargers':'compatibility','camera_lenses':'compatibility',
    'brush_heads':'compatibility','printer_ink':'compatibility','vacuum_bags':'compatibility',
    'books':'edition','board_games':'edition',
    'bedding':'dimensions','cookware':'dimensions','furniture':'dimensions','tents':'dimensions',
    'headphones':'version','drills':'version','garden_trimmers':'version','washing_machines':'version',
    'backpacks':'version','strollers':'version',
}


def vocabulary(family):return PROFILES[FAMILY_PROFILES.get(family,'version')]


def common_vocabulary(families):
    keys={FAMILY_PROFILES.get(f,'version') for f in families}
    return PROFILES[next(iter(keys))] if len(keys)==1 else PROFILES['version']
