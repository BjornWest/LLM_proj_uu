"""Native Windows demo assets and the existing WSL-to-Windows CDP transport."""
import argparse
import json
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
from urllib.request import urlopen, urlretrieve
from zipfile import ZipFile

from intent_browser.windows_browser import WindowsChrome


def windows_directory():
    local = WindowsChrome.powershell('$env:LOCALAPPDATA')
    return PureWindowsPath(local) / 'raven-demo'


def wsl_path(path):
    return Path(subprocess.check_output(['wslpath', '-u', str(path)], text=True).strip())


def prepare_browser():
    """Install CfT once; explicit setup keeps downloads outside service startup."""
    root = windows_directory()
    local = wsl_path(root)
    executable = local / 'chrome-win64/chrome.exe'
    if not executable.exists():
        local.mkdir(parents=True, exist_ok=True)
        with urlopen('https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json') as response:
            stable = json.load(response)['channels']['Stable']
        asset = next(a for a in stable['downloads']['chrome'] if a['platform'] == 'win64')
        archive = local / 'chrome-win64.zip'
        print(f'Downloading Chrome for Testing {stable["version"]} to {local}', flush=True)
        urlretrieve(asset['url'], archive)
        with ZipFile(archive) as bundle:
            bundle.extractall(local)
        archive.unlink()
        (local / 'chrome-version.json').write_text(json.dumps(stable, indent=2) + '\n')
    print(str(root / 'chrome-win64/chrome.exe'), flush=True)


def launch_browser(directory, extension, service_port, profile_dir=None):
    root = windows_directory()
    local = wsl_path(root)
    if not (local / 'chrome-win64/chrome.exe').exists():
        raise RuntimeError('Install Windows Chrome for Testing first: python3 -m apps.raven.windows_browser --setup')
    # Copy only the unpacked extension; the browser/profile never use a WSL path.
    shutil.copytree(extension, local / 'extension', dirs_exist_ok=True)
    port = int(WindowsChrome.powershell(
        '$l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0); '
        '$l.Start(); $l.LocalEndpoint.Port; $l.Stop()'))
    profile = str(profile_dir) if profile_dir else str(root / 'profiles' / str(service_port))
    # Accept both a C:\... path and a /mnt/c/... path for --profile-dir.
    if profile.startswith('/'):
        profile = subprocess.check_output(['wslpath', '-w', profile], text=True).strip()
    return WindowsChrome(directory, port, layout={}, background=False, windows_chat=False,
        executable=root / 'chrome-win64/chrome.exe', profile_dir=profile,
        extensions=[root / 'extension'], extra_args=[
            '--disable-blink-features=AutomationControlled', '--window-size=1440,1000',
            '--hide-crash-restore-bubble'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', required=True)
    parser.parse_args()
    prepare_browser()
