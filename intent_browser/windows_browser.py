"""Isolated Windows Chrome launcher for WSL BrowserGym sessions.

Only launcher-owned blank startup pages are closed; user browser profiles are never used.
"""
import base64, json, os, socket, subprocess, threading, time
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager

class WindowsChrome:
    def __init__(self, directory, port=19229, *, headless=False, layout=None, background=True, windows_chat=True):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")
        self.directory=Path(directory); self.port=port; self.relays=[]; self.browser=None
        self.directory.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.background = background
        self.windows_chat = windows_chat
        self.chat_chrome = None
        self._closed = False
        from .windows_layout import load_layout, validate_layout
        self.layout = load_layout() if layout is None else layout
        if self.layout:
            validate_layout(self.layout)
        self.startup_cleanup = None
        self.layout_results = []
        script=r'''
$ErrorActionPreference='Stop'
$port=PORT
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw 'Diagnostic port already occupied' }
$profile=Join-Path $env:TEMP ('browser-agent-research-'+[guid]::NewGuid().ToString('N'))
$exe='C:\Program Files\Google\Chrome\Application\chrome.exe'
$args='--user-data-dir="'+$profile+'" --no-first-run --no-default-browser-check --incognito --remote-debugging-address=127.0.0.1 --remote-debugging-port='+$port+' about:blank'
$p=Start-Process -FilePath $exe -ArgumentList $args -PassThru
@{pid=$p.Id;profile=$profile;port=$port;version=(Get-Item $exe).VersionInfo.ProductVersion;arguments=$args;enable_automation_flag=$false} | ConvertTo-Json -Compress
'''.replace('PORT',str(port))
        if background and not headless:
            script = script.replace('--incognito ', '--incognito --no-startup-window ')
        if headless:
            script = script.replace('--incognito ', '--incognito --headless=new ')
        r=self.powershell(script); self.start=json.loads(r)
        (self.directory/'windows-started.json').write_text(json.dumps(self.start,indent=2))
        self.listener=socket.socket(); self.listener.bind(('127.0.0.1',0)); self.listener.listen(8)
        self.local_port=self.listener.getsockname()[1]
        threading.Thread(target=self.accept,daemon=True).start()
        version=None
        for _ in range(20):
            try:
                version=json.loads(self.powershell(f'Invoke-RestMethod http://127.0.0.1:{port}/json/version | ConvertTo-Json -Compress'));break
            except Exception: time.sleep(.25)
        if version is None: raise RuntimeError('Windows Chrome did not expose loopback debugging')
        self.endpoint=version['webSocketDebuggerUrl'].replace(f'127.0.0.1:{port}',f'127.0.0.1:{self.local_port}').replace(f'localhost:{port}',f'127.0.0.1:{self.local_port}')
    @staticmethod
    def powershell(script):
        encoded=base64.b64encode(("$ProgressPreference='SilentlyContinue';\n" + script).encode('utf-16-le')).decode()
        r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],capture_output=True,text=True,timeout=20)
        if r.returncode: raise RuntimeError('Windows launch/transport command failed: '+r.stderr[:400])
        return r.stdout.strip().lstrip('\ufeff')
    def accept(self):
        while True:
            try: conn,_=self.listener.accept()
            except OSError: return
            threading.Thread(target=self.bridge,args=(conn,),daemon=True).start()
    def bridge(self, conn):
        script=f"$c=[System.Net.Sockets.TcpClient]::new('127.0.0.1',{self.port}); $n=$c.GetStream(); $i=[Console]::OpenStandardInput(); $o=[Console]::OpenStandardOutput(); $a=$i.CopyToAsync($n); $b=$n.CopyToAsync($o); [System.Threading.Tasks.Task]::WaitAny(@($a,$b)) | Out-Null; $c.Dispose()"
        p=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL);self.relays.append(p)
        def up():
            try:
                while data:=conn.recv(65536): p.stdin.write(data);p.stdin.flush()
            except (OSError,ValueError):pass
            finally:
                try:p.stdin.close()
                except (OSError,ValueError):pass
        threading.Thread(target=up,daemon=True).start()
        try:
            while data:=os.read(p.stdout.fileno(),65536):conn.sendall(data)
        except OSError:pass
        finally:conn.close()
    @contextmanager
    def bind_environment(self):
        # Scope BrowserGym factory bindings; each task/chat keeps a distinct browser.
        import browsergym.core.env as module
        original=module._get_global_playwright
        original_chat = module.Chat
        def chat_factory(*args, **kwargs):
            # WSLg activates even background-created windows. Native Windows chat
            # uses its own isolated profile/browser and respects background=True.
            if self.windows_chat and not kwargs.get("headless", False):
                import browsergym.core.chat as chat_module
                if self.chat_chrome is not None:
                    raise RuntimeError("One chat browser per launch")
                port = int(self.powershell("$l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0); $l.Start(); $l.LocalEndpoint.Port; $l.Stop()"))
                self.chat_chrome = WindowsChrome(self.directory / 'windows-chat', port,
                    layout={}, background=self.background, windows_chat=False)
                original_chat_factory = chat_module._get_global_playwright
                def chat_playwright():
                    pw = original_chat_factory()
                    def launch(**options):
                        from .background_pages import configure_pages
                        browser = pw.chromium.connect_over_cdp(self.chat_chrome.endpoint, timeout=20000)
                        self.chat_chrome.browser = browser
                        cleanup = StartupCleanup(browser, self.chat_chrome.directory)
                        self.chat_chrome.startup_cleanup = cleanup
                        return configure_pages(browser, background=self.background,
                                               after_page=cleanup.after_page)
                    return SimpleNamespace(chromium=SimpleNamespace(launch=launch))
                chat_module._get_global_playwright = chat_playwright
                try:
                    chat = original_chat(*args, **kwargs)
                finally:
                    chat_module._get_global_playwright = original_chat_factory
            else:
                chat = original_chat(*args, **kwargs)
            if not kwargs.get("headless", False):
                self._place(chat.page, "chat")
            return chat
        def factory():
            pw=original()
            def launch(**kwargs):
                if self.browser is not None: raise RuntimeError('One environment browser per launch')
                self.browser=pw.chromium.connect_over_cdp(self.endpoint,timeout=20000)
                self.startup_cleanup = StartupCleanup(self.browser, self.directory)
                from .background_pages import configure_pages
                def after_page(page):
                    first = not self.startup_cleanup.attempted
                    self.startup_cleanup.after_page(page)
                    if first and not self.headless:
                        self._place(page, "browser")
                configure_pages(self.browser, background=self.background and not self.headless,
                                after_page=after_page)
                return self.browser
            return SimpleNamespace(selectors=pw.selectors,chromium=SimpleNamespace(launch=launch))
        module._get_global_playwright=factory
        module.Chat = chat_factory
        try:yield self
        finally:
            module._get_global_playwright=original
            module.Chat = original_chat
    def _place(self, page, role):
        if not self.layout:
            return
        from .windows_layout import place_page
        try:
            result = place_page(page, role, self.layout, self.powershell)
        except Exception as exc:
            result = {"role": role, "placed": False, "error_type": type(exc).__name__, "detail": str(exc)[:500]}
        self.layout_results.append(result)
        (self.directory / "windows-layout-result.json").write_text(json.dumps(self.layout_results, indent=2))
    def close(self):
        # Idempotent: never signal a PID again after this owned launch has ended.
        if self._closed:
            return
        self._closed = True
        try:
            if self.chat_chrome is not None:
                self.chat_chrome.close()
                self.chat_chrome = None
        finally:
            try:
                self.powershell(f"Stop-Process -Id {int(self.start['pid'])} -ErrorAction SilentlyContinue; exit 0")
            finally:
                self.listener.close()
                for p in self.relays:
                    if p.poll() is None:
                        p.terminate()



class StartupCleanup:
    """One attempt, exact page identities, only after the replacement page exists."""

    def __init__(self, browser, directory):
        self.directory = Path(directory)
        self.pages = [page for context in browser.contexts for page in context.pages
                      if not page.is_closed() and page.url == "about:blank"]
        self.attempted = False
        self.results = []

    def after_page(self, agent_page):
        if self.attempted or agent_page.is_closed() or agent_page in self.pages:
            return
        self.attempted = True
        for page in self.pages:
            try:
                if page.is_closed():
                    outcome = "already_closed"
                elif page.url != "about:blank":
                    outcome = "retained_navigated"
                elif not page.evaluate("() => location.href === 'about:blank' && "
                                       "document.title === '' && document.body !== null && "
                                       "document.body.childNodes.length === 0"):
                    outcome = "retained_content"
                else:
                    page.close(run_before_unload=False)
                    outcome = "closed_unused_startup"
                self.results.append({"outcome": outcome})
            except Exception as exc:
                self.results.append({"outcome": "retained_error", "error_type": type(exc).__name__})
        (self.directory / "windows-startup-cleanup.json").write_text(json.dumps({
            "attempted": True, "candidates": len(self.pages), "results": self.results,
            "agent_page_open": not agent_page.is_closed(),
        }, indent=2))
