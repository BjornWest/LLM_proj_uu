"""Create Chromium pages in the background without changing their browser context.

CDP context IDs are discovered through public protocol calls. Restrict this wrapper
to launcher-owned browsers; concurrent context creation by other CDP clients is
rejected rather than guessing which isolated context belongs to the caller.
"""


def configure_pages(browser, *, background=True, after_page=None):
    original_context = browser.new_context
    session = browser.new_browser_cdp_session() if background else None

    def new_context(*args, **kwargs):
        before = set(session.send('Target.getBrowserContexts')['browserContextIds']) if session else set()
        context = original_context(*args, **kwargs)
        if session:
            after = set(session.send('Target.getBrowserContexts')['browserContextIds'])
            created = after - before
            if len(created) != 1:
                context.close()
                raise RuntimeError('Cannot identify the new isolated browser context')
            context_id = created.pop()
        original_page = context.new_page

        def new_page(*args, **kwargs):
            if session:
                if args or kwargs:
                    raise TypeError('BrowserContext.new_page takes no arguments')
                with context.expect_page() as event:
                    session.send('Target.createTarget', {
                        'url': 'about:blank', 'browserContextId': context_id,
                        'background': True,
                    })
                page = event.value
            else:
                page = original_page(*args, **kwargs)
            if after_page:
                after_page(page)
            return page

        context.new_page = new_page
        return context

    browser.new_context = new_context
    return browser
