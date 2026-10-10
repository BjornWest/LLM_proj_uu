"""Explicit sidecar version routing; old direct APIs and v1 pins stay valid."""
from . import ecosystem, rich_ecosystem, native_review_ecosystem


def producer(version):
    if version == ecosystem.VERSION:return ecosystem
    if version == rich_ecosystem.VERSION:return rich_ecosystem
    if version == native_review_ecosystem.VERSION:return native_review_ecosystem
    raise ValueError('Unknown surrounding-site version')


def options(value=None):
    raw={} if value is None else dict(value)
    # Preserve callers explicitly configuring the old two-layout pool.
    default=ecosystem.VERSION if 'comparison_layout_weights' in raw else rich_ecosystem.VERSION
    version=raw.pop('version',default)
    return {'version':version,**producer(version).options(raw)}


def generate(world,controls):
    controls=dict(controls);version=controls.pop('version')
    return producer(version).generate(world,controls)


def _generate_bound(world,controls,world_sha256):
    """Generation-only routing; public validation never accepts a cached hash."""
    controls=dict(controls);version=controls.pop('version')
    return producer(version)._generate_bound(world,controls,world_sha256)


def validate(world,sidecar):
    return producer(sidecar.get('schema_version')).validate(world,sidecar)
