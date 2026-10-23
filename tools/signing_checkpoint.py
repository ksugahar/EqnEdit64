"""Bind signed PE bytes to a completed unsigned qualification record.

This compares every byte except the PE checksum, security directory and appended
certificate table, allowing only the zero alignment padding needed for signing.
It does not validate certificate trust; the caller must verify Authenticode.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def payload(data, unsigned_size=None):
    def need(ok):
        if not ok: raise ValueError("Unsupported PE certificate layout")
    need(len(data) >= 64 and data[:2] == b"MZ")
    pe = struct.unpack_from("<I", data, 60)[0]
    need(pe + 24 <= len(data) and data[pe:pe + 4] == b"PE\0\0")
    optional = pe + 24
    size = struct.unpack_from("<H", data, pe + 20)[0]
    need(optional + size <= len(data) and size >= 152)
    need(struct.unpack_from("<H", data, optional)[0] == 0x20b)
    need(struct.unpack_from("<I", data, optional + 108)[0] >= 5)
    checksum = optional + 64
    security = optional + 112 + 8 * 4
    offset, length = struct.unpack_from("<II", data, security)
    if unsigned_size is None:
        need(offset == 0 and length == 0)
        end = len(data)
    else:
        need(offset > 0 and offset % 8 == 0 and length >= 8)
        need(offset + length == len(data))
        need(unsigned_size <= offset <= unsigned_size + 7)
        need(data[unsigned_size:offset] == bytes(offset - unsigned_size))
        # Exactly one certificate entry; a second entry can carry unsigned data.
        need(offset + 8 <= len(data))
        n, revision, kind = struct.unpack_from("<IHH", data, offset)
        need(n >= 8 and revision == 0x200 and kind == 2)
        need(offset + ((n + 7) // 8) * 8 == len(data))
        # Bound the PKCS#7 DER object itself, not only its outer certificate entry.
        start = offset + 8
        need(start + 2 <= len(data) and data[start] == 0x30)
        first = data[start + 1]
        if first < 0x80:
            header, body = 2, first
        else:
            count = first & 0x7f
            need(1 <= count <= 4 and start + 2 + count <= len(data))
            encoded = data[start + 2:start + 2 + count]
            need(encoded[0] != 0)
            body = int.from_bytes(encoded, "big")
            need(body >= 0x80)
            header = 2 + count
        der_total = header + body
        expected = 8 + der_total
        need(n in (expected, ((expected + 7) // 8) * 8))
        need(start + der_total <= len(data))
        need(not any(data[start + der_total:]))
        end = unsigned_size
    clean = bytearray(data[:end])
    need(security + 8 <= len(clean))
    clean[checksum:checksum + 4] = bytes(4)
    clean[security:security + 8] = bytes(8)
    return bytes(clean)


def require_acceptance(result, source_sha, unsigned_sha):
    if (result["source_commit"] != source_sha or result["app_sha256"].lower() != unsigned_sha
            or result["background_suite"] != "passed" or result["asan_suite"] != "passed"
            or result["gui_endurance"]["seeds"] != 100
            or result["gui_endurance"]["operations_per_seed"] != 5000
            or result["gui_endurance"]["total_operations"] != 500000
            or result["gui_endurance"]["timeout_seconds"] != 1800):
        raise ValueError("Completed unsigned qualification is required")


def record(source_sha, executable, acceptance):
    acceptance_bytes = acceptance.read_bytes()
    result = json.loads(acceptance_bytes.decode("utf-8-sig"))
    data = executable.read_bytes()
    require_acceptance(result, source_sha, digest(data))
    return {"schema": "eqnedit64.signing-checkpoint.v1", "source_sha": source_sha,
            "unsigned_size": len(data), "unsigned_sha256": digest(data),
            "payload_sha256": digest(payload(data)), "acceptance_sha256": digest(acceptance_bytes)}


def verify(source_sha, executable, acceptance, checkpoint):
    checkpoint_bytes = checkpoint.read_bytes()
    saved = json.loads(checkpoint_bytes.decode("utf-8"))
    acceptance_bytes = acceptance.read_bytes()
    if saved["schema"] != "eqnedit64.signing-checkpoint.v1" or saved["source_sha"] != source_sha:
        raise ValueError("Source checkpoint mismatch")
    if saved["acceptance_sha256"] != digest(acceptance_bytes):
        raise ValueError("Unsigned acceptance record changed")
    require_acceptance(json.loads(acceptance_bytes.decode("utf-8-sig")), source_sha, saved["unsigned_sha256"])
    data = executable.read_bytes()
    if digest(payload(data, saved["unsigned_size"])) != saved["payload_sha256"]:
        raise ValueError("Signed payload differs from qualified unsigned executable")
    return {"source_sha": source_sha, "signed_sha256": digest(data),
            "payload_sha256": saved["payload_sha256"], "checkpoint_sha256": digest(checkpoint_bytes),
            "acceptance_sha256": saved["acceptance_sha256"], "payload_matches": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("record", "verify"))
    p.add_argument("--exe", type=Path, required=True)
    p.add_argument("--acceptance", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        raise SystemExit("Qualification requires a clean committed checkout")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result = record(sha, a.exe, a.acceptance) if a.phase == "record" else verify(sha, a.exe, a.acceptance, a.checkpoint)
    text = json.dumps(result, indent=2)
    target = a.checkpoint if a.phase == "record" else a.output
    if target is None: p.error("--output is required for verify")
    target.write_text(text, encoding="utf-8")
    print(text)
