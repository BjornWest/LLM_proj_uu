"""Explicitly install only a registered model's pinned tokenizer assets."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model')
    parser.add_argument('--assets-root', type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    registry = json.loads((project / 'intent_browser/model_tokenizers.json').read_text())
    entry = registry['models'][args.model]
    root = args.assets_root or project / '.local/model-tokenizers'
    root.mkdir(parents=True, exist_ok=True)
    destination = root / entry['bundle']
    if destination.exists():
        for name, row in entry['files'].items():
            path = destination / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('Existing tokenizer assets differ; will not overwrite: ' + str(path))
        print(json.dumps({'status': 'already_installed', 'model': args.model, 'path': str(destination)}))
        return
    with tempfile.TemporaryDirectory(prefix='tokenizer-', dir=root) as temporary:
        staging = Path(temporary)
        for name, row in entry['files'].items():
            url = f"https://huggingface.co/{entry['repository']}/resolve/{entry['revision']}/{name}"
            raw = urllib.request.urlopen(url, timeout=60).read()
            if hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('Official tokenizer asset digest differs: ' + name)
            (staging / name).write_bytes(raw)
        (staging / 'manifest.json').write_text(json.dumps({'model': args.model, **entry}, indent=2) + '\n')
        staging.rename(destination)
    print(json.dumps({'status': 'installed', 'model': args.model, 'path': str(destination), 'weights_downloaded': False}))


if __name__ == '__main__':
    main()
