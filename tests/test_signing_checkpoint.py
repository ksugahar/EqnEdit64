"""Synthetic PE layouts independently exercise the signing-only byte boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("checkpoint", ROOT / "tools/signing_checkpoint.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def unsigned():
    data = bytearray(513)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 84, 240)
    struct.pack_into("<H", data, 88, 0x20b)
    struct.pack_into("<I", data, 196, 16)
    data[-1] = 37
    return bytes(data)


def signed(data):
    result = bytearray(data + bytes((-len(data)) % 8))
    offset = len(result)
    struct.pack_into("<I", result, 152, 1234)  # PE checksum legitimately changes.
    struct.pack_into("<II", result, 232, offset, 16)
    result.extend(struct.pack("<IHH", 16, 0x200, 2) + b"testcert")
    return bytes(result)


def inputs(tmp_path):
    exe = tmp_path / "editor.exe"
    raw = unsigned(); exe.write_bytes(raw)
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps({"source_commit": "a" * 40, "app_sha256": hashlib.sha256(raw).hexdigest(),
        "background_suite": "passed", "asan_suite": "passed", "gui_endurance": {"total_operations": 500000, "timeout_seconds": 1800, "seeds": 100, "operations_per_seed": 5000}}))
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps(mod.record("a" * 40, exe, acceptance)))
    exe.write_bytes(signed(raw))
    return exe, acceptance, checkpoint


def test_signing_only_bytes_match(tmp_path):
    exe, report, saved = inputs(tmp_path)
    assert mod.verify("a" * 40, exe, report, saved)["payload_matches"]


@pytest.mark.parametrize("mutation", ["code", "overlay", "padding", "certificate", "source", "report", "missing"])
def test_mutated_payload_or_provenance_fails(tmp_path, mutation):
    exe, report, saved = inputs(tmp_path)
    data = bytearray(exe.read_bytes())
    sha = "a" * 40
    if mutation == "code": data[400] ^= 1
    if mutation == "overlay": data.extend(b"extra")
    if mutation == "padding": data[514] = 1
    if mutation == "certificate": data[520] = 255
    if mutation == "source": sha = "b" * 40
    if mutation == "report": report.write_text("{}")
    if mutation == "missing": saved.unlink()
    exe.write_bytes(data)
    with pytest.raises((ValueError, FileNotFoundError)): mod.verify(sha, exe, report, saved)


def test_unsigned_qualification_cannot_skip_gates(tmp_path):
    exe, report, saved = inputs(tmp_path)
    exe.write_bytes(unsigned())
    data = json.loads(report.read_text()); data["asan_suite"] = "skipped"
    report.write_text(json.dumps(data))
    with pytest.raises(ValueError): mod.record("a" * 40, exe, report)


def test_second_certificate_entry_is_rejected(tmp_path):
    exe, report, saved = inputs(tmp_path)
    data = bytearray(exe.read_bytes())
    offset, length = struct.unpack_from("<II", data, 232)
    data.extend(struct.pack("<IHH", 16, 0x200, 2) + b"arbitrary")
    # Keep the forged second entry aligned and correct its declared length.
    data = data[:offset + length] + struct.pack("<IHH", 16, 0x200, 2) + b"payload!"
    struct.pack_into("<II", data, 232, offset, length + 16)
    exe.write_bytes(data)
    with pytest.raises(ValueError): mod.verify("a" * 40, exe, report, saved)


@pytest.mark.parametrize("field", ["asan", "background", "operations", "timeout", "source", "unsigned_hash"])
def test_verify_rechecks_acceptance_even_with_updated_report_hash(tmp_path, field):
    exe, report, saved = inputs(tmp_path)
    result = json.loads(report.read_text())
    if field == "asan": result["asan_suite"] = "skipped"
    if field == "background": result["background_suite"] = "skipped"
    if field == "operations": result["gui_endurance"]["total_operations"] = 1
    if field == "timeout": result["gui_endurance"]["timeout_seconds"] = 3600
    if field == "source": result["source_commit"] = "b" * 40
    if field == "unsigned_hash": result["app_sha256"] = "0" * 64
    report.write_text(json.dumps(result))
    checkpoint = json.loads(saved.read_text())
    checkpoint["acceptance_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    saved.write_text(json.dumps(checkpoint))
    with pytest.raises(ValueError): mod.verify("a" * 40, exe, report, saved)


@pytest.mark.parametrize("setting", [["-EnduranceSeeds", "99"], ["-EnduranceOps", "1"], ["-EnduranceTimeoutSeconds", "3600"]])
def test_nonstandard_gate_settings_fail_before_session_or_build(tmp_path, setting):
    import shutil
    import subprocess
    shell = shutil.which("pwsh")
    if not shell: pytest.skip("PowerShell required")
    result = subprocess.run([shell, "-NoProfile", "-File", str(ROOT / "build/accept_release.ps1"),
        "-Phase", "Unsigned", "-CheckpointPath", str(tmp_path / "checkpoint.json"), *setting], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Release gate requires" in result.stdout + result.stderr
    assert not (tmp_path / "checkpoint.json").exists()
