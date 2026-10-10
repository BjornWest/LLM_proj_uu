"""Empty browser landing for tool-based website discovery."""


def page():
    # This is an address field, not a synthetic search engine. The harness's
    # discover_sites tool supplies public site search and scope descriptions.
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>New tab</title><style>body{margin:0;background:#fff;'
            'font:16px system-ui}form{max-width:620px;margin:18vh auto;padding:24px}'
            'input{box-sizing:border-box;width:100%;padding:14px 20px;'
            'border:1px solid #dadce0;border-radius:24px;font:inherit}'
            '</style></head><body><form id="address"><input type="url"'
            ' name="url" aria-label="Address bar" placeholder="Enter website address"'
            ' autocomplete="off" required></form><script src="/discovery-start.js"></script></body></html>')


def script():
    """Same-origin script works with the runtime's existing script-src policy."""
    return ('document.getElementById("address").addEventListener("submit",event=>{'
            'event.preventDefault();const url=new URL(event.target.elements.url.value);'
            'if(url.protocol==="http:"||url.protocol==="https:")location.assign(url.href);'
            '});')
