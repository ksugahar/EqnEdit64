"""Inspect public content for generic identifying data shapes."""
import argparse
import hashlib
import zipfile
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Definitions and negative tests are assembled from tokens, not excluded:
# this checker, tests, and every other public semantic text remain scanned.
# Public rules describe generic data shapes, never project-specific identities.
import importlib.util
_spec = importlib.util.spec_from_file_location("content_shapes", ROOT / "tools/privacy_lint.py")
_shapes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shapes)



def notebook_text(document):
    for cell in document.get("cells", []):
        yield "".join(cell.get("source", []))
        for output in cell.get("outputs", []):
            yield "".join(output.get("text", []))
            for mime, value in output.get("data", {}).items():
                if mime.startswith("text/"):
                    yield "".join(value) if isinstance(value, list) else str(value)


def binary_hits(data):
    return bool(_shapes.findings("", data))


def artifact_hits(path):
    bad = []
    if _shapes.findings(path.name, b""):
        bad.append(str(path) + ": name")
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as wheel:
            for member in wheel.infolist():
                if _shapes.findings(member.filename, b"") or binary_hits(wheel.read(member)):
                    bad.append(str(path) + ": member " + member.filename)
    elif binary_hits(path.read_bytes()):
        bad.append(str(path) + ": bytes")
    return bad


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    bad = []
    semantic_count = 0
    semantic_hash = hashlib.sha256()
    for name in filter(None, paths):
        path = ROOT / name
        if _shapes.findings(name, b""):
            bad.append(name + ": path")
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        texts = notebook_text(json.loads(text)) if path.suffix == ".ipynb" else [text]
        semantic_count += 1
        semantic_hash.update(name.encode("utf-8") + b"\0" + data)
        if any(binary_hits(part.encode("utf-8")) for part in texts):
            bad.append(name + ": text")
    artifacts = []
    for path in args.artifact:
        data = path.read_bytes()
        artifacts.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest()})
        bad.extend(artifact_hits(path))
    report = {"status": "FAIL" if bad else "PASS", "source_semantic_files": semantic_count,
              "source_semantic_sha256": semantic_hash.hexdigest(),
              "source_head": subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, text=True, capture_output=True).stdout.strip() or None,
              "source_scope": "tracked paths and UTF-8 semantic text; notebook text excludes binary image payloads",
              "artifact_scope": "only explicitly supplied artifacts; no release-artifact result inferred",
              "artifacts": artifacts, "findings": bad}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if bad:
        raise SystemExit("\n".join(bad))
    print("PASS: generic public-content shapes; explicit artifacts=" + str(len(artifacts)))


if __name__ == "__main__":
    main()
