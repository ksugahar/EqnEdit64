"""Behavioral release-gate checks without native execution or remote publication."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]

def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text("utf-8"))

@pytest.mark.parametrize("name", ["eqnedit64.yml", "release-eqnedit64-pypi.yml"])
def test_workflow_has_literal_event_trigger(name):
    # BaseLoader preserves keys instead of interpreting YAML 1.1 booleans.
    data = yaml.load((ROOT / ".github/workflows" / name).read_text("utf-8"), Loader=yaml.BaseLoader)
    assert "on" in data, f"{name}: GitHub requires a literal on event key"
    assert "true" not in data and "false" not in data
    assert isinstance(data["on"], dict) and data["on"]


def test_hosted_runtime_and_artifact_transport_contracts():
    """Guards: pinned hosted runtimes and artifact paths; assumes upstream pins are reviewed."""
    pins = {}
    for name in ("eqnedit64.yml", "release-eqnedit64-pypi.yml"):
        for job in workflow(name)["jobs"].values():
            assert job["runs-on"] in {"ubuntu-24.04", "windows-2022"}
            for step in job.get("steps", []):
                if "uses" not in step:
                    continue
                action, ref = step["uses"].split("@")
                assert re.fullmatch(r"[0-9a-f]{40}", ref), step["uses"]
                assert pins.setdefault(action, ref) == ref, (action, "inconsistent pins")
                inputs = step.get("with", {})
                if action == "actions/setup-node":
                    assert str(inputs["node-version"]) == "24"
                    assert inputs["package-manager-cache"] is False
                if action == "actions/download-artifact":
                    assert not (inputs.get("name") and inputs.get("artifact-ids"))
                    assert not inputs.get("skip-decompress", False)
                    assert inputs.get("digest-mismatch", "error") == "error"
                if action == "actions/upload-artifact":
                    assert inputs.get("archive", True) is True
                    assert inputs.get("overwrite", False) is False
                    assert inputs.get("include-hidden-files", False) is False

    jobs = workflow("release-eqnedit64-pypi.yml")["jobs"]
    context = next(s for s in jobs["qualify"]["steps"]
                   if s.get("uses", "").startswith("actions/download-artifact@"))["with"]
    assert context["name"] == "eqnedit64-ci-release-context"
    assert context["path"] == "eqnedit64-ci-release-context"
    assert context["run-id"] == "${{ github.event.workflow_run.id }}"
    assert context["github-token"] == "${{ secrets.GITHUB_TOKEN }}"
    downloads = [s["with"] for s in jobs["publish"]["steps"]
                 if s.get("uses", "").startswith("actions/download-artifact@")]
    assert any(d.get("pattern") == "eqnedit64-wheel-*" and d["path"] == "dist"
               and d["merge-multiple"] is True for d in downloads)
    assert any(d.get("name") == "eqnedit64-signed-standalone"
               and d["path"] == "standalone" for d in downloads)


def test_privileged_release_checkouts_do_not_persist_credentials():
    data = workflow("release-eqnedit64-pypi.yml")
    for name in ("signed-standalone", "build-wheels", "publish"):
        checkouts = [step for step in data["jobs"][name]["steps"]
                     if step.get("uses", "").startswith("actions/checkout@")]
        assert checkouts and all(step["with"]["persist-credentials"] is False for step in checkouts)


def premature_guards(script):
    """Reject guards before any native command in a fresh PowerShell process."""
    native = re.compile(r"^\s*(?:&\s+|(?:python[0-9]?|dotnet|cmake|ctest|cmd(?:[.]exe)?|node|npm|npx|pwsh|gh|cl|rc)(?:\s|$))", re.I)
    seen = False
    bad = []
    for number, line in enumerate(script.splitlines(), 1):
        if native.search(line): seen = True
        if re.search(r"if\s*\(.*\$LASTEXITCODE", line, re.I) and not seen: bad.append(number)
    return bad

def test_all_windows_workflow_scripts_have_no_premature_native_exit_guard():
    assert premature_guards('if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\npython test.py') == [1]
    assert not premature_guards('python test.py\nif ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }')
    for name in ("eqnedit64.yml", "release-eqnedit64-pypi.yml"):
        for job in workflow(name)["jobs"].values():
            if not str(job.get("runs-on", "")).startswith("windows"): continue
            for step in job.get("steps", []):
                assert not premature_guards(step.get("run", "")), (name, step.get("name"))

def test_schema_step_executes_both_commands_and_propagates_errors(tmp_path):
    import shutil
    shell = shutil.which("pwsh")
    if shell is None: pytest.skip("PowerShell behavior is exercised by Windows CI")
    step = next(s for s in workflow("eqnedit64.yml")["jobs"]["build-test"]["steps"]
                if s.get("name") == "Validate native PowerPoint math fragments and schema")
    for code, expected in ((0, ["python", "dotnet"]), (7, ["python"])):
        log = tmp_path / f"calls-{code}.jsonl"
        setup = f"""$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE = $null
function python {{ 'python' | Add-Content -LiteralPath '{log.as_posix()}'; $global:LASTEXITCODE = {code} }}
function dotnet {{ 'dotnet' | Add-Content -LiteralPath '{log.as_posix()}'; $global:LASTEXITCODE = 0 }}
"""
        result = subprocess.run([shell, "-NoProfile", "-Command", setup + step["run"]], capture_output=True, text=True)
        assert result.returncode == code, result.stdout + result.stderr
        assert log.read_text("utf-8-sig").splitlines() == expected

def test_all_publication_comparisons_precede_pypi_upload():
    data = workflow("release-eqnedit64-pypi.yml")
    steps = data["jobs"]["publish"]["steps"]
    preflight = next(i for i, s in enumerate(steps) if s.get("id") == "draft")
    pypi = next(i for i, s in enumerate(steps) if s.get("uses", "").startswith("pypa/gh-action-pypi-publish@"))
    assert preflight < pypi
    checkout = next(i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/checkout@"))
    downloads = [i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/download-artifact@")]
    assert downloads and checkout < min(downloads), "Checkout must not clean already downloaded artifacts"

    assert "verify_draft_assets.py" in steps[preflight]["run"]
    assert not steps[preflight].get("if")
    assert re.fullmatch(r"pypa/gh-action-pypi-publish@[0-9a-f]{40}", steps[pypi]["uses"])
    assert data["jobs"]["signed-standalone"]["permissions"]["contents"] == "write"
    assert data["permissions"]["contents"] == "read"
    signature = next(s for s in data["jobs"]["signed-standalone"]["steps"] if s.get("name") == "Verify the signed standalone against the tag")
    assert "Copy-Item -LiteralPath (Join-Path $releaseRoot 'SHA256SUMS.txt') -Destination $artifact" in signature["run"]
    assert "WriteAllText" not in signature["run"]

def verifier():
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("draft_preflight", ROOT / "tools/verify_draft_assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b""])
def test_preflight_preserves_and_compares_exact_checksum_bytes(tmp_path, monkeypatch, ending):
    import io
    mod = verifier()
    executable = b"synthetic qualified executable"
    digest = hashlib.sha256(executable).hexdigest()
    manifest = {"schema": "eqnedit64.staged-release.v1", "repository": "example/editor", "tag": "v3.1.6",
                "version": "3.1.6", "source_sha": "a" * 40, "exe_sha256": digest}
    payloads = {"EqnEdit64.exe": executable, "EqnEdit64.release.json": json.dumps(manifest).encode(),
                "SHA256SUMS.txt": (digest + "  EqnEdit64.exe").encode() + ending}
    assets = []
    for index, (name, data) in enumerate(payloads.items(), 1):
        (tmp_path / name).write_bytes(data)
        assets.append({"id": index, "name": name, "size": len(data), "state": "uploaded"})
    monkeypatch.setattr(mod, "fetch_release", lambda *args: {"id": 42, "assets": assets, "name": "EqnEdit64 3.1.6", "body": "EqnEdit64 3.1.6 signed standalone release."})
    def response(url, binary=False):
        entry = next(a for a in assets if str(a["id"]) == url.rsplit("/", 1)[1])
        return io.BytesIO(payloads[entry["name"]])
    monkeypatch.setattr(mod, "request", response)
    assert mod.verify("example/editor", "v3.1.6", "a" * 40, tmp_path) == 42
    assert (tmp_path / "SHA256SUMS.txt").read_bytes().endswith(ending)
    # Byte differences fail even if whitespace-normalized checksums would agree.
    payloads["SHA256SUMS.txt"] += b" "
    assets[2]["size"] += 1
    with pytest.raises(ValueError): mod.verify("example/editor", "v3.1.6", "a" * 40, tmp_path)
    payloads["SHA256SUMS.txt"] = (tmp_path / "SHA256SUMS.txt").read_bytes()
    assets[2]["size"] -= 1
    assets.append({"id": 4, "name": "unexpected.txt", "size": 0, "state": "uploaded"})
    with pytest.raises(ValueError): mod.verify("example/editor", "v3.1.6", "a" * 40, tmp_path)


@pytest.mark.parametrize("name,body", [("wrong", "EqnEdit64 3.1.7"), ("EqnEdit64 3.1.7", ""), ("EqnEdit64 3.1.7", "Release 3.1.6"), ("EqnEdit64 3.1.7", "Draft 3.1.7"), ("EqnEdit64 3.1.7", "3.1.7 staging"), ("EqnEdit64 3.1.7", "3.1.7 not published")])
def test_release_metadata_rejects_unfinished_notes(name, body):
    with pytest.raises(ValueError):
        verifier().validate_release_metadata({"name": name, "body": body}, "3.1.7")


def test_release_metadata_accepts_final_notes_and_wheel_gate_precedes_upload():
    verifier().validate_release_metadata({"name": "EqnEdit64 3.1.7", "body": "EqnEdit64 3.1.7 signed standalone release."}, "3.1.7")
    jobs = workflow("release-eqnedit64-pypi.yml")["jobs"]
    steps = jobs["publish"]["steps"]
    gate = next(i for i, step in enumerate(steps) if "check_release_wheels.py" in step.get("run", ""))
    upload = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("pypa/"))
    assert gate < upload and not steps[gate].get("if")
    matrix_gate = next(s for s in jobs["build-wheels"]["steps"] if "check_release_wheels.py" in s.get("run", ""))
    assert '--python-version "${{ matrix.python-version }}"' in matrix_gate["run"]
