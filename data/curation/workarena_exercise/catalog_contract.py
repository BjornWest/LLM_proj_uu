"""Scoped order configuration check; preserves the native Label option semantics.

The empty Optional Software field is a Label in the inspected item_option_new
metadata. Unknown labels or nonempty values are not silently discarded.
"""
def configuration_correct(order):
    if not isinstance(order, dict) or not isinstance(order.get('items'), list):return None
    items=order['items']
    if len(items)!=1:return False
    item=items[0]
    if not isinstance(item, dict) or not isinstance(item.get('options'), dict):return None
    options=item['options']
    expected={'Adobe Acrobat':'false','Adobe Photoshop':'false','Additional software requirements':'Slack'}
    if not expected.keys()<=options.keys():return None
    if item.get('quantity')!='1' or item.get('short_description')!='Lenovo - Carbon x1':return False
    if options.keys()-expected.keys()-{'Optional Software'}:return False
    if 'Optional Software' in options and options['Optional Software']!='':return False
    return all(isinstance(options[k],str) and options[k].strip().casefold()==v.casefold() for k,v in expected.items())
