"""Assign native-compatible IDs only to viewport elements in a bounded AX preview.

This is an early proposal, not permission to act. DynamicPreview validates every
published BID against the subsequent full, stable-frame capture before dispatch.
"""
import asyncio
from uuid import uuid4
from .native_capture import SOURCE, marker_source

# Reuse the exact version-pinned BrowserGym tag whitelist and frame allocator.
marker_source()
TAGS = SOURCE[SOURCE.index('    const html_tags'):SOURCE.index('    const set_of_marks_tags')]
GENERATOR = SOURCE[SOURCE.index('class IFrameIdGenerator'):]
ASSIGN = '''function(...elements) {
''' + TAGS + GENERATOR + '''
    const first = !("browsergym_elem_counter" in window);
    // A conflicting page-supplied allocator is not repaired or trusted here.
    if (!first && (!Number.isSafeInteger(window.browsergym_elem_counter) ||
        window.browsergym_elem_counter < 0 || !window.browsergym_frame_id_generator ||
        typeof window.browsergym_frame_id_generator.next !== 'function'))
        return elements.map(() => null);
    let initialized = !first;
    return elements.map(elem => {
        if (!elem || elem.nodeType !== 1 || elem.ownerDocument !== document || !elem.isConnected)
            return null;
        // Native marking and Playwright selectors traverse open shadow roots,
        // not closed or browser-internal roots (for example input internals).
        let root = elem.getRootNode();
        while (root instanceof ShadowRoot) {
            if (root.mode !== 'open') return null;
            root = root.host.getRootNode();
        }
        if (root !== document) return null;
        const tag = elem.tagName.toLowerCase();
        if (!html_tags.has(tag) || ['iframe','frame'].includes(tag)) return null;
        const rect = elem.getBoundingClientRect(), style = getComputedStyle(elem);
        if (!rect.width || !rect.height || rect.bottom <= 0 || rect.right <= 0 ||
            rect.top >= innerHeight || rect.left >= innerWidth ||
            style.visibility !== 'visible' || style.display === 'none') return null;
        // Never adopt a site's preexisting BID on our first preparation.
        if (first && elem.hasAttribute('bid')) return null;
        if (!initialized) {
            window.browsergym_elem_counter = 0;
            window.browsergym_frame_id_generator = new IFrameIdGenerator();
            initialized = true;
        }
        let bid = elem.getAttribute('bid');
        if (bid === null) {
            if (window.browsergym_elem_counter >= Number.MAX_SAFE_INTEGER) return null;
            bid = String(window.browsergym_elem_counter++);
            elem.setAttribute('bid',bid);
        }
        // Main-document non-frame IDs use native numeric IDs only.
        return /^(0|[1-9][0-9]*)$/.test(bid) ? bid : null;
    });
}'''


def assign_preview_bids(page, cdp, nodes):
    """Resolve at most the caller's bounded preview; no whole-page DOM walk.

    Resolve references concurrently on Playwright's existing owner loop. Only
    assignment itself is a single ordered browser evaluation. Child documents,
    text/document nodes, hidden and offscreen elements do not receive IDs.
    """
    from .observation_pipeline import ObservationChanged
    group = 'intent-preview-' + uuid4().hex
    candidates = list(dict.fromkeys(n['backendDOMNodeId'] for n in nodes
        if not n.get('ignored') and n.get('backendDOMNodeId') is not None and n.get('role',{}).get('value')
        not in ('RootWebArea','StaticText','InlineTextBox','Iframe','IframePresentational')))
    if not candidates:return {}
    async def resolve_all():
        semaphore=asyncio.Semaphore(8)
        async def resolve(node):
            async with semaphore:
                return await cdp._impl_obj.send('DOM.resolveNode',
                    {'backendNodeId':node,'objectGroup':group})
        # Wait for every started resolution before releasing its object group.
        return await asyncio.gather(*(resolve(n) for n in candidates),return_exceptions=True)
    try:
        results=page._sync(resolve_all())
        for result in results:
            if isinstance(result,BaseException):
                raise ObservationChanged('Preview element detached or document changed during ID resolution') from result
        objects=[r.get('object',{}).get('objectId') for r in results]
        if not all(objects):raise ObservationChanged('Preview DOM reference unavailable')
        result=cdp.send('Runtime.callFunctionOn',{'objectId':objects[0],
            'functionDeclaration':ASSIGN,'arguments':[{'objectId':o} for o in objects],
            'returnByValue':True})
        if result.get('exceptionDetails'):raise ObservationChanged('Preview ID assignment failed')
        bids=result.get('result',{}).get('value')
        if not isinstance(bids,list) or len(bids)!=len(candidates):
            raise ObservationChanged('Invalid preview ID assignment result')
        return {node:bid for node,bid in zip(candidates,bids) if isinstance(bid,str)}
    finally:
        # Cleanup must not replace an already-raised document-race exception.
        import sys
        failing=sys.exc_info()[0] is not None
        try:cdp.send('Runtime.releaseObjectGroup',{'objectGroup':group})
        except Exception:
            if not failing:raise
