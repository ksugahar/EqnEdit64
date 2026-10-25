"""Guards: exact tag/CI provenance before approval; assumes GitHub GET integrity."""
import copy
import importlib.util
import os
import re
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


def publication_sequence_contract(data):
    """Required approval boundary checks must execute unconditionally in order."""
    jobs = data["jobs"]
    steps = jobs["publish"]["steps"]
    for job in jobs.values():
        assert str(job.get("continue-on-error", "false")).lower() == "false", "Release jobs must fail closed"
        assert not re.search(r"always\s*\(", str(job.get("if", "")), re.I), "Release jobs must not bypass dependency failures"

    def strict(step):
        assert str(step.get("continue-on-error", "false")).lower() == "false", "Mandatory checks must fail closed"
        assert not re.search(r"\|\|\s*true\b", step.get("run", ""), re.I), "Mandatory checks must preserve errors"
    selectors = [
        lambda s: "--report postapproval-qualification.json" in s.get("run", ""),
        lambda s: s.get("uses", "").startswith("actions/download-artifact@") and s.get("with", {}).get("name") == "eqnedit64-ci-release-context",
        lambda s: "--context eqnedit64-ci-release-context/context.json" in s.get("run", ""),
        lambda s: "verify_draft_assets.py" in s.get("run", ""),
        lambda s: "--verify-report" in s.get("run", ""),
        lambda s: s.get("uses", "").startswith("pypa/gh-action-pypi-publish@"),
        lambda s: 'gh api --method PATCH' in s.get("run", ""),
    ]
    positions = []
    for select in selectors:
        matches = [i for i, step in enumerate(steps) if select(step)]
        assert len(matches) == 1, "Missing or ambiguous mandatory publication check"
        i = matches[0]
        assert "if" not in steps[i], "Mandatory publication checks must not be conditional"
        strict(steps[i])
        positions.append(i)
    assert positions == sorted(positions), "Publication checks must precede upload in approval order"
    context = steps[positions[1]]["with"]
    assert context["run-id"] == "${{ inputs.ci_run_id }}", "Recheck must download the qualified CI context"
    assert steps[positions[5]]["with"].get("skip-existing") == "false", "Existing releases must fail closed"
    signed = jobs["signed-standalone"]["steps"]
    checks = [i for i, s in enumerate(signed) if "verify_draft_assets.py" in s.get("run", "")]
    uploads = [i for i, s in enumerate(signed) if s.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(checks) == 1 and uploads and checks[0] < min(uploads), "Draft checks must run before approval"
    assert "if" not in signed[checks[0]], "Pre-approval draft check must be unconditional"
    strict(signed[checks[0]])


def test_publication_sequence_guards_cannot_be_removed_or_skipped():
    data = yaml.load((ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text("utf-8"), Loader=yaml.BaseLoader)
    publication_sequence_contract(data)


@pytest.mark.parametrize("mutation", ["tag-check", "context-check", "draft-skip", "skip-existing", "continue-error", "ignore-error", "always-job"])
def test_required_publication_guard_mutations_fail(mutation):
    data = yaml.load((ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text("utf-8"), Loader=yaml.BaseLoader)
    steps = data["jobs"]["publish"]["steps"]
    if mutation in {"tag-check", "context-check"}:
        token = "--report postapproval-qualification.json" if mutation == "tag-check" else "--context eqnedit64-ci-release-context/context.json"
        steps[:] = [s for s in steps if token not in s.get("run", "")]
    elif mutation == "draft-skip":
        check = next(s for s in data["jobs"]["signed-standalone"]["steps"] if "verify_draft_assets.py" in s.get("run", ""))
        check["if"] = "false"
    elif mutation == "continue-error":
        steps[0]["continue-on-error"] = "true"
        # Select a mandatory post-approval qualification step.
        next(s for s in steps if "--report postapproval-qualification.json" in s.get("run", ""))["continue-on-error"] = "true"
    elif mutation == "ignore-error":
        check = next(s for s in steps if "--report postapproval-qualification.json" in s.get("run", ""))
        check["run"] += " || true"
    elif mutation == "always-job":
        data["jobs"]["publish"]["if"] = "always()"
    else:
        upload = next(s for s in steps if s.get("uses", "").startswith("pypa/"))
        upload["with"]["skip-existing"] = "true"
    with pytest.raises(AssertionError):
        publication_sequence_contract(data)
