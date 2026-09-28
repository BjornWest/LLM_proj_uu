import zipfile

import pytest

from scripts.verify_runtime_package import verify


def wheel(tmp_path, dependency='Jinja2<4,>=3.1', *, asset=True):
    source = tmp_path / 'observation_revision.js'
    source.write_text('/* test asset */')
    path = tmp_path / 'runtime.whl'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('intent_browser-0.1.dist-info/METADATA',
                        'Metadata-Version: 2.1\nRequires-Dist: ' + dependency + '\n')
        if asset:
            archive.writestr('intent_browser/observation_revision.js', source.read_bytes())
    return path, source


def test_complete_runtime_package(tmp_path):
    assert verify(*wheel(tmp_path))['passed']


@pytest.mark.parametrize('dependency', ['httpx>=0.27', 'Jinja2>=3.1; extra == "dev"'])
def test_missing_mandatory_dependency(tmp_path, dependency):
    with pytest.raises(ValueError, match='Jinja2'):
        verify(*wheel(tmp_path, dependency))


def test_missing_revision_asset(tmp_path):
    with pytest.raises(KeyError):
        verify(*wheel(tmp_path, asset=False))


def test_changed_revision_asset(tmp_path):
    path, source = wheel(tmp_path)
    source.write_text('/* changed */')
    with pytest.raises(ValueError, match='differs'):
        verify(path, source)
