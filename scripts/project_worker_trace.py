"""Project an authenticated worker archive with the pinned shared adapter.

No browser actions, grading, model access or source rewriting. The caller owns
archive authorization; archive contents never choose executable code or paths.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from urllib.parse import unquote
import zipfile

VENDOR = Path(__file__).resolve().parents[1] / 'deploy/daylight/vendor'
MAX_TOTAL = 512 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def project(archive, output):
    provenance = json.loads((VENDOR / 'agent_trace/projection-provenance.json').read_text())
    for name, digest in provenance['files'].items():
        if sha((VENDOR / 'agent_trace' / name).read_bytes()) != digest:
            raise ValueError('Shared projection source changed')
    sys.path.insert(0, str(VENDOR))
    from agent_trace.adapters import browsergym
    output = Path(output)
    output.mkdir()  # Exclusive: a partial/previous derivative is never overwritten.
    with tempfile.TemporaryDirectory(prefix='worker-trace-') as scratch:
        scratch = Path(scratch)
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if not entries or len(entries) > 10000:
                raise ValueError('Invalid archive member count')
            seen, roots, total = set(), set(), 0
            for entry in entries:
                name = entry.filename
                parts = name.split('/')
                if ('\\' in name or '\x00' in name or any(p in ('', '.', '..') for p in parts)
                        or len(parts) < 2 or not re.fullmatch(r'[A-Za-z0-9_-]+', parts[0])
                        or PurePosixPath(name).is_absolute() or name in seen):
                    raise ValueError('Unsafe or duplicate archive path')
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                    raise ValueError('Only regular files are accepted')
                if entry.flag_bits & 1 or entry.file_size > MAX_FILE:
                    raise ValueError('Encrypted or oversized archive member')
                total += entry.file_size
                if total > MAX_TOTAL:
                    raise ValueError('Archive exceeds expansion limit')
                seen.add(name)
                roots.add(parts[0])
            if len(roots) != 1:
                raise ValueError('Archive must contain exactly one episode')
            for entry in entries:
                target = scratch / entry.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as out, zipped.open(entry) as source:
                    count = 0
                    while data := source.read(1024 * 1024):
                        count += len(data)
                        if count > entry.file_size:
                            raise ValueError('Archive size mismatch')
                        out.write(data)
                    if count != entry.file_size:
                        raise ValueError('Archive size mismatch')
        directory = scratch / next(iter(roots))
        metadata = json.loads((directory / 'metadata.json').read_text())
        if metadata.get('episode_id') != directory.name:
            raise ValueError('Episode identity mismatch')
        def emit_projection(directory, output):
            session = browsergym.project(directory, artifact_prefix=str(directory.relative_to(scratch)))
            if not session:
                raise ValueError('Not a BrowserGym trace')
            assets, files = {}, {}

            def write(name, raw):
                path = output / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                files[name] = {'sha256': sha(raw), 'bytes': len(raw)}

            for message in session['messages']:
                for attachment in message.get('attachments', []):
                    url = attachment['url']
                    if not url.startswith('/artifacts/'):
                        raise ValueError('Unexpected shared projection asset')
                    file, mime = browsergym.asset(scratch, unquote(url.removeprefix('/artifacts/')))
                    raw = file.read_bytes()
                    name = 'assets/' + sha(raw)
                    if name not in files:
                        write(name, raw)
                    assets[url] = {'path': name, 'mime_type': mime, **files[name]}
            write('session.json', json.dumps(session, ensure_ascii=False).encode())
            write('assets.json', json.dumps(assets).encode())
            # Prefer the worker's post-close authoritative evaluation when retained.
            evaluation_file = directory / 'authoritative-evaluation.json'
            if not evaluation_file.exists():
                evaluation_file = directory / 'evaluation.json'
            evaluation = json.loads(evaluation_file.read_text()) if evaluation_file.exists() else None
            if evaluation_file.name == 'authoritative-evaluation.json' and isinstance(evaluation, dict):
                evaluation = evaluation.get('evaluation')
            manifest = {'schema_version': 1, 'kind': 'browsergym-saved-replay-v1',
                        'read_only': True, 'grader_recomputed': False,
                        'viewer_session_id': session['id'], 'raw_outcomes': evaluation,
                        'archive_sha256': sha(Path(archive).read_bytes()),
                        'projection_source': provenance, 'files': files}
            (output / 'manifest.json').write_text(json.dumps(manifest))
            return session['id']

        root_id = emit_projection(directory, output)
        members = {root_id: '.'}
        children = sorted([*directory.glob('children/*/metadata.json'),
                           *directory.glob('children/*/children/*/metadata.json')])
        if len(children) > 150:
            raise ValueError('Too many nested conversations')
        for metadata_path in children:
            child = metadata_path.parent
            metadata = json.loads(metadata_path.read_text())
            if metadata.get('episode_id') != child.name:
                raise ValueError('Nested episode identity mismatch')
            member_id = hashlib.sha256(('browsergym:' + child.name).encode()).hexdigest()[:20]
            if member_id in members:
                raise ValueError('Duplicate nested episode identity')
            destination = output / 'family' / member_id
            destination.mkdir(parents=True)
            if emit_projection(child, destination) != member_id:
                raise ValueError('Nested projection identity mismatch')
            members[member_id] = 'family/' + member_id
        (output / 'family.json').write_text(json.dumps({'root': root_id, 'members': members}))



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    project(args.archive, args.output)
