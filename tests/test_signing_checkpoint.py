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
        "background_suite": "passed", "asan_suite": "passed", "gui_endurance": {"total_operations": 500000, "timeout_seconds": 3600}}))
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
