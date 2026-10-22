"""Run the independent repository source-contract lane; no native or Office execution."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    commands = [[sys.executable, "tools/privacy_lint.py"],
                [sys.executable, "tests/check_public_names.py"],
                [sys.executable, "-m", "pytest", "tests/test_public_names.py", "tests/test_privacy_lint.py", "tests/test_version_contract.py", "tests/test_release_workflow.py", "-q"]]
    steps = []
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        steps.append({"command": command, "returncode": result.returncode,
                      "output": result.stdout + result.stderr})
    sha = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
    report = {"source_sha": sha, "scope": "source contracts only; native/release acceptance pending", "passed": all(s["returncode"] == 0 for s in steps), "steps": steps}
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for step in steps: print(step["returncode"], " ".join(step["command"]))
    return int(not report["passed"])
if __name__ == "__main__": raise SystemExit(main())
