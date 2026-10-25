"""Guards: reviewed release commands cannot mask failure; assumes reviewed allowlist."""
import copy
import json
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOW = json.loads((ROOT / 'tests/fixtures/release-run-allowlist.json').read_text('utf-8'))
PREFLIGHT = '''python tools/check_wheel_preflight.py --wheel-dir python/dist --standalone build_cmake/Release/EqnEdit64.exe --source-sha $env:GITHUB_SHA --report "$env:RUNNER_TEMP/eqnedit64-wheel-name-preflight.json"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }'''


def normalize(text):
    return '\n'.join(line.rstrip() for line in text.replace('\r\n', '\n').strip().split('\n'))


def no_error_override(value):
    if isinstance(value, dict):
        assert 'continue-on-error' not in value, 'Error overrides are forbidden'
        for item in value.values(): no_error_override(item)
    elif isinstance(value, list):
        for item in value: no_error_override(item)


def release_contract(data):
    no_error_override(data)
    jobs = data['jobs']
    assert {j: v.get('if') for j,v in jobs.items()} == ALLOW['job_if'], 'Unreviewed job condition'
    for name, job in jobs.items():
        assert all('if' not in s for s in job['steps']), 'Release steps must be unconditional'
        runs = [{'name': s.get('name'), 'run': normalize(s['run'])} for s in job['steps'] if 'run' in s]
        expected = [{'name': s['name'], 'run': normalize(s['run'])} for s in ALLOW['runs'][name]]
        assert runs == expected, 'Release commands/order differ from the reviewed allowlist'


def preflight_contract(data):
    no_error_override(data)
    job = data['jobs']['build-test']
    assert 'if' not in job, 'Preflight job must not be conditional'
    steps = [s for s in job['steps'] if s.get('name') == 'Verify actual cp312 wheel naming before installation']
    assert len(steps) == 1, 'Exactly one preflight is required'
    assert 'if' not in steps[0], 'Preflight must be unconditional'
    assert normalize(steps[0]['run']) == normalize(PREFLIGHT), 'Preflight commands differ from the reviewed allowlist'


def load(filename):
    return yaml.load((ROOT / '.github/workflows' / filename).read_text('utf-8'), Loader=yaml.BaseLoader)


def test_reviewed_workflows_pass_exact_allowlists():
    release_contract(load('release-eqnedit64-pypi.yml'))
    preflight_contract(load('eqnedit64.yml'))


@pytest.mark.parametrize('kind', ['cancelled', 'success-failure', 'exit', 'or-exit', 'or-echo',
    'set-plus-e', 'colon', 'pwsh-exit', 'preflight-continue', 'preflight-if', 'preflight-exit'])
def test_previous_bypasses_fail_and_restored_workflow_passes(kind):
    is_preflight = kind.startswith('preflight-')
    original = load('eqnedit64.yml' if is_preflight else 'release-eqnedit64-pypi.yml')
    contract = preflight_contract if is_preflight else release_contract
    contract(original)
    data = copy.deepcopy(original)
    if is_preflight:
        step = next(s for s in data['jobs']['build-test']['steps'] if s.get('name') == 'Verify actual cp312 wheel naming before installation')
        if kind == 'preflight-continue': step['continue-on-error'] = 'true'
        elif kind == 'preflight-if': step['if'] = 'false'
        else: step['run'] += '\nexit 0'
    elif kind in ('cancelled', 'success-failure'):
        data['jobs']['publish']['if'] = '!cancelled()' if kind == 'cancelled' else 'success() || failure()'
    else:
        step = next(s for s in data['jobs']['publish']['steps'] if '--report postapproval-qualification.json' in s.get('run',''))
        suffix = {'exit': '; exit 0', 'or-exit': ' || exit 0', 'or-echo': ' || echo ignored',
                  'colon': ' || :', 'pwsh-exit': '\npwsh -Command "exit 0"'}
        if kind == 'set-plus-e': step['run'] = 'set +e\n' + step['run'] + '\nexit 0'
        else: step['run'] += suffix[kind]
    with pytest.raises(AssertionError): contract(data)
    contract(original)
