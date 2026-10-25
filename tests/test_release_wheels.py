"""Guards: published wheel bytes and metadata; assumes a qualified signed standalone."""
import base64
import csv
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wheel_release_gate", ROOT / "tools/check_release_wheels.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
EXE = b"synthetic signed standalone"
WEB = {name: b"canonical web bytes\n" for name in gate.WEB}


def make_wheel(folder, abi, change=None):
    info = "eqnedit64-3.1.7.dist-info/"
    meta = "\n".join(f"{key}: {value}" for key, values in gate.expected_metadata("3.1.7").items() for value in values)
    meta = (meta + "\n\n" + (ROOT / "python/README.md").read_text("utf-8")).encode("utf-8")
    fixed, extension = gate.expected_files(info, abi)
    members = {**fixed, extension: b"synthetic native extension", "eqnedit64/EqnEdit64.exe": EXE,
               **{"eqnedit64/web/" + n: v for n, v in WEB.items()},
               info + "METADATA": meta,
               info + "WHEEL": f"Wheel-Version: 1.0\nGenerator: scikit-build-core 1.1.1\nRoot-Is-Purelib: false\nTag: {abi}-{abi}-win_amd64\n".encode()}
    if change:
        change(members)
    rows = []
    for name, data in members.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append((name, "sha256=" + digest, str(len(data))))
    rows.append((info + "RECORD", "", ""))
    output = io.StringIO(); csv.writer(output).writerows(rows)
    members[info + "RECORD"] = output.getvalue().encode()
    path = folder / f"eqnedit64-3.1.7-{abi}-{abi}-win_amd64.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def test_complete_wheel_set_and_matrix_member(tmp_path):
    wheels = [make_wheel(tmp_path, "cp" + v.replace(".", "")) for v in gate.VERSIONS]
    assert gate.verify(wheels, EXE, "3.1.7", WEB)["wheels"] == 4
    assert gate.verify(wheels[:1], EXE, "3.1.7", WEB, ("3.10",))["abis"] == ["cp310"]
    with pytest.raises(ValueError, match="exactly"):
        gate.verify(wheels[:-1], EXE, "3.1.7", WEB)
    with pytest.raises(ValueError, match="ABI"):
        gate.verify([wheels[0], wheels[0], *wheels[2:]], EXE, "3.1.7", WEB)


@pytest.mark.parametrize("member,replacement,message", [
    ("eqnedit64/EqnEdit64.exe", b"changed executable", "executable"),
    ("eqnedit64/web/equation-editor.js", b"canonical web bytes\r\n", "Web bytes"),
    ("eqnedit64-3.1.7.dist-info/METADATA", b"Name: EqnEdit64\nVersion: 3.1.6\n", "version"),
])
def test_payload_changes_fail_even_with_valid_record(tmp_path, member, replacement, message):
    wheel = make_wheel(tmp_path, "cp310", lambda m: m.update({member: replacement}))
    with pytest.raises(ValueError, match=message):
        gate.verify([wheel], EXE, "3.1.7", WEB, ("3.10",))


def test_record_tamper_is_rejected(tmp_path):
    wheel = make_wheel(tmp_path, "cp310")
    with zipfile.ZipFile(wheel) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
    key = next(n for n in members if n.endswith("/RECORD"))
    members[key] = members[key].replace(b"sha256=", b"sha512=", 1)
    with zipfile.ZipFile(wheel, "w") as archive:
        for n, data in members.items(): archive.writestr(n, data)
    with pytest.raises(ValueError, match="RECORD"):
        gate.verify([wheel], EXE, "3.1.7", WEB, ("3.10",))

def test_windows_checkout_preserves_canonical_web_bytes(tmp_path):
    import subprocess
    names = ("equation-editor.js", "equation-editor.fragment.html")
    subprocess.run(["git", "-C", str(ROOT), "-c", "core.autocrlf=true", "checkout-index",
                    "--prefix=" + tmp_path.as_posix() + "/", "--", *["web/" + n for n in names]], check=True)
    for name in names:
        actual = (tmp_path / "web" / name).read_bytes()
        expected = subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "blob", "HEAD:web/" + name])
        assert actual == expected, name
        assert b"\r" not in actual, name


@pytest.mark.parametrize("kind", ["url", "license", "python", "pure", "extra"])
def test_reviewer_metadata_and_member_bypasses_rejected(tmp_path, kind):
    def change(m):
        meta = "eqnedit64-3.1.7.dist-info/METADATA"
        wheel = "eqnedit64-3.1.7.dist-info/WHEEL"
        if kind == "url":
            m[meta] = m[meta].replace(b"https://github.com/ksugahar/EqnEdit64", b"https://example.invalid/other")
        elif kind == "license":
            m[meta] = b"\n".join(line for line in m[meta].split(b"\n") if not line.startswith(b"License-Expression:"))
        elif kind == "python":
            m[meta] = b"\n".join(line for line in m[meta].split(b"\n") if not line.startswith(b"Requires-Python:"))
        elif kind == "pure": m[wheel] = m[wheel].replace(b"Root-Is-Purelib: false", b"Root-Is-Purelib: true")
        else: m["eqnedit64/old/EqnEdit64.exe"] = b"unexpected"
    wheel = make_wheel(tmp_path, "cp310", change)
    with pytest.raises(ValueError): gate.verify([wheel], EXE, "3.1.7", WEB, ("3.10",))


def test_postapproval_report_detects_changed_bytes(tmp_path):
    standalone = tmp_path / "standalone"
    standalone.mkdir()
    for name in ("EqnEdit64.exe", "EqnEdit64.release.json", "SHA256SUMS.txt"):
        (standalone / name).write_bytes(b"synthetic")
    wheels = tmp_path / "wheels"; wheels.mkdir()
    make_wheel(wheels, "cp310")
    args = ({"wheels": 1}, wheels, standalone / "EqnEdit64.exe", "a"*40, "3.1.7")
    report = gate.bind_report(*args)
    assert gate.bind_report(*args, previous=report) == report
    (standalone / "SHA256SUMS.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="pre-approval"): gate.bind_report(*args, previous=report)
