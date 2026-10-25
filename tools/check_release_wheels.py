"""Bind release wheels to the qualified standalone and canonical Web Git blobs."""
import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

VERSIONS = ("3.10", "3.11", "3.12", "3.13")
WEB = ("equation-editor.js", "equation-editor.fragment.html")


def canonical_web(repository, source_sha):
    actual = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    if actual != source_sha:
        raise ValueError("Wheel audit checkout does not match the expected source")
    return {name: subprocess.check_output(["git", "-C", str(repository), "cat-file", "blob",
                                          f"{source_sha}:web/{name}"]) for name in WEB}


def verify(wheels, executable, version, web, python_versions=VERSIONS):
    expected = {"cp" + v.replace(".", "") for v in python_versions}
    if not expected or not set(python_versions) <= set(VERSIONS) or len(wheels) != len(expected):
        raise ValueError("Expected exactly one wheel for every selected Python ABI")
    seen = set()
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or any("\\" in n or PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names):
                raise ValueError("Unsafe or duplicate wheel members")
            metadata = [n for n in names if n.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Expected one wheel metadata directory")
            info = metadata[0].removesuffix("METADATA")
            meta = BytesParser().parsebytes(archive.read(metadata[0]))
            if meta.get_all("Name") != ["EqnEdit64"] or meta.get_all("Version") != [version]:
                raise ValueError("Wheel distribution/version mismatch")
            tags = BytesParser().parsebytes(archive.read(info + "WHEEL")).get_all("Tag", [])
            matches = [abi for abi in expected if tags == [f"{abi}-{abi}-win_amd64"]]
            if len(matches) != 1 or matches[0] in seen:
                raise ValueError("Wheel ABI tags are missing, duplicate or unexpected")
            abi = matches[0]
            if wheel.name != f"eqnedit64-{version}-{abi}-{abi}-win_amd64.whl":
                raise ValueError("Wheel filename and declared ABI disagree")
            seen.add(abi)
            if archive.read("eqnedit64/EqnEdit64.exe") != executable:
                raise ValueError("Embedded executable differs from the qualified signed standalone")
            for name in WEB:
                if archive.read("eqnedit64/web/" + name) != web[name]:
                    raise ValueError("Packaged Web bytes differ from the canonical source blob")
            rows = list(csv.reader(io.StringIO(archive.read(info + "RECORD").decode("utf-8"))))
            if any(len(row) != 3 for row in rows) or len(rows) != len(names) or {r[0] for r in rows} != set(names) or len({r[0] for r in rows}) != len(rows):
                raise ValueError("Wheel RECORD does not cover every member exactly once")
            for name, digest, size in rows:
                if name == info + "RECORD":
                    if digest or size:
                        raise ValueError("RECORD must not hash itself")
                    continue
                payload = archive.read(name)
                expected_digest = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode("ascii")
                if digest != expected_digest or size != str(len(payload)):
                    raise ValueError("Wheel RECORD hash or size mismatch")
    if seen != expected:
        raise ValueError("Release wheel ABI set is incomplete")
    return {"wheels": len(wheels), "abis": sorted(seen), "exe_sha256": hashlib.sha256(executable).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wheel-dir", type=Path, required=True)
    p.add_argument("--standalone", type=Path, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--python-version", choices=VERSIONS)
    args = p.parse_args()
    repository = Path(__file__).resolve().parents[1]
    result = verify(sorted(args.wheel_dir.glob("*.whl")), args.standalone.read_bytes(), args.version,
                    canonical_web(repository, args.source_sha), (args.python_version,) if args.python_version else VERSIONS)
    print(result)


if __name__ == "__main__":
    main()
