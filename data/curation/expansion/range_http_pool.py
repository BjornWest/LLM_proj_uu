"""Per-worker reusable HTTP connections; no retries or shared mutable sessions."""
import threading
import requests

class RangeSessions:
    def __init__(self, factory=None):
        self.factory = factory or requests.Session
        self.local = threading.local()
        self.lock = threading.Lock()
        self.clients = []
        self.closed = False

    def __enter__(self): return self

    def client(self):
        with self.lock:
            if self.closed: raise RuntimeError('Session pool closed')
            client = getattr(self.local, 'client', None)
            if client is None:
                client = self.factory()
                # requests defaults to zero retries; enforce that invariant even
                # if its defaults change. A failed range ends the invocation.
                for adapter in client.adapters.values():
                    if adapter.max_retries.total != 0:
                        client.close()
                        raise ValueError('Automatic HTTP retries forbidden')
                self.local.client = client
                self.clients.append(client)
        return client

    def get(self, *args, **kwargs):
        client = self.client()
        # Preserve requests.get's no-cross-call-cookie behavior while reusing
        # transport connections. Redirects within one request remain unchanged.
        client.cookies.clear()
        return client.get(*args, **kwargs)

    def __exit__(self, *exc):
        with self.lock:
            self.closed = True
            clients, self.clients = self.clients, []
        for client in clients: client.close()
