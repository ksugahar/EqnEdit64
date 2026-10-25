"""Bind a tag-ref dispatch to an exact successful tag CI and its context."""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen


def dispatch(env):
    ref, sha, run = (env.get(k, "") for k in ("GITHUB_REF", "EXPECTED_SOURCE_SHA", "CI_RUN_ID"))
    if (env.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or env.get("GITHUB_REF_TYPE") != "tag"
            or not re.fullmatch(r"refs/tags/v[0-9]+\.[0-9]+\.[0-9]+", ref)
            or not re.fullmatch(r"[0-9a-f]{40}", sha) or sha != env.get("GITHUB_SHA")
            or not re.fullmatch(r"[1-9][0-9]*", run)):
        raise ValueError("Release requires an exact tag-ref dispatch, source SHA and CI run")
    return ref, sha, run


def qualify(env, get, context=None):
    ref, sha, run_id = dispatch(env)
    repo = env["GITHUB_REPOSITORY"]
    prefix = f"repos/{repo}/"
    obj = get(prefix + "git/ref/tags/" + ref.removeprefix("refs/tags/"))["object"]
    for _ in range(4):
        if obj["type"] == "commit":
            break
        if obj["type"] != "tag":
            raise ValueError("Unexpected tag object")
        obj = get(prefix + "git/tags/" + obj["sha"])["object"]
    if obj.get("type") != "commit" or obj.get("sha") != sha:
        raise ValueError("Tag no longer points to the qualified source")
    run = get(prefix + "actions/runs/" + run_id)
    if (str(run.get("id")) != run_id or run.get("repository", {}).get("full_name") != repo
            or run.get("head_repository", {}).get("full_name") != repo
            or run.get("path") != ".github/workflows/eqnedit64.yml"
            or run.get("event") != "push" or run.get("status") != "completed"
            or run.get("conclusion") != "success" or run.get("head_sha") != sha):
        raise ValueError("CI run identity, source or conclusion mismatch")
    jobs = get(prefix + f"actions/runs/{run_id}/attempts/{int(run['run_attempt'])}/jobs?per_page=100")
    if jobs.get("total_count") != len(jobs["jobs"]):
        raise ValueError("Unexpected paginated CI jobs")
    for name in ("source-contracts", "web", "build-test"):
        matches = [j for j in jobs["jobs"] if j.get("name") == name]
        if len(matches) != 1 or matches[0].get("conclusion") != "success" or matches[0].get("status") != "completed":
            raise ValueError("Required CI job missing or unsuccessful")
    artifacts = get(prefix + f"actions/runs/{run_id}/artifacts?per_page=100")
    if artifacts.get("total_count") != len(artifacts["artifacts"]):
        raise ValueError("Unexpected paginated CI artifacts")
    matches = [a for a in artifacts["artifacts"] if a.get("name") == "eqnedit64-ci-release-context"]
    if len(matches) != 1 or matches[0].get("expired") is not False:
        raise ValueError("CI context artifact absent, expired or ambiguous")
    if context is not None and (context.get("schema") != "eqnedit64.ci-release-context.v1"
            or context.get("repository") != repo or context.get("sha") != sha
            or str(context.get("run_id")) != run_id or context.get("ref") != ref
            or context.get("ref_type") != "tag"):
        raise ValueError("CI context does not bind the exact release tag")
    return {"sha": sha, "tag": ref.removeprefix("refs/tags/"), "ci_run_id": run_id,
            "ci_run_attempt": run["run_attempt"], "context_artifact_id": matches[0]["id"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context", type=Path)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    # Reject invalid actual refs and inputs before using the token or making any GET.
    dispatch(os.environ)
    def get(path):
        request = Request("https://api.github.com/" + path, headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    result = qualify(os.environ, get, json.loads(args.context.read_text("utf-8")) if args.context else None)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.output and args.context:
        with args.output.open("a", encoding="utf-8") as output:
            output.write("eligible=true\n" + "".join(f"{key}={result[key]}\n" for key in ("sha", "tag")))


if __name__ == "__main__":
    main()
