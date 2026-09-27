"""Slot-based prose with private source spans; never add a requirement in wording."""
from .catalog import FAMILIES

# These belong to the environment/instructions, not to every human message. The
# policy export includes them so the oracle cannot impose undisclosed conventions.
ENVIRONMENT_CONTEXT = {
    "shopping_scope": "The provided shops, delivery to Sweden, prices in SEK. Compare currently purchasable offers.",
    "price_convention": "Delivered totals include all mandatory charges once, for the requested quantities. Basket quotes include applicable discounts and each shipment.",
    "comparison_convention": "Any tied optimum is acceptable. Average prices use the cheapest eligible delivered quote per retailer, rounded half-up to the nearest öre; an empty population is undefined. Explain uncertainty if evidence is missing.",
    "interaction_convention": "A comparison request authorizes research and a report, not an order, account creation or persistent changes. Ask for missing personal fit or device compatibility information when needed. Ordinary unspecified preferences are unconstrained.",
    "delivery_convention": "Delivery is the latest promised arrival in calendar days after ordering; for a basket, use the last shipment. Fastest-delivery ties are broken by delivered cost.",
}


def phrase(p, rng=None):
    def pick(*options): return rng.choice(options) if rng else options[0]
    value, field = p["value"], p["field"]
    label = {"size_label": "size", "compatible_model": "device model", "compatible_system": "handle system",
             "shade": "shade", "net_weight_kg": "pack weight", "marketed_skin_types": "listed skin types",
             "marketed_hair_types": "listed hair types", "marketed_benefits": "claimed benefits"}.get(field, p["label"])
    if p["value_type"] == "boolean":
        special = {"waterproof": "waterproof", "induction": "suitable for induction", "wireless": "wireless",
                   "freestanding": "freestanding", "standalone": "playable on its own",
                   "refillable": "refillable", "height_adjustable": "height-adjustable"}
        if field in special:
            return ("it needs to be " if value else "it must not be ") + special[field]
        return ("it needs " if value else "it must not have ") + {"lid_included": "a lid included", "cable_included": "a cable included", "rain_cover": "a rain cover", "complete_food": "to be labelled complete food"}.get(field, label)
    if field == "size_eu": return pick(f"I wear EU size {value}", f"size {value} EU, please")
    if field == "colour": return pick(f"make it {value}", f"I need it in {value}")
    if field == "material": return pick(f"it needs to be {value}", f"{value}, please")
    if field == "base": return f"it needs a {value}"
    if field == "activity": return pick(f"they're for {value}", f"I need them for {value}")
    if field == "diameter_cm": return pick(f"I need a {value} cm diameter", f"{value} cm across, please")
    if field == "volume_ml": return pick(f"I need the {value} ml size", f"make it {value} ml")
    if field == "production_region": return pick(f"it needs to be produced in {value}", f"please look for something made in {value}")
    if field == "marketed_bitterness": return f"look for {value} bitterness according to the producer's description"
    if field == "beer_style": return f"make it {'an' if value == 'IPA' else 'a'} {value}"
    if field == "wine_colour": return f"I'm looking for a {value} wine"
    if field == "alcohol_abv": return pick(f"keep it to {value}% ABV or less", f"the alcohol content must be no more than {value}% ABV")
    if field == "net_weight_kg": return pick(f"I want a {value} kg pack", f"the pack should weigh {value} kg")
    if field == "pack_count": return pick(f"I need {value} units per pack", f"make it a {value}-pack")
    if field == "recipe": return pick(f"I want the {value} recipe", f"the {value} recipe, please")
    if field == "food_type": return pick(f"it needs to be {value} food", f"{value} food, please")
    if field == "life_stage": return f"it needs to be labelled for {value}s" if value in ("adult", "senior") else f"it needs to be labelled for {'puppies' if value == 'puppy' else 'kittens'}"
    if field == "dimensions": return pick(f"it needs to fit a {value} duvet", f"my duvet is {value}")
    if field == "shade": return pick(f"I use shade {value}", f"shade {value}, please")
    if field == "waist_in": return pick(f"I wear a {value}-inch waist", f"the waist needs to be {value} inches")
    if field == "inseam_in": return pick(f"I need a {value}-inch inside leg", f"the inseam needs to be {value} inches")
    if field == "size_label": return pick(f"I wear size {value}", f"size {value}, please")
    if field == "compatible_model": return pick(f"it needs to fit my {value}", f"it must be compatible with {value}")
    if field == "compatible_system": return pick(f"it is for a {value} handle", f"it must be compatible with {value}")
    if field == "mount": return pick(f"I need the {value} mount", f"it is for a {value} mount")
    if field == "ingredients" and p["operator"] == "contains": return pick(f"it needs to contain {value}", f"with {value}, please")
    if field == "ingredients" and p["operator"] == "excludes": return pick(f"no {value}, please", f"it must be free of {value}", f"nothing with {value}")
    if p["operator"] == "contains": return pick(f"the {label} must include {value}", f"I need {value} among the {label}")
    if p["operator"] == "excludes": return pick(f"no {value} in the {label}", f"the {label} must exclude {value}")
    unit = f" {p['unit']}" if p["unit"] else ""
    if p["operator"] == "ge": return pick(f"I need at least {value}{unit} {label}", f"the {label} must be {value}{unit} or more")
    if p["operator"] == "le": return pick(f"the {label} must be no more than {value}{unit}", f"at most {value}{unit} for {label}, please")
    return pick(f"I need {value}{unit} for {label}", f"the {label} needs to be {value}{unit}")


def sentences(items):
    return " ".join(s[0].upper() + s[1:] + "." for s in items)


def render(request, facts, prose_seed, world_memories=()):
    from .generator import stream
    rng = stream(prose_seed, "prose")
    profile, episodes = [], []
    from .world import phrase as world_phrase
    for fact in world_memories:
        p=fact['predicate']
        scope={'shopping':'future shopping','pickup':'future click-and-collect purchases','inspect':'future in-store visits'}[fact['scope']]
        if fact['channel']=='profile':
            profile.append({'id':fact['id'],'subject':'self','strength':'required','scope':scope,
                            'attribute':p['label'],'operator':p['operator'],'value':p['value'],'unit':p['unit']})
        else:
            episodes.append({'id':fact['id'],'text':f'Saved from an earlier shopping conversation: "For {scope}: {sentences([world_phrase(p,rng)])} Please remember this."'})
    for fact in facts:
        if fact["channel"] == "profile":
            p = fact["predicate"]
            profile.append({"id": fact["id"], "subject": fact["subject"],
                            "product_family": fact["family_id"], "strength": "required",
                            "scope": "future purchases in this family", "attribute": p["label"],
                            "operator": p["operator"], "value": p["value"], "unit": p["unit"]})
        else:
            subject = "me" if fact["subject"] == "self" else fact["subject"]
            family = FAMILIES[fact["family_id"]].label.lower()
            requirement = sentences([phrase(fact["predicate"], rng)])
            text = rng.choice((
                f'When we last looked at {family} for {subject}, I said: "{requirement} Please remember that for next time."',
                f'From an earlier {family} search for {subject}: "For future purchases: {requirement}"',
                f'Saved from our last conversation about {family} for {subject}: "Please stick to this next time too: {requirement}"'))
            episodes.append({"id": fact["id"], "text": text})
    segments = []
    def add(stage, text, refs=None):
        segments.append({"stage": stage, "text": (" " if segments else "") + text, "sources": refs or []})
    q = request["query"]
    activity=q.get('activity','delivery')
    objective=q['objective'][0]['field'] if q['objective'] else None
    if q['operation']=='assortment':
        opening=rng.choice(("Which physical store has the widest selection of", "Can you find the shop with the most different"))
    elif activity=='inspect':
        opening=rng.choice(("Find the nearest physical shop where I can try out","Where's the closest physical shop where I can inspect"))
    elif activity=='pickup' and objective=='travel_minutes':
        opening=rng.choice(("Find the nearest place I can collect","Where's the closest shop for picking up"))
    elif activity=='pickup' and objective=='ready_days':
        opening=rng.choice(("Where can I collect this soonest:","Find the soonest available collection for"))
    elif activity=='pickup':
        opening=rng.choice(("Find the cheapest collection option for","Where can I get the best price for collecting"))
    elif objective=='unit_price':
        opening=rng.choice((f"Find the lowest delivered price per {q['unit']} for",f"What's the best value per {q['unit']} for"))
    elif q["operation"] == "aggregate":
        opening = rng.choice(("What's the average delivered price for", "Can you check the average price, including delivery, of", "How much does this cost on average with delivery:"))
    elif q["objective"][0]["field"] == "arrival_days":
        opening = rng.choice(("Where can I get the fastest delivery on", "Find me the quickest delivery for", "Who can deliver this soonest:"))
    elif len(request["lines"]) > 1:
        opening = rng.choice(("Can you find the cheapest way to get", "Find the lowest total price for", "Where's the cheapest place to order"))
    else:
        opening = rng.choice(("Can you find the cheapest", "Find me the lowest delivered price for", "Where's the cheapest place to get", "I'm looking for the best price on"))
    add("objective", opening)
    for index, line in enumerate(request["lines"]):
        name = line["model"]["name"] if line["model"] else FAMILIES[line["family_id"]].noun
        quantity = ("an" if name[0].lower() in "aeiou" or name == "SSD" else "a") if line["quantity"] == 1 else str(line["quantity"]) + " ×"
        if line["model"]: quantity = "1 ×" if line["quantity"] == 1 else quantity
        subject = "" if line["subject"] == "self" else " for " + line["subject"]
        punctuation = "?" if not index and opening.startswith(("Can", "Where", "Who", "What", "How")) else "."
        product_text=f"shoes that would suit me? I want to go and try them on." if q['operation']=='assortment' else ("Also, " if index else "") + f"{quantity} {name}{subject}{punctuation}"
        add("product", product_text, [line["id"]])
        ordinary = [p for p in line["explicit_requirements"] if not p.get("temporary_override")]
        overrides = [p for p in line["explicit_requirements"] if p.get("temporary_override")]
        if ordinary:
            add("requirement", sentences([phrase(p, rng) for p in ordinary]), [line["id"] + ":" + p["field"] + ":" + p["operator"] for p in ordinary])
        if overrides:
            add("override", rng.choice(("Just for this one: ", "For this request only: ", "This time: ")) +
                sentences([phrase(p, rng) for p in overrides]) + " That replaces my usual preference for this order.",
                [line["id"] + ":" + p["field"] + ":" + p["operator"] for p in overrides])
    for p in request.get('explicit_world_requirements',[]):
        text=sentences([world_phrase(p,rng)])
        if p.get('temporary_override'):text='Just for this search: '+text+' That replaces my usual preference.'
        add('override' if p.get('temporary_override') else 'constraint',text,['world:'+p['field']])
    if facts or world_memories:
        add("memory", rng.choice(("Use my usual requirements too.", "Please keep my saved requirements in mind.", "The rest of my usual requirements still apply.")), [f["id"] for f in (*facts,*world_memories)])
    c = request["constraints"]
    if q['operation']=='assortment':
        lo,hi=c['price_min_minor']/100,c['budget_minor']/100
        add('constraint',rng.choice((f"I'm looking to spend {lo:g}–{hi:g} kr per pair.",f"My price range is {lo:g}–{hi:g} SEK for a pair.")),['price_min_minor','budget_minor'])
    elif "budget_minor" in c:
        value = f"{c['budget_minor'] / 100:g} SEK"
        wording=(f"Keep the collection total to {value} max.",f"My budget for the product and collection fees is {value}.") if activity=='pickup' else (f"Keep it to {value} max, delivery included.", f"My budget is {value} including shipping.", f"I can spend up to {value} all in.")
        add("constraint", rng.choice(wording), ["budget_minor"])
    elif q["operation"] != "aggregate" and activity=='delivery':
        add("scope", rng.choice(("Include delivery in the price.", "Please count shipping too.", "Compare totals with shipping included.")))
    if "arrival_days_max" in c:
        d = c["arrival_days_max"]
        add("constraint", rng.choice((f"I need everything here within {d} calendar days of ordering.", f"Delivery needs to take {d} calendar days at most.")), ["arrival_days_max"])
    if "delivery_mode" in c:
        add("constraint", rng.choice(("It needs to be home delivery.", "Please choose delivery to my door.", "Home delivery only, please.")), ["delivery_mode"])
    if 'ready_days_max' in c:
        add('constraint',f"It must be ready to collect within {c['ready_days_max']} days.",['ready_days_max'])
    if len(request["lines"]) > 1:
        add("scope", rng.choice(("I want to buy the whole list from one shop.", "Please keep everything with one retailer.")) if q["allocation"] == "single_store" else
            rng.choice(("Different shops are fine if the total is cheaper.", "You can split the list between shops.")))
    if q["operation"] == "aggregate":
        add("scope", rng.choice(("Count each shop once, using its lowest qualifying price.", "Use the cheapest matching offer from each shop for the average.")))
    environment=ENVIRONMENT_CONTEXT.copy()
    if 'destination_location' in request['context']:
        point=request['context']['destination_location']
        environment.update(user_location=point,shopping_scope=f"The provided shops; user home in {point['city']}, {point['country']}. All scenario prices are in SEK.")
    if activity!='delivery':
        environment['price_convention']='Collection totals include the item and mandatory collection charges. Personal travel costs are excluded. Inspection requests do not require purchasing the item.'
        environment['delivery_convention']='Readiness is calendar days before collection; travel duration is one-way from home using the specified mode. Check opening hours separately; this snapshot does not model them.'
        environment['comparison_convention']='Nearest means minimum estimated travel minutes in the requested mode. All ties are acceptable. Fastest collection compares readiness days, then collection cost. Missing route evidence remains unknown.'
    if objective=='unit_price':environment['comparison_convention']=f"Compare delivered total divided by the full purchased quantity in {q['unit']}, including all units per pack. All exact ties are acceptable."
    if q['operation']=='assortment':
        environment['price_convention']='Use the listed item price per pair, including both price-range endpoints. Online coupons, delivery/collection fees and personal travel costs do not change the displayed in-store price in this task.'
        environment['comparison_convention']='Compare individual branches by distinct matching shoe models already in saleable stock in the required size and available to try on. Count a model once even if several colours or widths qualify. Warehouse stock, transfers and display-only units do not count. All branches tied for the largest positive assortment are acceptable; no matching models means no match. Missing evidence remains unknown.'
    if world_memories or request.get('explicit_world_requirements'):
        environment['review_convention']='Customer review thresholds use the arithmetic mean of all published stars in the provided frozen merchant-review corpus, plus its published review count; this is not a safety guarantee.'
    return {"user_message": "".join(s["text"] for s in segments),
            "memories": {"profile": profile, "episodes": episodes},
            "environment_context": environment}, segments
