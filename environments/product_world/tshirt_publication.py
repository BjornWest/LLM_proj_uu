"""Opt-in T-shirt scoped prose over the approved publication policy.

Consumes a completed commerce product; no compiler/caller replay or new product
sampling. Whole-garment composition is never inferred from component fractions.
"""
from .feature_publication import load_policy, select_content, policy_sha256, resolve_scalar_records

CID = 'tops.t_shirts'


def _records(item, policy):
    return resolve_scalar_records(policy, {'product': item['public']}, item['catalog_status'])


def _prose(group, values):
    def v(key): return values['product.facts.' + key]
    if group == 'main_fabric':
        return f"Main body and sleeve fabric: {v('fabric_structure')}, {v('main_fabric_cotton_percent')}% cotton. This composition excludes neck trim, sewing thread and labels."
    if group == 'fit':
        return f"{v('cut').capitalize()} with {v('shoulder_style')}."
    if group == 'neckline':
        return f"{v('neckline')} neckline."
    if group == 'fabric_weight':
        text = f"{v('fabric_weight_label').capitalize()} fabric."
        if 'product.facts.nominal_main_fabric_areal_mass_g_m2' in values:
            text += f" Nominal main-cloth areal mass: {v('nominal_main_fabric_areal_mass_g_m2')} g/m²; not a measured purchased-shirt mass."
        return text
    if group == 'neck_trim':
        return f"Neck trim: {v('neck_trim_structure')}, {v('neck_trim_cotton_percent')}% cotton and {v('neck_trim_elastane_percent')}% elastane. These percentages describe the trim only."
    if group == 'style':
        return f"{v('sleeve_length').capitalize()} sleeves and a {v('lower_hem')}. " + ('Printed finish.' if v('print_present') else 'Plain, without a print.')
    if group == 'machine_wash':
        return f"Machine wash at up to {v('wash_temperature_max_c')}°C on a {v('wash_cycle')} cycle." if v('wash_machine_allowed') else 'Do not machine wash.'
    if group == 'drying':
        return ('Line drying is allowed.' if v('line_drying_allowed') else 'Do not line dry.') + (' Tumble drying is allowed.' if v('tumble_drying_allowed') else ' Do not tumble dry.')
    if group == 'bleach': return 'Bleaching is allowed.' if v('bleach_allowed') else 'Do not bleach.'
    if group == 'dry_cleaning': return 'Dry cleaning is allowed.' if v('dry_cleaning_allowed') else 'Do not dry clean.'
    if group == 'ironing':
        return (f"Iron the main body and sleeve cloth only at up to {v('iron_main_cloth_temperature_max_c')}°C." if v('iron_main_cloth_only') else 'Do not iron the main cloth.') + (' Neck trim may be ironed.' if v('iron_neck_trim_allowed') else ' Do not iron the neck trim.')
    raise ValueError('No approved prose adapter for group ' + group)


def export_tshirt_content(item, *, seed, retailer_id, probabilities=None, selected_groups=None):
    if item['public']['concept_id'] != CID:
        raise ValueError('T-shirt publication adapter requires its declared concept')
    policy = load_policy(CID)
    packet = select_content(policy, _records(item, policy), seed=seed, retailer_id=retailer_id,
                            product_id=item['public']['product_id'], probabilities=probabilities,
                            selected_groups=selected_groups)
    for display in packet['display_groups']:
        retained = []
        for slot in display['slots']:
            if slot['group_key'] not in {'main_fabric','fit','neckline','fabric_weight','neck_trim','style','machine_wash','drying','bleach','dry_cleaning','ironing'}:
                continue
            values = {a['field']: a['value'] for a in slot['assertions']}
            try:
                text = _prose(slot['group_key'], values)
            except KeyError:
                # A prose statement requiring missing/unknown source fields is
                # withheld as a unit. Do not silently print a half-true sentence.
                packet['withheld_groups'].append(slot['group_key'])
                continue
            slot['text'] = text
            retained.append(slot)
        display['slots'] = retained
    packet['display_groups'] = [d for d in packet['display_groups'] if d['slots']]
    published = {slot['id'] for d in packet['display_groups'] for slot in d['slots']}
    packet['highlight_candidates'] = [h for h in packet['highlight_candidates'] if h['slot_id'] in published]
    packet['prose_authoring_version'] = 'tshirt-scoped-prose-v1'
    packet['policy_sha256'] = policy_sha256(CID)
    packet['sku_consistency'] = 'These model-scoped facts are shared by every manufactured T-shirt SKU; selectors retain the native SKU/quantity/status contract.'
    return packet
