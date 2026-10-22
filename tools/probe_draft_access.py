"""One-shot, read-only draft asset access rehearsal; never publishes anything."""
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
from datetime import datetime, timezone
from download_release_asset import API, request


def utc():
    return datetime.now(timezone.utc).isoformat()


def probe(env, report, get=request):
    def require(ok):
        if not ok:
            raise ValueError("Unexpected rehearsal input or response")

    def read(stage, url, binary=False):
        entry = {"stage": stage, "status": None}
        report["requests"].append(entry)
        with get(url, binary=binary) as response:
            entry["status"] = response.status
            require(response.status == 200)
            require(not response.headers.get("Link"))
            data = response.read(1048577)
            require(len(data) <= 1048576)
            return data if binary else json.loads(data)

    require(env["GITHUB_RUN_ATTEMPT"] == "1")
    repo = env["GITHUB_REPOSITORY"]
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo))
    release_id = int(env["PROBE_RELEASE_ID"])
    asset_id = int(env["PROBE_ASSET_ID"])
    sha = env["PROBE_SOURCE_SHA"]
    digest = env["PROBE_ASSET_SHA256"]
    require(release_id > 0 and asset_id > 0)
    require(re.fullmatch(r"[0-9a-f]{40}", sha))
    require(re.fullmatch(r"[0-9a-f]{64}", digest))
    report["expected"] = {"release_id": release_id, "asset_id": asset_id,
                          "source_sha": sha, "asset_sha256": digest}
    releases = read("list_releases", f"{API}/repos/{repo}/releases?per_page=100&page=1")
    require(isinstance(releases, list))
    matches = [r for r in releases if r.get("id") == release_id]
    require(len(matches) == 1)
    release = matches[0]
    require(release.get("draft") is True and release.get("target_commitish") == sha)
    report["release"] = {"id": release_id, "draft": True, "source_sha": sha, "matches": 1}
    assets = read("list_assets", f"{API}/repos/{repo}/releases/{release_id}/assets?per_page=100")
    require(isinstance(assets, list) and len(assets) == 1)
    asset = assets[0]
    require(asset.get("id") == asset_id and asset.get("name") == "probe.txt")
    require(asset.get("state") == "uploaded" and type(asset.get("size")) is int)
    require(0 < asset["size"] <= 4096)
    data = read("download_asset", f"{API}/repos/{repo}/releases/assets/{asset_id}", binary=True)
    actual = hashlib.sha256(data).hexdigest()
    report["asset"] = {"id": asset_id, "count": 1, "size": len(data), "sha256": actual}
    require(len(data) == asset["size"] and actual == digest)


def run(env, output, get=request):
    report = {"schema": "eqnedit64.draft-access-probe.v1", "started": utc(),
              "repository": env.get("GITHUB_REPOSITORY"), "workflow_ref": env.get("GITHUB_WORKFLOW_REF"),
              "source_sha": env.get("GITHUB_SHA"), "run_id": env.get("GITHUB_RUN_ID"),
              "run_attempt": env.get("GITHUB_RUN_ATTEMPT"), "runner_os": env.get("RUNNER_OS"),
              "token_kind": "GITHUB_TOKEN", "declared_permissions": {"contents": "write", "actions": "read"},
              "requests": [], "passed": False}
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    try:
        probe(env, report, get)
        report["passed"] = True
    except Exception as error:
        report["error_category"] = type(error).__name__
        if isinstance(error, urllib.error.HTTPError):
            report["http_status"] = error.code
            if report["requests"]:
                report["requests"][-1]["status"] = error.code
    finally:
        report["finished"] = utc()
        text = json.dumps(report, indent=2)
        output.write_text(text, encoding="utf-8")
        print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run(os.environ, Path("draft-access-probe.json")))
