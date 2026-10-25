"""Bind release wheels to the qualified standalone and canonical Web Git blobs."""
import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile
try:
    import tomllib
except ImportError:
    import tomli as tomllib

VERSIONS = ("3.10", "3.11", "3.12", "3.13")
WEB = ("equation-editor.js", "equation-editor.fragment.html")
ROOT = Path(__file__).resolve().parents[1]


def expected_metadata(version):
    project = tomllib.loads((ROOT / "python/pyproject.toml").read_text("utf-8"))["project"]
    licenses = sorted({p.relative_to(ROOT / "python").as_posix()
                       for pattern in project["license-files"]
                       for p in (ROOT / "python").glob(pattern) if p.is_file()})
    return {"Metadata-Version": ["2.4"], "Name": [project["name"]], "Version": [version],
            "Summary": [project["description"]], "Keywords": [",".join(project["keywords"])],
            "Author": [project["authors"][0]["name"]], "License-Expression": [project["license"]],
            "License-File": licenses, "Classifier": project["classifiers"],
            "Project-URL": [f"{key}, {value}" for key, value in project["urls"].items()],
            "Requires-Python": [project["requires-python"]],
            "Provides-Extra": list(project["optional-dependencies"]),
            "Requires-Dist": [f'{dependency}; extra == "{extra}"' for extra, dependencies in project["optional-dependencies"].items() for dependency in dependencies],
            "Description-Content-Type": ["text/markdown"]}


def expected_files(info, abi):
    files = {"eqnedit64/" + p.name: p.read_bytes() for p in (ROOT / "python/src/eqnedit64").glob("*.py")}
    for p in (ROOT / "assets").iterdir():
        if p.name in {"GUST-FONT-LICENSE.txt", "BOOTSTRAP-ICONS-LICENSE.txt", "THIRD_PARTY_NOTICES.md", "MANIFEST-eqnedit-math.txt"}:
            files["eqnedit64/licenses/" + p.name] = p.read_bytes()
    for name in expected_metadata("unused")["License-File"]:
        files[info + "licenses/" + name] = (ROOT / "python" / name).read_bytes()
    files[info + "entry_points.txt"] = b"[console_scripts]\neqnedit64 = eqnedit64.cli:main\n\n"
    # The extension is validated by the native lane; its ABI-specific presence is mandatory.
    return files, "eqnedit64/eqnedit_core." + abi + "-win_amd64.pyd"


def bind_report(result, wheel_dir, standalone, source_sha, version, previous=None):
    staged = sorted(standalone.parent.iterdir())
    if {p.name for p in staged} != {"EqnEdit64.exe", "EqnEdit64.release.json", "SHA256SUMS.txt"} or any(not p.is_file() for p in staged):
        raise ValueError("Standalone artifact must contain exactly three qualified files")
    result = dict(result, source_sha=source_sha, version=version,
                  files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in [*sorted(wheel_dir.glob("*.whl")), *staged]})
    if previous is not None and previous != result:
        raise ValueError("Artifacts differ from the pre-approval audit")
    return result


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
            if info != f"eqnedit64-{version}.dist-info/":
                raise ValueError("Wheel metadata directory mismatch")
            wanted = expected_metadata(version)
            if set(meta.keys()) != set(wanted) or any(sorted(meta.get_all(k, [])) != sorted(v) for k, v in wanted.items()):
                raise ValueError("Wheel METADATA fields differ from the source contract")
            if meta.get_payload().replace("\r\n", "\n").rstrip("\n") != (ROOT / "python/README.md").read_text("utf-8").rstrip("\n"):
                raise ValueError("Wheel METADATA description differs from source")
            wheel_meta = BytesParser().parsebytes(archive.read(info + "WHEEL"))
            tags = wheel_meta.get_all("Tag", [])
            matches = [abi for abi in expected if tags == [f"{abi}-{abi}-win_amd64"]]
            if len(matches) != 1 or matches[0] in seen:
                raise ValueError("Wheel ABI tags are missing, duplicate or unexpected")
            abi = matches[0]
            wheel_fields = {"Wheel-Version": ["1.0"], "Generator": ["scikit-build-core 1.1.1"],
                            "Root-Is-Purelib": ["false"], "Tag": [f"{abi}-{abi}-win_amd64"]}
            if set(wheel_meta.keys()) != set(wheel_fields) or any(wheel_meta.get_all(k) != v for k, v in wheel_fields.items()) or wheel_meta.get_payload().strip():
                raise ValueError("Wheel WHEEL fields differ from the native wheel contract")
            fixed, extension = expected_files(info, abi)
            allowed = set(fixed) | {extension, "eqnedit64/EqnEdit64.exe", info + "METADATA", info + "WHEEL", info + "RECORD"} | {"eqnedit64/web/" + n for n in WEB}
            if set(names) != allowed or not archive.read(extension):
                raise ValueError("Wheel member set differs from source contract")
            for name, data in fixed.items():
                if archive.read(name).replace(b"\r\n", b"\n") != data.replace(b"\r\n", b"\n"):
                    raise ValueError("Wheel source/license/entry-point bytes mismatch")
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
    p.add_argument("--report", type=Path)
    p.add_argument("--verify-report", type=Path)
    args = p.parse_args()
    repository = Path(__file__).resolve().parents[1]
    if tomllib.loads((ROOT / "python/pyproject.toml").read_text("utf-8"))["project"]["version"] != args.version:
        raise ValueError("Tag version differs from source package")
    result = verify(sorted(args.wheel_dir.glob("*.whl")), args.standalone.read_bytes(), args.version,
                    canonical_web(repository, args.source_sha), (args.python_version,) if args.python_version else VERSIONS)
    if args.report or args.verify_report:
        result = bind_report(result, args.wheel_dir, args.standalone, args.source_sha, args.version,
                             json.loads(args.verify_report.read_text("utf-8")) if args.verify_report else None)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(result)


if __name__ == "__main__":
    main()
