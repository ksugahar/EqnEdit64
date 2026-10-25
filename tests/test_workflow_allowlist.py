"""Guards: reviewed release commands cannot mask failure; assumes reviewed allowlist."""
import copy
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOW = yaml.load((ROOT / 'tests/fixtures/release-run-allowlist.yml').read_text('utf-8'), Loader=yaml.BaseLoader)


def normalize(text):
    return '\n'.join(line.rstrip() for line in text.replace('\r\n', '\n').strip().split('\n'))


def no_error_override(value):
    if isinstance(value, dict):
        assert 'continue-on-error' not in value, 'Error overrides are forbidden'
        for item in value.values(): no_error_override(item)
    elif isinstance(value, list):
        for item in value: no_error_override(item)


def normalized_context(value):
    if isinstance(value, dict):
        return {key: normalize(item) if key == 'run' and isinstance(item, str)
                else normalized_context(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized_context(item) for item in value]
    return value


def no_global_context(data):
    assert 'defaults' not in data and 'env' not in data, 'Global execution overrides are forbidden'
    no_error_override(data)


def release_contract(data):
    no_global_context(data)
    assert normalized_context(data['jobs']) == normalized_context(ALLOW['release_jobs']), 'Release jobs/steps differ from the reviewed execution context'


def preflight_contract(data):
    no_global_context(data)
    job = data['jobs']['build-test']
    assert normalized_context({k:v for k,v in job.items() if k != 'steps'}) == normalized_context(ALLOW['preflight_job_context']), 'Preflight job context differs'
    steps = [s for s in job['steps'] if s.get('name') == 'Verify actual cp312 wheel naming before installation']
    assert len(steps) == 1, 'Exactly one preflight is required'
    assert normalized_context(steps[0]) == normalized_context(ALLOW['preflight_step']), 'Preflight execution context differs'


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


@pytest.mark.parametrize('kind', ['shell', 'path', 'checkout-ref', 'action-sha',
    'global-env', 'global-defaults', 'job-defaults', 'job-env', 'permissions', 'needs',
    'environment', 'working-directory', 'preflight-shell', 'preflight-env', 'preflight-job'])
def test_execution_context_bypasses_rejected_and_restored(kind):
    preflight = kind.startswith('preflight-')
    original = load('eqnedit64.yml' if preflight else 'release-eqnedit64-pypi.yml')
    contract = preflight_contract if preflight else release_contract
    contract(original)
    data = copy.deepcopy(original)
    job = data['jobs']['build-test' if preflight else 'qualify']
    step = next(s for s in job['steps'] if 'check_wheel_preflight.py' in s.get('run','')) if preflight else next(s for s in job['steps'] if s.get('name','').startswith('Bind exact CI context'))
    if kind in ('shell', 'preflight-shell'): step['shell'] = 'bash {0}'
    elif kind in ('path', 'preflight-env'): step['env'] = {'PATH': './bin'}
    elif kind == 'checkout-ref':
        next(s for s in data['jobs']['publish']['steps'] if s.get('uses','').startswith('actions/checkout@')).setdefault('with',{})['ref'] = 'main'
    elif kind == 'action-sha':
        next(s for s in data['jobs']['publish']['steps'] if s.get('uses','').startswith('pypa/'))['uses'] = 'pypa/gh-action-pypi-publish@' + '0' * 40
    elif kind == 'global-env': data['env'] = {'PATH': './bin'}
    elif kind == 'global-defaults': data['defaults'] = {'run': {'shell': 'bash {0}'}}
    elif kind == 'job-defaults': job['defaults'] = {'run': {'shell': 'bash {0}'}}
    elif kind in ('job-env', 'preflight-job'): job['env'] = {'PATH': './bin'}
    elif kind == 'permissions': job['permissions'] = {'contents': 'write'}
    elif kind == 'needs': data['jobs']['publish']['needs'] = ['qualify']
    elif kind == 'environment': data['jobs']['publish']['environment'] = 'other'
    else: step['working-directory'] = './other'
    with pytest.raises(AssertionError): contract(data)
    contract(original)
