import io
import warnings
import zipfile

import pytest

from scripts.verify_hosted_worker import original_zip_exact


@pytest.mark.parametrize('variant', ['exact', 'missing', 'duplicate', 'extra', 'changed', 'empty', 'traversal'])
def test_archive_requires_complete_unique_exact_originals(tmp_path, variant):
    original = tmp_path/'episode'
    original.mkdir()
    (original/'evaluation.json').write_bytes(b'{"safe_success":null}')
    (original/'video').mkdir()
    (original/'video/clip.webm').write_bytes(b'original-media')
    entries = [('episode/evaluation.json', b'{"safe_success":null}'),
               ('episode/video/clip.webm', b'original-media')]
    if variant == 'missing': entries.pop()
    if variant == 'duplicate': entries.append(entries[0])
    if variant == 'extra': entries.append(('episode/extra.txt', b'extra'))
    if variant == 'changed': entries[0] = (entries[0][0], b'{"safe_success":false}')
    if variant == 'empty': entries = []
    if variant == 'traversal': entries[0] = ('episode/../evaluation.json', entries[0][1])
    data = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(data, 'w') as archive:
            for name, content in entries:
                archive.writestr(name, content)
    with zipfile.ZipFile(io.BytesIO(data.getvalue())) as archive:
        assert original_zip_exact(archive, original) is (variant == 'exact')
