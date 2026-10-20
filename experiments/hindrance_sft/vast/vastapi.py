"""Shared Vast client helper (isolated vastai 1.8.3 env). Key read from VAST_API_KEY or the project .env; never printed."""
import os, pathlib
from vastai.api.client import VastClient
from vastai.api import instances, offers, billing, keys  # noqa: F401

ENV_FILE = pathlib.Path(os.environ.get('VAST_ENV_FILE', pathlib.Path(__file__).resolve().parents[3] / '.env'))


def api_key():
    if os.environ.get('VAST_API_KEY'):
        return os.environ['VAST_API_KEY']
    return next(l.split('=', 1)[1].strip().strip('"\'') for l in ENV_FILE.read_text().splitlines()
                if l.strip().startswith('VAST_API_KEY='))

def client():
    return VastClient(api_key=api_key(), retry=2, timeout=30)

def credit(c):
    u = billing.show_user(c)
    return float(u.get('credit') or 0) + min(0.0, float(u.get('balance') or 0))
