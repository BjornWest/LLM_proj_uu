"""Demo Chromium settings compatible with a human completing verification."""
import os


def demo_launch_options(**options):
    options['ignore_default_args'] = [*options.get('ignore_default_args', []), '--enable-automation']
    options['args'] = [*options.get('args', []), '--disable-blink-features=AutomationControlled']
    options['env'] = {**os.environ, **options.get('env', {}), 'DISPLAY': ':99'}
    return options
