"""Small copied-renderer confirmation projection; native acceptance is separate."""
from hashlib import sha256
from pathlib import Path

VERSION = 'website-simulated-order-presentation-v1'
IMPORT = '\nimport {purchaseForm as simulatedPurchaseForm,confirmation as simulatedOrderConfirmation,complete as completeSimulatedOrder} from "./simulated-order-presentation.js";\n'
QUOTE_IMPORT = '\nimport {orderMethods,explicitOrderQuote} from "./simulated-order-transport.js";\n'
QUOTE_HOOKS = {
    'export const worldBinding={...itemBinding,basket:true,inquiryKey,':
        'export const worldBinding={...itemBinding,basket:true,inquiryKey,\n  ...orderMethods({data,payload,requests,inquiryKey}),',
    'const key=inquiryKey(draft);': 'const key=inquiryKey(draft);let settledKey=key;',
    'requests.set(key,{value});':
        'const explicit=await explicitOrderQuote(value,draft,{data,payload,inquiryKey,expectedKey:key});\n      if(!explicit)return false;\n      if(explicit.selection)draft.basketSelection={...explicit.selection};\n      settledKey=inquiryKey(draft);requests.set(settledKey,{value:explicit.value});',
    'return key===inquiryKey(draft);':
        'return settledKey===inquiryKey(draft)?{inquiryKey:settledKey}:false;',
}
HOOKS = {
    'function purchaseForm(result) {':
        'function purchaseForm(result) {\n  if(worldBinding?.simulatedOrders)return simulatedPurchaseForm(result,{state,e,link});',
    'function orderArticle(order) {':
        'function orderArticle(order) {\n  if(order.simulated)return simulatedOrderConfirmation(order,{e,money,serviceTypes});',
    'function article(id) {':
        'function article(id) {\n  const __simulatedOrders=state.orders.filter(order=>order.simulated);\n  if(worldBinding?.simulatedOrders&&id===\'orders\')return __simulatedOrders.length?`<p>Your confirmed orders:</p><ul>${__simulatedOrders.map(order=>`<li>${link(`info/order-${order.id}`,`Order ${e(order.id)} · ${e(order.date)} · Order received`)}</li>`).join(\'\')}</ul>`:\'<p>No orders have been placed in this shop.</p>\';\n  const __simulatedOrder=__simulatedOrders.find(order=>id===`order-${order.id}`);\n  if(__simulatedOrder)return orderArticle(__simulatedOrder);',
    'if(!changed||key!==worldBinding.inquiryKey(state))return;':
        'if(!changed||(worldBinding.simulatedOrders?changed.inquiryKey!==worldBinding.inquiryKey(state):key!==worldBinding.inquiryKey(state)))return;',
    "if(worldBinding){feedback='Purchase submission is unavailable.';render();return;}":
        "if(worldBinding?.simulatedOrders){await completeSimulatedOrder({state,values,result:currentQuote(),binding:worldBinding,save,goto,notify:message=>{feedback=message;render();}});return;}\n    if(worldBinding){feedback='Purchase submission is unavailable.';render();return;}",
}


def project_assets(assets, *, expected_source_sha256):
    source=assets.get('shop.js')
    if type(source) is not bytes or sha256(source).hexdigest()!=expected_source_sha256:
        raise ValueError('Simulated ordering requires the exact composed shop renderer')
    text=source.decode()
    if 'simulated-order-presentation.js' in assets or 'simulatedPurchaseForm' in text:
        raise ValueError('Simulated-order renderer has already been projected')
    for old,new in HOOKS.items():
        if text.count(old)!=1:raise ValueError('Simulated-order renderer seam changed: '+old)
        text=text.replace(old,new)
    changed=(text+IMPORT).encode()
    helper=Path(__file__).with_suffix('.js').read_bytes()
    quote=assets.get('quote.js')
    if type(quote) is not bytes or 'simulated-order-transport.js' in assets:
        raise ValueError('Simulated ordering requires the native basket quote binding')
    quote_text=quote.decode()
    for old,new in QUOTE_HOOKS.items():
        if quote_text.count(old)!=1:raise ValueError('Simulated-order quote seam changed: '+old)
        quote_text=quote_text.replace(old,new)
    changed_quote=(quote_text+QUOTE_IMPORT).encode()
    transport=Path(__file__).with_name('simulated_order_transport.js').read_bytes()
    evidence={'schema':VERSION,'before_sha256':expected_source_sha256,
        'after_sha256':sha256(changed).hexdigest(),'helper_sha256':sha256(helper).hexdigest(),
        'quote_before_sha256':sha256(quote).hexdigest(),'quote_after_sha256':sha256(changed_quote).hexdigest(),
        'transport_sha256':sha256(transport).hexdigest(),
        'qualification':'Presentation only; server record/native grading/runtime/browser acceptance required'}
    if restore_source(changed,evidence)!=source:raise ValueError('Order projection has no exact inverse')
    if restore_quote(changed_quote,evidence)!=quote:raise ValueError('Order quote projection has no exact inverse')
    return {**assets,'shop.js':changed,'quote.js':changed_quote,
            'simulated-order-presentation.js':helper,'simulated-order-transport.js':transport},evidence


def restore_source(source,evidence):
    if evidence.get('schema')!=VERSION or sha256(source).hexdigest()!=evidence['after_sha256']:
        raise ValueError('Order projection differs from pinned renderer')
    text=source.decode()
    if not text.endswith(IMPORT):raise ValueError('Order projection import changed')
    text=text[:-len(IMPORT)]
    for old,new in reversed(list(HOOKS.items())):
        if text.count(new)!=1:raise ValueError('Order inverse seam is not unique')
        text=text.replace(new,old)
    original=text.encode()
    if sha256(original).hexdigest()!=evidence['before_sha256']:
        raise ValueError('Order inverse differs from original renderer')
    return original


def restore_quote(source,evidence):
    if evidence.get('schema')!=VERSION or sha256(source).hexdigest()!=evidence['quote_after_sha256']:
        raise ValueError('Order quote projection differs from pinned binding')
    text=source.decode()
    if not text.endswith(QUOTE_IMPORT):raise ValueError('Order quote import changed')
    text=text[:-len(QUOTE_IMPORT)]
    for old,new in reversed(list(QUOTE_HOOKS.items())):
        if text.count(new)!=1:raise ValueError('Order quote inverse seam is not unique')
        text=text.replace(new,old)
    original=text.encode()
    if sha256(original).hexdigest()!=evidence['quote_before_sha256']:
        raise ValueError('Order quote inverse differs from native binding')
    return original
