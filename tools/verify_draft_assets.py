"""Compare every draft asset before allowing any package or release publication."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from download_release_asset import API, fetch_release, request
from check_release_versions import MARKER, clean

ASSETS = {"EqnEdit64.exe", "EqnEdit64.release.json", "SHA256SUMS.txt"}

def validate_release_metadata(release, version):
    if release.get("name") != f"EqnEdit64 {version}":
        raise ValueError("Release title must match the exact product version")
    body = release.get("body")
    if not isinstance(body, str) or not body.strip() or not re.search(r"(?<![0-9.])" + re.escape(version) + r"(?![0-9A-Za-z]|\.[0-9])", body):
        raise ValueError("Final release notes must include the exact version")
    if any(MARKER.search(text) or re.search(r"draft|staging|unpublished|not[\s-]*published|pre[\s-]*release|下書き", text, re.I)
           for text in (release["name"], body)):
        raise ValueError("Release notes still describe an unpublished draft")
    for text in (release["name"], body):
        clean(text, "release title/notes")


def verify(repo, tag, source_sha, artifact_dir):
    release = fetch_release(repo, tag, source_sha)
    validate_release_metadata(release, tag.removeprefix("v"))
    assets = release.get("assets", [])
    if len(assets) != 3 or {a.get("name") for a in assets} != ASSETS:
        raise ValueError("Draft must contain exactly the three qualified assets")
    for asset in assets:
        if asset.get("state") != "uploaded": raise ValueError("Asset upload is incomplete")
        expected = (artifact_dir / asset["name"]).read_bytes()
        if len(expected) != int(asset["size"]): raise ValueError("Draft/artifact asset size mismatch")
        with request(f"{API}/repos/{repo}/releases/assets/{int(asset['id'])}", binary=True) as response:
            actual = response.read()
        if actual != expected: raise ValueError("Draft asset bytes differ from qualified artifact")
    manifest = json.loads((artifact_dir / "EqnEdit64.release.json").read_text("utf-8-sig"))
    if set(manifest) != {"schema", "repository", "tag", "version", "source_sha", "exe_sha256"}:
        raise ValueError("Unexpected public manifest fields")
    actual_hash = hashlib.sha256((artifact_dir / "EqnEdit64.exe").read_bytes()).hexdigest()
    if (manifest["schema"] != "eqnedit64.staged-release.v1" or manifest["repository"] != repo or
        manifest["tag"] != tag or manifest["version"] != tag.removeprefix("v") or
        manifest["source_sha"] != source_sha or manifest["exe_sha256"].lower() != actual_hash):
        raise ValueError("Manifest does not bind the exact qualified artifact")
    checksum = (artifact_dir / "SHA256SUMS.txt").read_text("utf-8-sig").strip()
    if checksum != actual_hash + "  EqnEdit64.exe": raise ValueError("Qualified checksum is inconsistent")
    release_id = int(release["id"])
    if release_id <= 0: raise ValueError("Invalid draft release identifier")
    return release_id

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--artifact-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    release_id = verify(args.repo, args.tag, args.source_sha, args.artifact_dir)
    with args.output.open("a", encoding="utf-8") as output: output.write(f"release_id={release_id}\n")
if __name__ == "__main__": main()
