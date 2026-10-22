"""Independent synthetic API responses exercise the one-shot probe boundary."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import urllib.error
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("draft_probe", ROOT / "tools/probe_draft_access.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.mark.parametrize("failure", [None, "attempt", "missing", "duplicate", "sha", "extra_asset", "asset_id", "hash", "http", "pagination"])
def test_probe_saves_result_without_retries(tmp_path, failure):
    data = b"harmless rehearsal payload\n"
    env = {"GITHUB_RUN_ATTEMPT": "2" if failure == "attempt" else "1",
           "GITHUB_REPOSITORY": "example/editor", "PROBE_RELEASE_ID": "17", "PROBE_ASSET_ID": "23",
           "PROBE_SOURCE_SHA": "a" * 40, "PROBE_ASSET_SHA256": hashlib.sha256(data).hexdigest()}
    release = {"id": 17, "draft": True, "target_commitish": "b" * 40 if failure == "sha" else "a" * 40}
    releases = [] if failure == "missing" else [release] * (2 if failure == "duplicate" else 1)
    asset = {"id": 24 if failure == "asset_id" else 23, "name": "probe.txt", "state": "uploaded", "size": len(data)}
    payloads = [json.dumps(releases).encode(), json.dumps([asset] * (2 if failure == "extra_asset" else 1)).encode(),
                b"wrong bytes" if failure == "hash" else data]
    calls = []
    def get(url, binary=False):
        calls.append((url, binary))
        if failure == "http":
            raise urllib.error.HTTPError(url, 403, "sensitive error text", {}, None)
        response = io.BytesIO(payloads[len(calls) - 1])
        response.status = 200
        response.headers = {"Link": "next"} if failure == "pagination" else {}
        return response
    output = tmp_path / "result.json"
    assert mod.run(env, output, get) == (0 if failure is None else 1)
    result = json.loads(output.read_text("utf-8"))
    assert result["passed"] == (failure is None)
    assert result["finished"] and len(calls) <= 3
    assert len({url for url, _ in calls}) == len(calls)
    assert "sensitive error text" not in output.read_text("utf-8")
    if failure == "attempt": assert calls == []
    if failure is None:
        assert [binary for _, binary in calls] == [False, False, True]
        assert result["asset"]["sha256"] == hashlib.sha256(data).hexdigest()
    if failure == "http": assert result["http_status"] == 403


def test_probe_workflow_is_manual_only_and_matches_signing_reader_permissions():
    folder = ROOT / ".github/workflows"
    data = yaml.load((folder / "draft-access-probe.yml").read_text("utf-8"), Loader=yaml.BaseLoader)
    assert list(data["on"]) == ["workflow_dispatch"]
    assert data["permissions"] == {}
    assert list(data["jobs"]) == ["probe"]
    job = data["jobs"]["probe"]
    release = yaml.load((folder / "release-eqnedit64-pypi.yml").read_text("utf-8"), Loader=yaml.BaseLoader)
    assert job["permissions"] == release["jobs"]["signed-standalone"]["permissions"]
    assert job["runs-on"] == "windows-2022" and job["timeout-minutes"] == "5"
    assert job["steps"][0]["with"]["persist-credentials"] == "false"
    assert job["steps"][-1]["if"] == "always()"
    assert job["steps"][-1]["with"]["if-no-files-found"] == "error"
    assert "environment" not in job
