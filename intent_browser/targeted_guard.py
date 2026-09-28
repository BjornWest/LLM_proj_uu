"""Bounded main-document target checks against an already captured AX snapshot.

This is element/document consistency, NOT whole-page content equivalence or an
application authorization verifier. Unrelated prices/terms outside the target's
AX ancestry are not asserted unchanged. Frame targets keep the full guard path.
"""
import json
import time
from uuid import uuid4
from playwright.sync_api import Error as PlaywrightError
from .cdp_json import send_json
from .dynamic_preview import semantics
from .native_capture import CaptureDeadlineExceeded

VERSION='targeted-main-action-v1'
NO_TARGET_TOOLS=frozenset(('goto','go_back','go_forward','reload','scroll','noop','send_msg_to_user','extract_page','release_image'))


def _chain(nodes,target):
    by_id={n['nodeId']:n for n in nodes}
    parents={c:n['nodeId'] for n in nodes for c in n.get('childIds',[])}
    chain=[];seen=set();node=target
    while node is not None:
        key=node['nodeId']
        if key in seen or len(seen)>=128:raise ValueError('Unbounded target ancestry')
        seen.add(key)
        # Include ignored ancestors' DOM identity too: moving an unchanged Buy
        # button to a different product must not pass on label equality alone.
        if node.get('backendDOMNodeId') is not None and node.get('role',{}).get('value')!='RootWebArea':
            # Native temporary accessibility marking can expose structural
            # body/div ancestors as generic; unmarked partial AX calls report
            # those same ancestors as ignored/none. Their DOM identity remains
            # meaningful, but that marker-induced role transition does not.
            semantic=semantics(node)
            structural=(node is not target and not semantic['name'] and
                semantic['value'] is None and not semantic['state'] and
                (node.get('ignored') or semantic['role'] in ('none','generic')))
            chain.append({'backend_node_id':node['backendDOMNodeId'],'structural':True}
                         if structural else semantic)
        node=by_id.get(parents.get(key,node.get('parentId')))
    return chain


def check(human,ticket,observation,decision):
    """None means unsupported/fall back; a result always records check scope."""
    # Each pre-dispatch RPC, including resource cleanup, shares the existing
    # owner-thread guard deadline. Diagnostic mode observes overruns instead.
    return human._guard_operation('targeted_action',
        lambda budget: _check(human,ticket,observation,decision))


def _check(human,ticket,observation,decision):
    bid=decision.arguments.get('bid')
    if bid is None:
        if decision.name not in NO_TARGET_TOOLS:return None
        return {'version':VERSION,'reason':None,'scope':'Document/custody guarded; no element target or full-content comparison.'}
    frame=ticket.get('frame_capture',{}).get('bid_frames',{}).get(bid)
    if frame!=ticket['document']['frame_id']:return None
    nodes=observation.get('axtree_object',{}).get('nodes',[])
    matches=[n for n in nodes if n.get('browsergym_id')==bid and not n.get('ignored')]
    result={'version':VERSION,'bid':bid,'reason':None,
            'scope':'Main-document target identity/name/value/state and AX ancestor identities/names/state; not unrelated page content.'}
    def reject(reason,**extra):
        result.update(reason=reason,**extra)
        return result
    if len(matches)!=1 or matches[0].get('backendDOMNodeId') is None:
        return reject('target_missing_or_ambiguous_in_captured_observation')
    old=matches[0];page=human.env.page;cdp=None;group='intent-target-'+uuid4().hex
    started=time.monotonic()
    try:
        cdp=page.context.new_cdp_session(page)
        if page.locator('[bid='+json.dumps(bid)+']').count()!=1:
            return reject('target_bid_missing_or_ambiguous')
        remote=send_json(cdp,'DOM.resolveNode',{'backendNodeId':old['backendDOMNodeId'],'objectGroup':group})
        obj=remote.get('object',{}).get('objectId')
        if not obj:return reject('target_detached')
        live=cdp.send('Runtime.callFunctionOn',{'objectId':obj,'returnByValue':True,
            'functionDeclaration':'function(){return {connected:this.isConnected,main:this.ownerDocument===document,bid:this.getAttribute("bid")}}'})
        if live.get('exceptionDetails') or live.get('result',{}).get('value')!={'connected':True,'main':True,'bid':bid}:
            return reject('target_removed_replaced_or_bid_changed')
        current=send_json(cdp,'Accessibility.getPartialAXTree',{'backendNodeId':old['backendDOMNodeId'],'fetchRelatives':True})['nodes']
        selected=[n for n in current if n.get('backendDOMNodeId')==old['backendDOMNodeId'] and not n.get('ignored')]
        if len(selected)!=1:return reject('target_no_longer_accessible')
        result['captured_target']=semantics(old);result['live_target']=semantics(selected[0])
        if any(p['name']=='disabled' and p['value'].get('value') is True for p in selected[0].get('properties',[])):
            return reject('target_disabled')
        if _chain(nodes,old)!=_chain(current,selected[0]):
            return reject('target_or_ancestry_changed')
        return result
    except (PlaywrightError,KeyError,ValueError) as exc:
        return reject('target_check_unavailable',error=f'{type(exc).__name__}: {exc}')
    finally:
        if cdp is not None:
            try:cdp.send('Runtime.releaseObjectGroup',{'objectGroup':group})
            except (PlaywrightError,CaptureDeadlineExceeded):pass
            try:cdp.detach()
            except (PlaywrightError,CaptureDeadlineExceeded):pass
        result['seconds']=time.monotonic()-started
