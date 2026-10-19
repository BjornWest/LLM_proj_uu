"""Demo Chromium settings compatible with a human completing verification."""
import os


def demo_launch_options(**options):
    options['ignore_default_args'] = [*options.get('ignore_default_args', []), '--enable-automation']
    options['args'] = [*options.get('args', []), '--disable-blink-features=AutomationControlled']
    # RAVEN_BROWSER_DISPLAY picks the screen: the owner's display for the demo, :99 (invisible
    # Xvfb) for worker tests. Defaults to the service's own DISPLAY.
    display = os.environ.get('RAVEN_BROWSER_DISPLAY') or os.environ.get('DISPLAY') or ':99'
    options['env'] = {**os.environ, **options.get('env', {}), 'DISPLAY': display}
    return options
