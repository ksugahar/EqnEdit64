"""Reject private operational metadata from a public source snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "absolute-drive": re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][A-Za-z_][A-Za-z0-9_. -]{2,}"),
    "certificate-id": re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", re.I),
    "network-location": re.compile(r"(?<![0-9.])(?:10|192|172)[.][0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3}(?![0-9.])"),
}

def findings(name, data):
    result = []
    # Binary assets also undergo printable/UTF16 metadata inspection.
    texts = [name, data.decode("utf-8", errors="ignore")]
    if b"\0" in data:
        texts += [data.decode(enc, errors="ignore") for enc in ("utf-16-le", "utf-16-be")]
    # Content-addressed workflow dependencies are public provenance, not certificate IDs.
    action = re.compile(r"(?m)^(\s*(?:-\s*)?uses:\s*['\"]?[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@)[0-9a-f]{40}(['\"]?\s*(?:#.*)?)$")
    texts = [action.sub(r"\1<revision>\2", text) for text in texts]
    for category, pattern in PATTERNS.items():
        if any(pattern.search(text) for text in texts): result.append(category)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    bad = []; hashed = []
    for name in filter(None, paths):
        data = (ROOT / name).read_bytes()
        hashed.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
        for category in findings(name, data): bad.append({"path": name, "category": category})
    report = {"scope": "tracked snapshot bytes; not provenance clearance", "findings": bad, "files": hashed, "passed": not bad}
    if args.report: args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for item in bad: print(item["path"] + ": " + item["category"])
    raise SystemExit(bool(bad))

if __name__ == "__main__": main()
