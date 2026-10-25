"""Guards: exact tag/CI provenance before approval; assumes GitHub GET integrity."""
import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_qualification", ROOT / "tools/qualify_release.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def fixtures():
    env = dict(GITHUB_REF="refs/tags/v3.1.8", GITHUB_REF_TYPE="tag", GITHUB_EVENT_NAME="workflow_dispatch",
               GITHUB_SHA="a" * 40, EXPECTED_SOURCE_SHA="a" * 40, CI_RUN_ID="42", GITHUB_REPOSITORY="example/editor")
    prefix = "repos/example/editor/"
    responses = {prefix + "git/ref/tags/v3.1.8": {"object": {"type": "commit", "sha": "a" * 40}},
                 prefix + "actions/runs/42": {"id": 42, "repository": {"full_name": "example/editor"},
                    "head_repository": {"full_name": "example/editor"}, "path": ".github/workflows/eqnedit64.yml",
                    "event": "push", "status": "completed", "conclusion": "success", "head_sha": "a" * 40, "run_attempt": 1},
                 prefix + "actions/runs/42/attempts/1/jobs?per_page=100": {"total_count": 3, "jobs": [
                     {"name": name, "status": "completed", "conclusion": "success"} for name in ("source-contracts", "web", "build-test")]},
                 prefix + "actions/runs/42/artifacts?per_page=100": {"total_count": 1, "artifacts": [
                     {"name": "eqnedit64-ci-release-context", "expired": False, "id": 7}]}}
    context = dict(schema="eqnedit64.ci-release-context.v1", repository="example/editor", sha="a" * 40,
                   run_id="42", ref=env["GITHUB_REF"], ref_type="tag")
    return env, responses, context


def test_exact_tag_ci_and_context_pass():
    env, responses, context = fixtures()
    result = gate.qualify(env, responses.__getitem__, context)
    assert result == dict(sha="a" * 40, tag="v3.1.8", ci_run_id="42", ci_run_attempt=1, context_artifact_id=7)


@pytest.mark.parametrize("key,value", [("GITHUB_REF", "refs/heads/main"), ("GITHUB_REF", "refs/heads/v3.1.8"),
    ("GITHUB_REF_TYPE", "branch"), ("GITHUB_EVENT_NAME", "workflow_run"), ("EXPECTED_SOURCE_SHA", "b"*40),
    ("CI_RUN_ID", "42; echo injected"), ("GITHUB_REF", "refs/tags/v3.1.8-rc1")])
def test_invalid_actual_dispatch_fails_before_get(key, value):
    env, _, _ = fixtures(); env[key] = value
    calls = []
    with pytest.raises(ValueError): gate.qualify(env, lambda path: calls.append(path))
    assert calls == []


def test_actual_workflow_entry_guard_rejects_non_tag_dispatch():
    data = yaml.safe_load((ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text("utf-8"))
    step = data["jobs"]["qualify"]["steps"][0]
    script = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    good, _, _ = fixtures()
    for patch, expected in [({}, 0), ({"GITHUB_REF": "refs/heads/main"}, 1),
                            ({"GITHUB_REF": "refs/heads/v3.1.8", "GITHUB_REF_TYPE": "branch"}, 1),
                            ({"EXPECTED_SOURCE_SHA": "b"*40}, 1), ({"CI_RUN_ID": "not-a-run"}, 1)]:
        result = subprocess.run([sys.executable, "-c", script], env=dict(os.environ, **dict(good, **patch)), capture_output=True, text=True)
        assert result.returncode == expected, result.stderr


@pytest.mark.parametrize("field,value", [("repository", "wrong"), ("sha", "b"*40), ("run_id", "43"),
    ("ref", "refs/heads/main"), ("ref_type", "branch"), ("schema", "wrong")])
def test_context_bypasses_rejected(field, value):
    env, responses, context = fixtures(); context[field] = value
    with pytest.raises(ValueError): gate.qualify(env, responses.__getitem__, context)


@pytest.mark.parametrize("field,value", [("path", ".github/workflows/other.yml"), ("event", "pull_request"),
    ("status", "in_progress"), ("conclusion", "failure"), ("head_sha", "b"*40),
    ("head_repository", {"full_name": "other/fork"})])
def test_ci_identity_bypasses_rejected(field, value):
    env, responses, context = fixtures(); responses["repos/example/editor/actions/runs/42"][field] = value
    with pytest.raises(ValueError): gate.qualify(env, responses.__getitem__, context)


@pytest.mark.parametrize("mutation", ["tag", "job", "missing", "duplicate", "expired"])
def test_tag_jobs_and_artifact_bypasses_rejected(mutation):
    env, responses, context = fixtures()
    artifacts = responses["repos/example/editor/actions/runs/42/artifacts?per_page=100"]
    if mutation == "tag": responses["repos/example/editor/git/ref/tags/v3.1.8"]["object"]["sha"] = "b"*40
    elif mutation == "job": responses["repos/example/editor/actions/runs/42/attempts/1/jobs?per_page=100"]["jobs"][0]["conclusion"] = "failure"
    elif mutation == "missing": artifacts.update(total_count=0, artifacts=[])
    elif mutation == "duplicate": artifacts["artifacts"] *= 2; artifacts["total_count"] = 2
    else: artifacts["artifacts"][0]["expired"] = True
    with pytest.raises(ValueError): gate.qualify(env, responses.__getitem__, context)


def test_workflow_preserves_tag_context_and_preapproval_audit():
    data = yaml.load((ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text("utf-8"), Loader=yaml.BaseLoader)
    assert set(data["on"]) == {"workflow_dispatch"}
    assert set(data["on"]["workflow_dispatch"]["inputs"]) == {"expected_source_sha", "ci_run_id"}
    jobs = data["jobs"]
    assert "audit-wheels" in jobs["publish"]["needs"]
    assert "environment" not in jobs["audit-wheels"] and jobs["audit-wheels"]["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["publish"]["environment"] == "pypi"
    assert [name for name, job in jobs.items() if job.get("permissions", {}).get("id-token") == "write"] == ["publish"]
    text = (ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text("utf-8")
    assert "workflow_run" not in text and "pending_deployments" not in text
    assert "--verify-report preapproval/wheel-audit.json" in text
    assert data["concurrency"] == {"group": "eqnedit64-release-${{ github.ref }}", "cancel-in-progress": "false"}
