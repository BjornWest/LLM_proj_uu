"""Checkout-relative Raven locations, overridable by environment (portable to other PCs).

RAVEN_ENV_FILE    secrets file           default <checkout>/.env, else the main checkout's .env
RAVEN_VENV        virtualenv directory   default <checkout>/.venv, else the main checkout's .venv
RAVEN_CAU_PATH    common_agent_util      default this workstation's pinned checkout if present,
                                         else a sibling ../common_agent_util
RAVEN_SYSTEM_LIBS extra Chromium libs    only used when the directory exists (sudo-less installs)

"Main checkout" is the repository a linked Git worktree belongs to, so worktrees reuse it.
`python3 -m apps.raven.paths --shell` prints the values as shell exports (stdlib only).
"""
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]


def _main_checkout():
    marker = ROOT / '.git'
    if marker.is_file():  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
        text = marker.read_text().strip()
        if text.startswith('gitdir:'):
            gitdir = (ROOT / text.split(':', 1)[1].strip()).resolve()
            if gitdir.parent.name == 'worktrees':
                return gitdir.parent.parent.parent
    return ROOT


MAIN = _main_checkout()


def _pick(variable, *candidates):
    if os.environ.get(variable):
        return Path(os.environ[variable]).expanduser()
    return next((path for path in candidates if path.exists()), candidates[0])


ENV_FILE = _pick('RAVEN_ENV_FILE', ROOT / '.env', MAIN / '.env')
VENV = _pick('RAVEN_VENV', ROOT / '.venv', MAIN / '.venv')
PYTHON = VENV / 'bin/python'
CAU = _pick('RAVEN_CAU_PATH', Path('/home/bjorn/code/cau-merge-20261016'),
            ROOT.parent / 'common_agent_util', MAIN.parent / 'common_agent_util')
_LIBS = '.local/system-libs/usr/lib/x86_64-linux-gnu'
SYSTEM_LIBS = _pick('RAVEN_SYSTEM_LIBS', ROOT / _LIBS, MAIN / _LIBS)


def child_environment(env):
    """PYTHONPATH/LD_LIBRARY_PATH additions for the service; libs only if present."""
    env = dict(env)
    env['PYTHONPATH'] = os.pathsep.join(p for p in [str(ROOT), str(CAU), env.get('PYTHONPATH', '')] if p)
    if SYSTEM_LIBS.is_dir():
        env['LD_LIBRARY_PATH'] = os.pathsep.join(
            p for p in [str(SYSTEM_LIBS), env.get('LD_LIBRARY_PATH', '')] if p)
    return env


if __name__ == '__main__':
    if sys.argv[1:] != ['--shell']:
        sys.exit('usage: python3 -m apps.raven.paths --shell')
    env = child_environment({k: os.environ.get(k, '') for k in ('PYTHONPATH', 'LD_LIBRARY_PATH')})
    for name, value in [('RAVEN_PYTHON', PYTHON), ('RAVEN_ENV_FILE', ENV_FILE), ('RAVEN_CAU_PATH', CAU),
                        ('PYTHONPATH', env['PYTHONPATH']), ('LD_LIBRARY_PATH', env.get('LD_LIBRARY_PATH', ''))]:
        print(f'export {name}={shlex.quote(str(value))}')
