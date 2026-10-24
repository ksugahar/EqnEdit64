"""Fail closed on development version labels in actual publication artifacts."""
import argparse
from email.parser import Parser
import json
from pathlib import Path
import re
import struct
import zipfile

from release_version import version

MARKER = re.compile(r"(?i)\b(?:candidate|unreleased)\b|(?<![a-z])dev(?:elopment)?(?=\b|[0-9])")


def clean(text, name):
    if MARKER.search(text):
        raise ValueError(f"Development version marker in {name}")


def exact(value, expected, name):
    clean(value, name)
    if value != expected:
        raise ValueError(f"{name}: expected {expected!r}, got {value!r}")


def web(data, name, expected):
    text = data.decode("utf-8-sig")
    if name.endswith(".js"):
        # Identifiers are not version labels; inspect quoted publication strings.
        literals = re.findall(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', text)
        for literal in literals:
            clean(literal, name)
        fields = re.findall(r'\bvar BUILD = "([^"]+)";', text)
        if fields != [expected]:
            raise ValueError(f"{name}: expected one final BUILD {expected!r}, got {fields!r}")
    else:
        clean(text, name)


def pe_versions(data):
    """Read PE RT_VERSION leaves; never execute the binary or scan API names."""
    if data[:2] != b"MZ":
        raise ValueError("Not a PE executable")
    pe = struct.unpack_from("<I", data, 0x3c)[0]
    if data[pe:pe+4] != b"PE\0\0":
        raise ValueError("Invalid PE header")
    sections = struct.unpack_from("<H", data, pe+6)[0]
    optional_size = struct.unpack_from("<H", data, pe+20)[0]
    opt = pe+24
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic not in (0x10b, 0x20b):
        raise ValueError("Unsupported PE optional header")
    directory = opt + (112 if magic == 0x20b else 96)
    resource_rva, resource_size = struct.unpack_from("<II", data, directory+16)
    if not resource_rva or not resource_size:
        raise ValueError("Missing PE resources")

    def offset(rva, size):
        for i in range(sections):
            sh = opt+optional_size+40*i
            virtual_size, address, raw_size, raw = struct.unpack_from("<IIII", data, sh+8)
            if address <= rva and rva+size <= address+raw_size:
                start = raw+rva-address
                if start+size <= len(data):
                    return start
        raise ValueError("Resource RVA outside file sections")

    base = offset(resource_rva, resource_size)
    resource = data[base:base+resource_size]
    def unpack(fmt, at):
        size = struct.calcsize(fmt)
        if at < 0 or at+size > len(resource):
            raise ValueError("Truncated resource directory")
        return struct.unpack_from(fmt, resource, at)

    def leaves(at, depth=0):
        if depth > 2:
            raise ValueError("Unexpected resource directory depth")
        named, ids = unpack("<HH", at+12)
        if named+ids > 4096:
            raise ValueError("Invalid resource count")
        for i in range(named+ids):
            key, value = unpack("<II", at+16+i*8)
            if depth == 0 and key != 16:
                continue
            if value & 0x80000000:
                yield from leaves(value & 0x7fffffff, depth+1)
            else:
                rva, size, _, _ = unpack("<IIII", value)
                start = offset(rva, size)
                yield data[start:start+size]

    values = []
    def blocks(blob, at, limit):
        if at+6 > limit:
            raise ValueError("Truncated VERSIONINFO")
        length, count, kind = struct.unpack_from("<HHH", blob, at)
        end = at+length
        if length < 6 or end > limit:
            raise ValueError("Invalid VERSIONINFO block")
        pos = at+6
        key = []
        while pos+2 <= end:
            code = struct.unpack_from("<H", blob, pos)[0]; pos += 2
            if code == 0:
                break
            key.append(chr(code))
        else:
            raise ValueError("Unterminated VERSIONINFO key")
        key = "".join(key)
        pos = (pos+3) & ~3
        size = count*2 if kind == 1 else count
        if pos+size > end:
            raise ValueError("Truncated VERSIONINFO value")
        if key in ("FileVersion", "ProductVersion"):
            values.append((key, blob[pos:pos+size].decode("utf-16le").rstrip("\0")))
        child = (pos+size+3) & ~3
        while child+6 <= end:
            used = blocks(blob, child, end)
            child = (used+3) & ~3
        return end
    for blob in leaves(0):
        blocks(blob, 0, len(blob))
    if not all(any(key == wanted for key, _ in values) for wanted in ("FileVersion", "ProductVersion")):
        raise ValueError("Missing FileVersion/ProductVersion")
    return values


def check(path, expected):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate wheel members")
            metadata = [n for n in names if n.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Expected exactly one wheel METADATA")
            text = archive.read(metadata[0]).decode("utf-8")
            metadata_text = Parser().parsestr(text)
            # Trove's standard Development Status classifier is not a version label.
            clean("\n".join(line for line in text.splitlines()
                            if not line.startswith("Classifier: Development Status ::")), metadata[0])
            exact(metadata_text["Version"] or "", expected, metadata[0])
            for required in ("eqnedit64/Eqnedit64.exe", "eqnedit64/web/equation-editor.js", "eqnedit64/web/equation-editor.fragment.html"):
                payload = archive.read(required)
                if required.endswith(".exe"):
                    for name, value in pe_versions(payload):
                        exact(value, expected, name)
                else:
                    web(payload, required, expected)
    elif path.suffix.lower() == ".exe":
        for name, value in pe_versions(path.read_bytes()):
            exact(value, expected, name)
    elif path.name.endswith(".release.json"):
        text = path.read_text("utf-8-sig")
        clean(text, path.name)
        record = json.loads(text)
        exact(record["version"], expected, "manifest version")
        exact(record["tag"], "v"+expected, "manifest tag")
    elif path.suffix in (".js", ".html"):
        web(path.read_bytes(), path.name, expected)
    else:
        raise ValueError(f"Unsupported release artifact: {path}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact", type=Path, action="append", required=True)
    args = p.parse_args()
    expected = version()
    for path in args.artifact:
        check(path, expected)
    print(f"PASS: final release version {expected}, artifacts={len(args.artifact)}")


if __name__ == "__main__":
    main()
