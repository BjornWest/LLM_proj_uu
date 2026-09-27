"""Authored semantic domains, not measured retail distributions or a stock catalog.

Each field explicitly declares its comparison operators and presentation role.
Numerical fit uses equality, never a generic 'larger is better' rule.
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Attribute:
    key: str
    label: str
    values: tuple
    operator: str = "eq"
    unit: str | None = None
    surface: str = "description"
    value_type: str = "string"


def choice(key, label, values, *, select=False):
    return Attribute(key, label, tuple(values.split("|")), surface="selection" if select else "description")


def number(key, label, values, unit, op="ge", *, select=False):
    return Attribute(key, label, tuple(values), op, unit,
                     "selection" if select else "description", "number")


def flag(key, label):
    return Attribute(key, label, (True,), value_type="boolean")


def excludes(key, label, values):
    return Attribute(key, label, tuple(values.split("|")), "excludes", value_type="string_set")


def includes(key, label, values):
    return Attribute(key, label, tuple(values.split("|")), "contains", value_type="string_set")


@dataclass(frozen=True)
class Family:
    id: str
    label: str
    noun: str
    reference_sek: int
    attributes: tuple[Attribute, ...]
    subject: str = "self"


COLOUR = choice("colour", "colour", "black|blue|grey|white", select=True)
PACK = number("pack_count", "units per pack", (1, 2, 4, 6), "units", "eq", select=True)
INGREDIENTS = excludes("ingredients", "ingredients", "added fragrance|lavender oil|coconut oil")


def family(id, label, noun, price, *attrs, subject="self"):
    return Family(id, label, noun, price, tuple(attrs), subject)


FAMILIES = {f.id: f for f in [
    family("footwear", "Footwear", "pair of shoes", 1100,
           number("size_eu", "EU shoe size", (38, 40, 42, 44, 46), "EU", "eq", select=True),
           choice("width", "width", "standard|wide", select=True), COLOUR,
           choice("activity", "intended activity", "running|walking|hiking|formal|beach"), flag("waterproof", "waterproof")),
    family("trousers", "Trousers", "pair of trousers", 700,
           number("waist_in", "waist", (28, 30, 32, 34, 36), "in", "eq", select=True),
           number("inseam_in", "inseam", (28, 30, 32, 34), "in", "eq", select=True), COLOUR,
           choice("cut", "cut", "straight|relaxed|slim"), includes("materials", "materials", "cotton|linen"),
           excludes("materials", "materials", "polyester|wool|cotton")),
    family("jackets", "Jackets", "jacket", 1200,
           choice("size_label", "labelled size", "S|M|L|XL", select=True), COLOUR,
           flag("waterproof", "waterproof"), choice("insulation", "insulation", "uninsulated|synthetic|down"),
           number("weight_g", "weight", (400, 600, 900), "g", "le")),
    family("laptops", "Laptops", "laptop", 11000,
           number("ram_gb", "RAM", (16, 32, 64), "GB", select=True),
           number("storage_gb", "storage", (256, 512, 1024), "GB", select=True),
           choice("keyboard_layout", "keyboard layout", "Swedish|US English|UK English", select=True),
           number("weight_kg", "weight", (1.3, 1.5, 2), "kg", "le"),
           includes("ports", "ports", "HDMI|USB-C")),
    family("phones", "Phones", "phone", 7000,
           number("storage_gb", "storage", (128, 256, 512), "GB", select=True), COLOUR,
           choice("os", "operating system", "Android|iOS"), flag("wireless_charging", "wireless charging"),
           number("screen_in", "screen size", (6, 6.5, 7), "in", "le")),
    family("tablets", "Tablets", "tablet", 4500,
           number("storage_gb", "storage", (64, 128, 256), "GB", select=True),
           choice("connectivity", "connectivity version", "Wi-Fi only|Wi-Fi and cellular", select=True),
           number("screen_in", "screen size", (10, 11, 12), "in"), flag("stylus_support", "stylus support")),
    family("monitors", "Monitors", "monitor", 3000,
           number("screen_in", "screen size", (24, 27, 32), "in", "eq", select=True),
           number("refresh_hz", "refresh rate", (60, 120, 144), "Hz"),
           choice("resolution", "resolution", "1920×1080|2560×1440|3840×2160"),
           includes("ports", "ports", "HDMI|DisplayPort|USB-C")),
    family("headphones", "Headphones", "pair of headphones", 1500,
           COLOUR, choice("form", "form", "over-ear|in-ear|on-ear"),
           flag("noise_cancelling", "active noise cancellation"),
           number("battery_hours", "advertised battery life with noise cancellation off", (20, 30, 40), "hours"),
           flag("microphone", "microphone")),
    family("keyboards", "Keyboards", "keyboard", 900,
           choice("layout", "keyboard layout", "Swedish|US English|UK English", select=True),
           choice("switch", "switch type", "linear|tactile|clicky", select=True), COLOUR,
           flag("wireless", "wireless connection"), flag("numpad", "numeric keypad")),
    family("memory_cards", "Memory cards", "memory card", 350,
           number("capacity_gb", "capacity", (64, 128, 256), "GB", select=True), PACK,
           choice("format", "card format", "SD|microSD"),
           choice("video_class", "video speed class", "V30|V60|V90")),
    family("ssd", "Solid-state storage", "SSD", 1300,
           number("capacity_gb", "capacity", (512, 1024, 2048), "GB", select=True),
           choice("interface", "interface", "SATA|NVMe PCIe 4.0|NVMe PCIe 5.0"),
           choice("form_factor", "form factor", "2.5-inch|M.2 2280|M.2 2230")),
    family("phone_cases", "Phone cases", "phone case", 300,
           choice("compatible_model", "compatible fictional phone model", "Aster P1|Aster P2|Boreal M3", select=True),
           COLOUR, choice("material", "material", "silicone|leather|polycarbonate"), flag("card_slots", "card slots")),
    family("chargers", "Chargers", "charger", 450,
           choice("plug", "wall plug", "EU|UK", select=True),
           number("power_w", "rated output power", (30, 65, 100), "W"),
           includes("protocols", "supported protocols", "USB PD|USB PD PPS"), flag("cable_included", "included cable")),
    family("camera_lenses", "Camera lenses", "camera lens", 6000,
           choice("mount", "mount", "Aster E|Boreal R|Cedar Z", select=True),
           number("focal_length_mm", "fixed focal length", (24, 35, 50, 85), "mm", "eq"),
           number("f_number", "maximum-aperture f-number", (1.8, 2, 2.8), "f-number", "le"),
           flag("stabilization", "optical stabilization"), number("weight_g", "weight", (400, 600, 900), "g", "le")),
    family("dog_food", "Dog food", "pack of dog food", 600,
           number("net_weight_kg", "net weight per pack", (2, 5, 10, 12), "kg", "eq", select=True),
           choice("recipe", "recipe", "lamb|salmon|chicken", select=True),
           choice("life_stage", "labelled life stage", "puppy|adult|senior"),
           choice("food_type", "food type", "dry|wet"),
           excludes("ingredients", "ingredients", "chicken|wheat|beef"), flag("complete_food", "labelled complete food"), subject="my dog"),
    family("cat_food", "Cat food", "pack of cat food", 400,
           number("net_weight_kg", "net weight per pack", (1, 2, 4, 8), "kg", "eq", select=True),
           choice("recipe", "recipe", "salmon|turkey|chicken", select=True),
           choice("life_stage", "labelled life stage", "kitten|adult|senior"),
           choice("food_type", "food type", "dry|wet"),
           excludes("ingredients", "ingredients", "beef|wheat"), flag("complete_food", "labelled complete food"), subject="my cat"),
    family("beer", "Beer", "pack of beer", 180,
           number("pack_count", "cans or bottles per pack", (1, 6, 12, 24), "units", "eq", select=True),
           number("volume_ml", "volume per can or bottle", (330, 440, 500), "ml", "eq", select=True),
           choice("beer_style", "beer style", "lager|IPA|stout|wheat beer"),
           number("alcohol_abv", "alcohol by volume", (0.5, 4, 5, 6, 8), "% ABV", "le"),
           choice("origin_country", "country of production", "Sweden|Germany|Belgium|United Kingdom"),
           choice("production_region", "production region", "Uppsala|Skåne|Bavaria|Flanders|Kent"),
           flag("unfiltered", "unfiltered beer"),
           choice("marketed_bitterness", "producer-described bitterness", "low|medium|high")),
    family("wine", "Wine", "pack of wine", 300,
           number("pack_count", "bottles per pack", (1, 3, 6), "units", "eq", select=True),
           number("volume_ml", "volume per bottle", (750, 1500), "ml", "eq", select=True),
           choice("vintage", "vintage", "2021|2022|2023|non-vintage", select=True),
           choice("wine_colour", "wine colour", "red|white|rosé"),
           includes("grapes", "grape varieties", "Chardonnay|Pinot Noir|Riesling|Cabernet Sauvignon"),
           choice("sweetness", "sweetness", "dry|off-dry|sweet"),
           flag("sparkling", "sparkling wine"),
           number("alcohol_abv", "alcohol by volume", (8, 11, 13, 15), "% ABV", "le"),
           choice("origin_country", "country of production", "France|Italy|Spain|Germany")),
    family("pet_harnesses", "Pet harnesses", "pet harness", 350,
           choice("species", "species", "dog|cat"), COLOUR,
           number("chest_min_cm", "minimum supported chest circumference", (30, 45, 60), "cm", "le"),
           number("chest_max_cm", "maximum supported chest circumference", (65, 80, 95), "cm", "ge"),
           flag("reflective", "reflective details")),
    family("moisturizers", "Moisturizers", "moisturizer", 300,
           number("volume_ml", "volume", (50, 100, 200), "ml", "eq", select=True),
           choice("texture", "texture", "cream|lotion|gel"), INGREDIENTS,
           includes("ingredients", "ingredients", "glycerin|niacinamide"),
           includes("marketed_skin_types", "skin types named by the manufacturer", "dry|oily|sensitive")),
    family("cleansers", "Cleansers", "cleanser", 200,
           number("volume_ml", "volume", (100, 200, 400), "ml", "eq", select=True),
           choice("format", "format", "gel|oil|balm"), INGREDIENTS,
           flag("rinse_off", "rinse-off formula")),
    family("serums", "Skincare serums", "serum", 350,
           number("volume_ml", "volume", (15, 30, 60), "ml", "eq", select=True),
           includes("ingredients", "ingredients", "niacinamide|glycerin"), INGREDIENTS,
           includes("marketed_benefits", "manufacturer's stated benefits", "hydration|more even-looking skin tone")),
    family("foundation", "Foundation", "foundation", 400,
           choice("shade", "shade code in this fictional range", "F1 cool|F2 neutral|M1 warm|D1 neutral", select=True),
           choice("coverage", "coverage", "light|medium|full"),
           choice("finish", "finish", "matte|satin|dewy"), INGREDIENTS,
           number("volume_ml", "volume", (20, 30, 50), "ml", "eq", select=True)),
    family("lip_colour", "Lip colour", "lip colour product", 200,
           choice("shade", "shade", "berry|coral|red|rose", select=True),
           choice("finish", "finish", "matte|satin|glossy"),
           choice("format", "format", "stick|liquid"), INGREDIENTS),
    family("shampoo", "Shampoo", "shampoo", 250,
           number("volume_ml", "volume", (250, 500, 1000), "ml", "eq", select=True),
           includes("marketed_hair_types", "hair types named by the manufacturer", "fine|curly|colour-treated"),
           INGREDIENTS, choice("packaging", "packaging", "bottle|refill pouch", select=True)),
    family("fragrance", "Fragrance", "fragrance", 800,
           number("volume_ml", "volume", (30, 50, 100), "ml", "eq", select=True),
           choice("concentration", "concentration label", "eau de toilette|eau de parfum", select=True),
           includes("notes", "listed fragrance notes", "citrus|vanilla|cedar"), flag("refillable", "refillable bottle")),
    family("brush_heads", "Toothbrush heads", "pack of toothbrush heads", 250,
           PACK, choice("compatible_system", "compatible fictional handle system", "Aster Sonic|Boreal Rotate"),
           choice("bristles", "bristle firmness", "soft|extra soft"), COLOUR),
    family("printer_ink", "Printer ink", "ink cartridge pack", 500,
           PACK, choice("colour", "ink colour", "black|cyan|magenta|yellow", select=True),
           choice("compatible_model", "compatible fictional printer", "Aster Print 10|Boreal Print 20"),
           number("rated_yield_pages", "manufacturer-rated page yield", (300, 500, 1000), "pages")),
    family("vacuum_bags", "Vacuum bags", "pack of vacuum bags", 150,
           PACK, choice("compatible_model", "compatible fictional vacuum", "Aster V1|Boreal V2"),
           choice("material", "bag material", "paper|synthetic")),
    family("drills", "Cordless drills", "cordless drill", 1600,
           choice("bundle", "bundle", "bare tool|tool with battery and charger", select=True),
           choice("battery_platform", "fictional battery platform", "Aster 18V|Boreal 18V|Cedar 12V"),
           number("torque_nm", "rated maximum torque", (30, 50, 70), "Nm"), flag("hammer_mode", "hammer mode")),
    family("garden_trimmers", "Garden trimmers", "garden trimmer", 1800,
           choice("bundle", "bundle", "bare tool|tool with battery and charger", select=True),
           choice("battery_platform", "fictional battery platform", "Aster 18V|Boreal 18V"),
           number("cutting_width_cm", "cutting width", (25, 30, 35), "cm"),
           number("weight_kg", "tool weight excluding battery", (2, 3, 4), "kg", "le")),
    family("board_games", "Board games", "board game", 450,
           choice("language", "language", "Swedish|English|German", select=True),
           number("min_players", "minimum player count", (1, 2), "players", "le"),
           number("max_players", "maximum player count", (4, 5, 6), "players"),
           number("play_time_min", "publisher-stated play time", (30, 60, 90), "minutes", "le"),
           flag("standalone", "playable without a separate base game")),
    family("books", "Books", "book", 220,
           choice("language", "language", "Swedish|English|German", select=True),
           choice("format", "format", "paperback|hardback", select=True),
           choice("genre", "genre", "mystery|fantasy|history")),
    family("bedding", "Bedding", "duvet cover set", 700,
           choice("dimensions", "duvet-cover dimensions", "150 × 200 cm|200 × 220 cm|240 × 220 cm", select=True),
           COLOUR, choice("material", "material", "cotton|linen"),
           number("pillowcases", "included pillowcases", (1, 2), "units", "eq")),
    family("cookware", "Frying pans", "frying pan", 600,
           number("diameter_cm", "diameter", (24, 28, 32), "cm", "eq", select=True),
           choice("material", "body material", "stainless steel|cast iron|aluminium"),
           choice("base", "base construction", "bonded magnetic base|bare aluminium base|magnetic stainless base|nonmagnetic stainless base|cast iron base"),
           flag("induction", "induction compatibility"), flag("lid_included", "included lid")),
    family("furniture", "Desks", "desk", 2000,
           COLOUR, number("width_cm", "width", (100, 120, 140), "cm", "le", select=True),
           number("depth_cm", "depth", (50, 60, 70), "cm", "le"),
           flag("height_adjustable", "adjustable height"), choice("material", "desktop material", "wood|laminate")),
    family("washing_machines", "Washing machines", "washing machine", 6500,
           COLOUR, number("capacity_kg", "rated load capacity", (7, 8, 9), "kg"),
           number("width_cm", "width", (55, 60, 65), "cm", "le"),
           number("depth_cm", "depth", (45, 55, 65), "cm", "le"),
           choice("installation", "installation type", "freestanding|integrated")),
    family("tents", "Tents", "tent", 2200,
           number("person_capacity", "advertised person capacity", (2, 3, 4), "people", select=True), COLOUR,
           number("weight_kg", "weight", (2, 3, 4), "kg", "le"),
           flag("freestanding", "freestanding construction")),
    family("backpacks", "Backpacks", "backpack", 1000,
           number("capacity_l", "capacity", (20, 30, 40), "L", "eq", select=True), COLOUR,
           number("weight_g", "weight", (600, 900, 1200), "g", "le"), flag("rain_cover", "included rain cover")),
    family("strollers", "Strollers", "stroller", 4500,
           COLOUR, choice("configuration", "configuration", "single|double", select=True),
           number("folded_width_cm", "folded width", (45, 55, 65), "cm", "le"),
           number("weight_kg", "weight", (7, 9, 12), "kg", "le"), flag("rain_cover", "included rain cover")),
]}


def catalog():
    return [asdict(f) for f in FAMILIES.values()]


OPTIONAL_ATTRIBUTES = {
    'footwear': (choice('shoe_type', 'shoe type',
        'walking shoes|running shoes|hiking shoes|dress shoes|flip-flops'),),
}


def attribute_for(family_id, field, operator=None):
    return next(a for a in (*FAMILIES[family_id].attributes, *OPTIONAL_ATTRIBUTES.get(family_id, ()))
                if a.key == field and (operator is None or a.operator == operator))
