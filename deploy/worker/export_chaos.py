"""Export an already prepared Chaos build and cached dependencies without downloads."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    """Describe materialized files; reject escaping links, cycles and special files."""
    root = root.resolve(strict=True)
    result = {}

    def visit(directory, relative, ancestors):
        resolved = directory.resolve(strict=True)
        if resolved in ancestors:
            raise ValueError(f'Symlink directory cycle at {relative}')
        for path in sorted(directory.iterdir()):
            target = path.resolve(strict=True)
            if not target.is_relative_to(root):
                raise ValueError(f'Symlink escapes its copied tree: {relative / path.name}')
            name = relative / path.name
            if target.is_dir():
                visit(path, name, ancestors | {resolved})
            elif target.is_file():
                result[name.as_posix()] = digest(path)
            else:
                raise ValueError(f'Unsupported special file: {name}')

    visit(root, Path(), set())
    return result


def export(source, output):
    # lexists intentionally rejects dangling output symlinks before reading inputs.
    output = Path(os.path.abspath(output))
    if os.path.lexists(output):
        raise FileExistsError(f'Output already exists; refusing to overwrite: {output}')
    source = Path(source).resolve(strict=True)
    dependencies = (source / 'node_modules').resolve(strict=True)
    if output.resolve().is_relative_to(source) or output.resolve().is_relative_to(dependencies):
        raise ValueError('Output must be outside the source build and dependency cache')
    package = json.loads((source / 'package.json').read_text())
    manifest = json.loads((source / 'dist/intent-repair.json').read_text())
    if package.get('name') != 'browser-agent-chaos' or not manifest.get('derived_files_sha256'):
        raise ValueError('Source must be an existing prepared Chaos repair build')
    dist = inventory(source / 'dist')
    for name, expected in manifest['derived_files_sha256'].items():
        if dist.get(name) != expected:
            raise ValueError(f'Prepared build does not match its own manifest: {name}')
    package_hash = digest(source / 'package.json')
    dependency_files = inventory(dependencies)
    if not dependency_files:
        raise ValueError('Dependency cache is empty')

    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Exclusive creation: also protects against a competing exporter.
    # Leave a failed partial export for inspection; it will never be overwritten.
    shutil.copy2(source / 'package.json', output / 'package.json')
    shutil.copytree(source / 'dist', output / 'dist', symlinks=False)
    shutil.copytree(dependencies, output / 'node_modules', symlinks=False)
    for name in ('LICENSE', 'README.md'):
        if (source / name).is_file():
            shutil.copy2(source / name, output / name)
    if (digest(output / 'package.json') != package_hash or
            inventory(output / 'dist') != dist or
            inventory(output / 'node_modules') != dependency_files):
        raise ValueError('Copied bytes differ from the inspected source snapshot')
    if (digest(source / 'package.json') != package_hash or
            inventory(source / 'dist') != dist or
            inventory(dependencies) != dependency_files):
        raise ValueError('Source changed during export; exported copy is not accepted')
    report = {
        'schema_version': 1, 'source': str(source), 'output': str(output),
        'dependency_cache': str(dependencies),
        'package_sha256': package_hash, 'dist_files_sha256': dist,
        'dependency_files_sha256': dependency_files,
        'materialized_dependency_links': True, 'source_unchanged': True,
        'copied_state_or_server_records': False, 'downloads': 0,
        'readiness': False,
        'scope': 'Exact local copy only. Run container-side certification before offering Chaos.',
    }
    with (output / 'export-report.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = export(args.source, args.output)
    print(json.dumps({'output': result['output'], 'package_sha256': result['package_sha256'],
                      'dist_files': len(result['dist_files_sha256']),
                      'dependency_files': len(result['dependency_files_sha256']),
                      'source_unchanged': True, 'readiness': False, 'downloads': 0}))


if __name__ == '__main__':
    main()
