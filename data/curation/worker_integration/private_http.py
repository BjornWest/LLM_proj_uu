"""Private same-origin GET through the lease proxy; preserve server session cookies.

Playwright's APIRequestContext uses CONNECT for HTTP in the pinned version. This
httpx path uses ordinary HTTP proxy forwarding, independent of policy actions.
It never logs proxy credentials and never follows redirects.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit
import httpx


@dataclass
class PageRead:
    status: int
    url: str
    body: str

    def text(self):
        return self.body


def get_page(*, browser_context, origin, path, headers, proxy=None):
    if not path.startswith('/') or path.startswith('//') or '\\' in path:
        raise ValueError('Invalid private read path')
    url = origin + path
    if (urlsplit(url).scheme, urlsplit(url).netloc) != (urlsplit(origin).scheme, urlsplit(origin).netloc):
        raise ValueError('Private read escaped configured origin')
    cookies = httpx.Cookies()
    for cookie in browser_context.cookies(origin):
        cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'])
    proxy_value = None
    if proxy:
        proxy_value = httpx.Proxy(proxy['server'], auth=(proxy['username'], proxy['password']))
    with httpx.Client(proxy=proxy_value, trust_env=False, timeout=60, follow_redirects=False,
                      headers=headers, cookies=cookies) as client:
        response = client.get(url)
        # Preserve only cookies issued by this ordinary server response, not synthetic
        # login/CSRF values. Copying HTTP cookie state is part of session bootstrap.
        issued = []
        for cookie in response.cookies.jar:
            item = {'name': cookie.name, 'value': cookie.value, 'domain': cookie.domain,
                    'path': cookie.path, 'secure': cookie.secure,
                    'httpOnly': cookie.has_nonstandard_attr('HttpOnly')}
            if cookie.expires is not None:
                item['expires'] = cookie.expires
            same_site = cookie.get_nonstandard_attr('SameSite')
            if same_site and same_site.lower() in ('strict', 'lax', 'none'):
                item['sameSite'] = same_site.capitalize()
            issued.append(item)
        if issued:
            browser_context.add_cookies(issued)
        return PageRead(response.status_code, str(response.url), response.text)
