"""V2 establishes the benchmark's authenticated session before its original start URL.
No CSRF bypass, cookie injection, form-key modification or application source change.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];sys.path.insert(0,str(ROOT))
from data.curation.expansion.webarena_wishlist import run as base
from browsergym.core.task import OpenEndedTask
from urllib.parse import urlsplit

class SessionWishlistTask(base.WishlistTask):
 def prepare(self,trace):self.trace=trace;return super().prepare(trace)
class SessionBrowserTask(base.BrowserTask):
 def setup(self,page):
  page.context.route('**/*',lambda r:r.continue_()if urlsplit(r.request.url).netloc=='localhost:17770'else r.abort())
  url=base.ORIGIN+'/customer/account/'
  response=page.context.request.get(url,timeout=60000,max_redirects=0)
  html=response.text();cookies=page.context.cookies(base.ORIGIN)
  (self.adapter.trace.directory/'privileged-session-setup.html').write_text(html)
  proof={'url':url,'status':response.status,'html_sha256':base.sha(self.adapter.trace.directory/'privileged-session-setup.html'),'cookie_names':sorted({c['name']for c in cookies}),'purpose':'Establish original authenticated fixture account using unmodified original account GET, before original task start; no policy action or state-changing request','original_start_url':self.adapter.start_url}
  base.dump(self.adapter.trace.directory/'privileged-session-setup.json',proof)
  assert response.status==200 and 'PHPSESSID'in proof['cookie_names'],'Authenticated session bootstrap failed'
  return OpenEndedTask.setup(self,page)
base.WishlistTask=SessionWishlistTask;base.BrowserTask=SessionBrowserTask
if __name__=='__main__':base.main()
