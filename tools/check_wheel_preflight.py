"""Check real CI wheel naming; this cannot qualify a signed release."""
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile
from release_version import version


def validate(wheels, expected_version, standalone):
    if len(wheels) != 1:
        raise ValueError('Expected exactly one cp312 preflight wheel')
    wheel = wheels[0]
    expected_name = f'eqnedit64-{expected_version}-cp312-cp312-win_amd64.whl'
    if wheel.name != expected_name:
        raise ValueError('Wheel filename is not the normalized cp312 distribution name')
    info = f'eqnedit64-{expected_version}.dist-info/'
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        if names != [info + 'METADATA']:
            raise ValueError('Wheel dist-info name is not normalized')
        meta = BytesParser().parsebytes(archive.read(names[0]))
        if meta.get_all('Name') != ['EqnEdit64'] or meta.get_all('Version') != [expected_version]:
            raise ValueError('Wheel METADATA Name/version differs from the source contract')
        fields = BytesParser().parsebytes(archive.read(info + 'WHEEL'))
        if fields.get_all('Tag') != ['cp312-cp312-win_amd64'] or fields.get_all('Root-Is-Purelib') != ['false']:
            raise ValueError('Preflight requires a native cp312 Windows wheel')
        if 'eqnedit64/EqnEdit64.exe' not in archive.namelist() or archive.read('eqnedit64/EqnEdit64.exe') != standalone:
            raise ValueError('Wheel must embed the exact existing CI executable')
    return dict(schema='eqnedit64.wheel-name-preflight.v1', wheel_filename=wheel.name,
                dist_info=info, metadata_name='EqnEdit64', version=expected_version,
                wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
                embedded_exe_sha256=hashlib.sha256(standalone).hexdigest(),
                release_qualified=False, signature_checked=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wheel-dir', type=Path, required=True)
    p.add_argument('--standalone', type=Path, required=True)
    p.add_argument('--source-sha', required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not re.fullmatch(r'[0-9a-f]{40}', args.source_sha) or subprocess.check_output(
            ['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() != args.source_sha:
        raise ValueError('Preflight source does not match this checkout')
    result = validate(sorted(args.wheel_dir.glob('*.whl')), version(root), args.standalone.read_bytes())
    result['source_sha'] = args.source_sha
    args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('WHEEL_NAME_PREFLIGHT ' + json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
