"""Trusted runtime injection shared by suites and the website worker."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from .bindings import ROOT


@dataclass
class RuntimeContext:
    registry_path: Path
    project_root: Path = ROOT
    fixture_root: Path | None = None
    origins: dict[str, str] = field(default_factory=dict)
    # BrowserContext and private httpx reads use the same trusted proxy.
    browser_proxy: dict[str, str] | None = field(default=None, repr=False)
    # Host service owns clone/reset identity. Called before setup and grading.
    attest: Callable[[], dict] | None = None
    # Trusted, lease-bound callbacks; never expose these in tool schemas.
    state_read: Callable[[str, dict], object] | None = None
    native_grade: Callable[[int, object, Path, dict], dict] | None = None

    def origin(self, site):
        value = self.origins[site]
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username
                or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('Expected trusted application origin')
        return value.rstrip('/')

    def identity(self):
        if self.attest is None:
            raise ValueError('Dedicated instance/reset attestation is required')
        identity = self.attest()
        if not isinstance(identity, dict) or not identity.get('instance_id') or not identity.get('reset_id'):
            raise ValueError('Missing isolated instance/reset identity')
        return identity
