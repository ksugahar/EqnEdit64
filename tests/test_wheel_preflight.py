"""Guards: real CI wheel naming and payload identity; assumes ZIP integrity checks."""
import importlib.util
from pathlib import Path
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wheel_preflight', ROOT / 'tools/check_wheel_preflight.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def fixture(tmp_path, mutation=''):
    name = 'eqnedit64-3.1.8-cp312-cp312-win_amd64.whl'
    info = 'eqnedit64-3.1.8.dist-info/'
    if mutation == 'filename': name = name.replace('eqnedit64', 'EqnEdit64')
    if mutation == 'directory': info = info.replace('eqnedit64', 'EqnEdit64')
    metadata = 'Name: EqnEdit64\nVersion: 3.1.8\n'
    if mutation == 'name': metadata = metadata.replace('EqnEdit64', 'eqnedit64')
    if mutation == 'version': metadata = metadata.replace('3.1.8', '3.1.7')
    fields = 'Tag: cp312-cp312-win_amd64\nRoot-Is-Purelib: false\n'
    if mutation == 'abi': fields = fields.replace('cp312', 'cp311')
    wheel = tmp_path / name
    with zipfile.ZipFile(wheel, 'w') as z:
        z.writestr(info + 'METADATA', metadata)
        z.writestr(info + 'WHEEL', fields)
        z.writestr('eqnedit64/EqnEdit64.exe', b'other' if mutation == 'payload' else b'fixture-only')
    return wheel


def test_normalized_real_wheel_contract(tmp_path):
    report = gate.validate([fixture(tmp_path)], '3.1.8', b'fixture-only')
    assert report['metadata_name'] == 'EqnEdit64'
    assert report['release_qualified'] is False and report['signature_checked'] is False


@pytest.mark.parametrize('mutation', ['filename', 'directory', 'name', 'version', 'abi', 'payload', 'multiple', 'missing'])
def test_wheel_contract_rejects_mismatch(tmp_path, mutation):
    wheel = fixture(tmp_path, mutation)
    wheels = [] if mutation == 'missing' else [wheel, wheel] if mutation == 'multiple' else [wheel]
    with pytest.raises(ValueError): gate.validate(wheels, '3.1.8', b'fixture-only')


def test_existing_build_is_verified_before_install_and_upload():
    import yaml
    data = yaml.load((ROOT / '.github/workflows/eqnedit64.yml').read_text('utf-8'), Loader=yaml.BaseLoader)
    steps = data['jobs']['build-test']['steps']
    build = next(i for i,s in enumerate(steps) if 'python -m build --wheel python' in s.get('run',''))
    verify = next(i for i,s in enumerate(steps) if 'check_wheel_preflight.py' in s.get('run',''))
    install = next(i for i,s in enumerate(steps) if 'python python\\tests\\verify_installed.py' in s.get('run',''))
    assert build < verify < install
    assert '--source-sha $env:GITHUB_SHA' in steps[verify]['run']
    assert '--standalone build_cmake/Release/EqnEdit64.exe' in steps[verify]['run']
