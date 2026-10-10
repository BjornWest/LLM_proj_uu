"""Compact, opt-in media-tablet prose over completed model/SKU facts.

No manufacture, compiler projection, resampling or raw-fact fallback. Native
selectors remain a separate mandatory contract. Topic draws are model-stable;
each packet's actual assertions use the explicitly selected manufactured SKU.
"""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from .feature_publication import resolve_scalar_records, select_content
from .reviewed_feature_publication import load_reviewed_policy, CATALOGUE
from .public_field_rules import is_public_field, VERSION as RULE_VERSION
from .shared_state import freeze, mutable

CID = 'tablets.everyday_media_tablets'
SPEC = Path(__file__).parent / 'data/product_feature_policies/media_tablet_v1.json'


@lru_cache(maxsize=1)
def _loaded():
    raw = SPEC.read_bytes()
    spec = json.loads(raw)
    base = CATALOGUE / (CID + '.json')
    if sha256(base.read_bytes()).hexdigest() != spec['base_policy_sha256']:
        raise ValueError('Media-tablet base publication policy changed')
    policy = mutable(load_reviewed_policy(CID))
    selected = {path for group in spec['groups'].values() for path in group['fields']}
    for path, field in policy['fields'].items():
        if path in selected:
            if not is_public_field(path) or not field['semantic_id']:
                raise ValueError('Tablet prose requires an existing public meaning: ' + path)
            field['native_role'] = field['role']
            # Optional prose can repeat the selected RAM/storage facts without
            # changing the source policy or hiding their native selector roles.
            if field['role'] == 'buying_choice':
                field['role'] = 'descriptive'
        elif field['role'] in {'literal', 'descriptive'}:
            field['role'] = 'omit_low_value_detail'
    policy['disclosure_groups'] = {
        key: {'id': CID + '.content.' + key, 'display_group': g['display_group'],
              'fields': g['fields'], 'highlight_candidate': g['priority'] > 0,
              'highlight_priority': g['priority']}
        for key, g in spec['groups'].items()}
    policy['display_groups'] = spec['display_groups']
    return freeze(policy), freeze(spec), sha256(raw).hexdigest()


def _prose(key, values):
    used = set()
    def v(path):
        used.add(path)
        return values[path]
    def p(name): return v('product.facts.' + name)
    def s(name): return v('sku.' + name)
    if key == 'platform':
        text = f"{p('os_label')} with a {p('processor_label')} processor."
    elif key == 'screen':
        text = (f"{p('screen_size_label')} {p('screen_technology')}; "
                f"{p('screen_width_px')} × {p('screen_height_px')} px. "
                f"Rectangular screen diagonal: {p('screen_rectangle_diagonal_in'):g} inches.")
    elif key == 'refresh':
        text = f"Display refresh rate: {p('refresh_rate_hz'):g} Hz."
    elif key == 'memory_storage':
        parts = []
        if 'sku.ram_gb' in values:parts.append(f"{s('ram_gb')} GB RAM")
        parts.append(f"{s('storage_gb')} GB storage ({s('storage_kind')})")
        text = '; '.join(parts) + '.'
    elif key == 'wireless':
        text = f"{p('wifi_label')} and Bluetooth {p('bluetooth_label')}."
    elif key == 'cellular':
        present, trays = s('cellular_present'), s('physical_sim_tray_units')
        if present:
            modem = f" ({s('logical_modem_family')})" if 'sku.logical_modem_family' in values else ''
            text = f"Cellular modem included{modem}; physical SIM trays: {trays}."
        else:
            text = f"No cellular modem; physical SIM trays: {trays}."
    elif key == 'battery':
        parts = []
        for name, unit in [('battery_charge_mah', 'mAh'), ('battery_energy_wh', 'Wh')]:
            if 'product.facts.' + name in values:parts.append(f"{p(name):g} {unit}")
        if not parts:raise KeyError('No known battery quantity')
        if 'product.facts.battery_chemistry' in values:parts.append(p('battery_chemistry'))
        text = 'Battery: ' + ', '.join(parts) + '.'
    elif key == 'usb':
        units = p('usb_c_units')
        if units == 0:text = 'No USB-C port.'
        else:
            data = 'data supported' if p('c1_data') else 'data not supported'
            charge = 'tablet charging input supported' if p('c1_tablet_input_charging') else 'tablet charging input not supported'
            text = f"USB-C ports: {units}. C1: {p('c1_interface_label')}, {data}; {charge}."
    elif key == 'audio_card':
        text = f"Combo audio sockets: {p('audio_combo_units')}; memory-card slots: {p('memory_card_reader_units')}."
    elif key == 'wired_video':
        text = f"Wired video: {p('c1_video_declaration')}; {p('c1_video_conditions')}."
    elif key == 'reference_size_weight':
        text = (f"Reference configuration ({p('reference_configuration')}): "
                f"{p('reference_width_mm'):g} × {p('reference_height_mm'):g} mm; "
                f"maximum thickness {p('reference_max_thickness_mm'):g} mm; "
                f"weight {p('reference_mass_g'):g} g.")
    elif key == 'materials':
        text = f"Back material: {p('back_material')}; touch surface: {p('touch_surface_material')}."
    elif key == 'accessories':
        declaration = p('stylus_compatibility_declaration')
        # The accepted domain's declaration is explicit compatibility, not a
        # performance claim or a guarantee of an included pen.
        if declaration != 'declared compatible platform':
            raise KeyError('No approved pen compatibility wording')
        text = f"Compatible pen platform: {p('stylus_platform_label')}. "
        pen = s('pen_units')
        text += 'Pen not included. ' if pen == 0 else f"Pens included: {pen}. "
        text += f"Keyboard: {p('keyboard_compatibility_declaration')}."
    elif key == 'charging':
        units = s('adapter_units')
        text = 'Power adapter not included. ' if units == 0 else f"Power adapters included: {units}. "
        requirement = p('own_charger_requirement').replace(' own ', ' ')
        text += requirement[0].upper() + requirement[1:] + '.'
    elif key == 'cable':
        units = s('cable_units')
        text = 'Cable not included.' if units == 0 else f"Includes {units} {s('cable_connector_label')} cable ({s('cable_length_m'):g} m)."
    else:
        raise ValueError('Unknown tablet disclosure group')
    return text, used


def export_tablet_content(item, *, sku_id, seed, retailer_id, probabilities=None,
                          selected_groups=None):
    public = item['public']
    if public['concept_id'] != CID:
        raise ValueError('Media-tablet publication requires its declared concept')
    sku = next((s for s in public['skus'] if s['sku_id'] == sku_id), None)
    if sku is None or sku['product_id'] != public['product_id']:
        raise ValueError('Select a manufactured SKU of this tablet')
    policy, spec, digest = _loaded()
    statuses = {**item['catalog_status'], **item['sku_status'].get(sku_id, {})}
    projected = dict(sku)
    for target, source in spec['completed_aliases'].items():
        # Exact accepted caller alias, guarded by BOTH already recorded statuses.
        # Missing/unknown/NA fields are never upgraded or inferred from labels.
        if statuses.get(target) == statuses.get(source) == 'known' and source[4:] in sku:
            projected[target[4:]] = sku[source[4:]]
    records = resolve_scalar_records(policy, {'product': public, 'sku': projected}, statuses)
    packet = select_content(policy, records, seed=seed, retailer_id=retailer_id,
                            product_id=public['product_id'], probabilities=probabilities,
                            selected_groups=selected_groups)
    for display in packet['display_groups']:
        retained = []
        for slot in display['slots']:
            values = {a['field']: a['value'] for a in slot['assertions']}
            try:
                if any(path not in values for path in spec['groups'][slot['group_key']]['required_fields']):
                    raise KeyError('Incomplete tablet disclosure')
                text, used = _prose(slot['group_key'], values)
            except KeyError:
                packet['withheld_groups'].append(slot['group_key'])
                continue
            slot['text'] = text
            slot['assertions'] = [a for a in slot['assertions'] if a['field'] in used]
            slot['fields'] = [a['field'] for a in slot['assertions']]
            retained.append(slot)
        display['slots'] = retained
    packet['display_groups'] = [g for g in packet['display_groups'] if g['slots']]
    ids = {s['id'] for g in packet['display_groups'] for s in g['slots']}
    packet['highlight_candidates'] = [c for c in packet['highlight_candidates'] if c['slot_id'] in ids]
    packet['withheld_groups'] = list(dict.fromkeys(packet['withheld_groups']))
    packet.update(sku_id=sku_id, publication_policy_version='media-tablet-v1',
                  prose_authoring_version='media-tablet-scoped-prose-v1', policy_sha256=digest,
                  base_publication_policy_sha256=spec['base_policy_sha256'],
                  public_field_rules_version=RULE_VERSION,
                  sku_consistency='Topic selection is model/retailer-stable; configuration assertions belong to this exact selected SKU. Reference dimensions remain tied to their named reference configuration.')
    return packet
