"""Publication text is generated and the exact packaged bytes fail closed."""
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import release_version as versions
import check_release_versions as gate


def test_generated_version_fields_and_single_source(tmp_path):
    versions.generate(check=True)
    for name in ["python/pyproject.toml", *(name for name, _ in versions.generated())]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    p = tmp_path / "python/pyproject.toml"
    p.write_text(p.read_text().replace('version = "3.1.7"', 'version = "4.5.6"'))
    with pytest.raises(ValueError, match="Regenerate"):
        versions.generate(tmp_path, check=True)
    versions.generate(tmp_path)
    versions.generate(tmp_path, check=True)
    assert 'var BUILD = "4.5.6";' in (tmp_path / "web/equation-editor.js").read_text()
    assert 'TUPLE 4,5,6,0' in (tmp_path / "src/eqnedit64_version.h").read_text()
    assert 'Source version: **4.5.6**.' in (tmp_path / "python/README.md").read_text()


def block(key, value=b"", children=b"", text=False):
    head = struct.pack("<HHH", 0, len(value)//2 if text else len(value), int(text))
    raw = head + (key+"\0").encode("utf-16le")
    raw += b"\0" * (-len(raw) % 4)
    raw += value
    raw += b"\0" * (-len(raw) % 4)
    raw += children
    return struct.pack("<H", len(raw)) + raw[2:]


def executable(value="3.1.7"):
    fields = b"".join(block(k, (value+"\0").encode("utf-16le"), text=True)
                      for k in ("FileVersion", "ProductVersion"))
    blob = block("VS_VERSION_INFO", children=block("StringFileInfo", children=block("040904b0", children=fields)))
    data = bytearray(0x400+len(blob))
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x86, 1)
    struct.pack_into("<H", data, 0x94, 240)
    struct.pack_into("<H", data, 0x98, 0x20b)
    struct.pack_into("<II", data, 0x98+112+16, 0x1000, len(data)-0x200)
    struct.pack_into("<IIII", data, 0x98+240+8, len(data)-0x200, 0x1000, len(data)-0x200, 0x200)
    # Type16 -> name1 -> language -> data entry.
    for at, key, child in [(0x200,16,0x80000020),(0x220,1,0x80000040),(0x240,1033,0x60)]:
        struct.pack_into("<HH", data, at+12, 0, 1)
        struct.pack_into("<II", data, at+16, key, child)
    struct.pack_into("<IIII", data, 0x260, 0x1200, len(blob), 0, 0)
    data[0x400:] = blob
    return bytes(data)


def wheel(path, marker=None, target="metadata"):
    metadata = "Metadata-Version: 2.1\nName: eqnedit64\nClassifier: Development Status :: 4 - Beta\nVersion: 3.1.7\n\nSource version: **3.1.7**.\n"
    js = 'var BUILD = "3.1.7";'
    html = '<div data-equation-editor></div>'
    exe = executable()
    if marker:
        if target == "metadata": metadata += f"Source version: 3.1.7 ({marker})"
        elif target == "js": js = f'var BUILD = "3.1.7 {marker}";'
        elif target == "html": html += f'<span>3.1.7 {marker}</span>'
        elif target == "exe": exe = executable(f"3.1.7 {marker}")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("eqnedit64-3.1.7.dist-info/METADATA", metadata)
        z.writestr("eqnedit64/web/equation-editor.js", js)
        z.writestr("eqnedit64/web/equation-editor.fragment.html", html)
        z.writestr("eqnedit64/Eqnedit64.exe", exe)


def test_final_artifacts_and_api_names_are_accepted(tmp_path):
    p = tmp_path / "release.whl"
    wheel(p)
    gate.check(p, "3.1.7")
    exe = tmp_path / "Eqnedit64.exe"
    exe.write_bytes(executable()+b"ImmGetCandidateListW")
    gate.check(exe, "3.1.7")
    manifest = tmp_path / "Eqnedit64.release.json"
    manifest.write_text(json.dumps({"version":"3.1.7", "tag":"v3.1.7"}))
    gate.check(manifest, "3.1.7")


@pytest.mark.parametrize("marker", ["candidate", "unreleased", "dev", ".dev1"])
@pytest.mark.parametrize("target", ["metadata", "js", "html", "exe", "manifest"])
def test_rejects_development_labels_in_each_publication_surface(tmp_path, marker, target):
    if target == "manifest":
        path = tmp_path / "Eqnedit64.release.json"
        path.write_text(json.dumps({"version":f"3.1.7 {marker}", "tag":"v3.1.7"}))
    else:
        path = tmp_path / "release.whl"
        wheel(path, marker, target)
    with pytest.raises(ValueError, match="Development version marker"):
        gate.check(path, "3.1.7")


def test_gate_rejects_mismatched_or_missing_payload(tmp_path):
    path = tmp_path / "release.whl"
    wheel(path)
    with pytest.raises(ValueError): gate.check(path, "3.1.8")
    with zipfile.ZipFile(path, "w") as z: z.writestr("placeholder", "empty")
    with pytest.raises(ValueError): gate.check(path, "3.1.7")


def test_backend_generates_before_metadata(monkeypatch):
    import types
    fake_backend = types.SimpleNamespace(prepare_metadata_for_build_wheel=lambda *args: None)
    monkeypatch.setitem(sys.modules, "scikit_build_core", types.SimpleNamespace(build=fake_backend))
    spec = importlib.util.spec_from_file_location("release_backend", ROOT / "python/build_backend/release_backend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    order = []
    monkeypatch.setattr(module, "prepare", lambda: order.append("generate"))
    monkeypatch.setattr(module.backend, "prepare_metadata_for_build_wheel", lambda *args: order.append("metadata"))
    module.prepare_metadata_for_build_wheel("unused")
    assert order == ["generate", "metadata"]


def test_release_workflow_gates_artifacts_before_approval_and_publish():
    import yaml
    data = yaml.load((ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text(), Loader=yaml.BaseLoader)
    for job in ("signed-standalone", "build-wheels", "publish"):
        steps = data["jobs"][job]["steps"]
        gates = [i for i, step in enumerate(steps) if "tools/check_release_versions.py" in step.get("run", "")]
        boundaries = [i for i, step in enumerate(steps) if step.get("uses", "").startswith(("actions/upload-artifact@", "pypa/gh-action-pypi-publish@"))]
        assert gates and boundaries and max(gates) < min(boundaries), job
