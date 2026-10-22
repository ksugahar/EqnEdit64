"""Read exact draft-release assets through the authenticated repository API."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

API = "https://api.github.com"

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        if urllib.parse.urlparse(new_url).scheme != "https":
            raise ValueError("Non-HTTPS asset redirect")
        redirected = super().redirect_request(request, fp, code, message, headers, new_url)
        if urllib.parse.urlparse(new_url).hostname != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected

def request(url, binary=False):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("Authenticated draft access is required")
    if not url.startswith(API + "/"):
        raise ValueError("Only the repository API may receive authentication")
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    opener = urllib.request.build_opener(SafeRedirect())
    return opener.open(urllib.request.Request(url, headers=headers), timeout=60)

def select_draft(releases, tag, source_sha):
    matches = [item for item in releases if item.get("tag_name") == tag]
    if len(matches) != 1 or matches[0].get("draft") is not True:
        raise ValueError("Exactly one unpublished draft for the release tag is required")
    release = matches[0]
    if release.get("target_commitish") != source_sha:
        raise ValueError("Draft must target the exact qualified source SHA")
    return release

def fetch_release(repo, tag, source_sha):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository name")
    if not re.fullmatch(r"v[0-9]+[.][0-9]+[.][0-9]+", tag) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Invalid tag or source SHA")
    releases = []
    for page in range(1, 11):
        with request(f"{API}/repos/{repo}/releases?per_page=100&page={page}") as response:
            batch = json.load(response)
        releases.extend(batch)
        if len(batch) < 100:
            return select_draft(releases, tag, source_sha)
    raise ValueError("Release pagination bound exceeded")

def download(repo, tag, source_sha, name, destination, minimum):
    if name not in {"Eqnedit64.exe", "Eqnedit64.release.json", "SHA256SUMS.txt"}:
        raise ValueError("Unexpected staged asset name")
    release = fetch_release(repo, tag, source_sha)
    assets = [a for a in release.get("assets", []) if a.get("name") == name]
    if len(assets) != 1 or assets[0].get("state") != "uploaded":
        raise ValueError("Exactly one completely uploaded staged asset is required")
    asset = assets[0]
    url = f"{API}/repos/{repo}/releases/assets/{int(asset['id'])}"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / name
    with request(url, binary=True) as response, path.open("wb") as output:
        while chunk := response.read(1024 * 1024): output.write(chunk)
    if path.stat().st_size < minimum or path.stat().st_size != int(asset["size"]):
        raise ValueError("Truncated or incorrectly sized staged asset")
    return path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--min-size", type=int, default=1)
    args = parser.parse_args()
    download(args.repo, args.tag, args.source_sha, args.name, args.dest, args.min_size)
    return 0
if __name__ == "__main__": raise SystemExit(main())
