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
    p.write_text(p.read_text(encoding="utf-8").replace(f'version = "{versions.version()}"', 'version = "4.5.6"', 1), encoding="utf-8")
    with pytest.raises(ValueError, match="Regenerate"):
        versions.generate(tmp_path, check=True)
    versions.generate(tmp_path)
    versions.generate(tmp_path, check=True)
    assert 'var BUILD = "4.5.6";' in (tmp_path / "web/equation-editor.js").read_text(encoding="utf-8")
    assert 'TUPLE 4,5,6,0' in (tmp_path / "src/eqnedit64_version.h").read_text(encoding="utf-8")
    assert 'Source version: **4.5.6**.' in (tmp_path / "python/README.md").read_text(encoding="utf-8")


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
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000,
                        0x00030001, 0x00070000, 0x00030001, 0x00070000,
                        0x3f, 0, 0x00040004, 1, 0, 0, 0)
    blob = block("VS_VERSION_INFO", value=fixed, children=block("StringFileInfo", children=block("040904b0", children=fields)))
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
        z.writestr("eqnedit64/EqnEdit64.exe", exe)


def test_final_artifacts_and_api_names_are_accepted(tmp_path):
    p = tmp_path / "release.whl"
    wheel(p)
    gate.check(p, "3.1.7")
    exe = tmp_path / "EqnEdit64.exe"
    exe.write_bytes(executable()+b"ImmGetCandidateListW")
    gate.check(exe, "3.1.7")
    manifest = tmp_path / "EqnEdit64.release.json"
    manifest.write_text(json.dumps({"version":"3.1.7", "tag":"v3.1.7"}))
    gate.check(manifest, "3.1.7")


@pytest.mark.parametrize("marker", ["candidate", "unreleased", "dev", ".dev1"])
@pytest.mark.parametrize("target", ["metadata", "js", "html", "exe", "manifest"])
def test_rejects_development_labels_in_each_publication_surface(tmp_path, marker, target):
    if target == "manifest":
        path = tmp_path / "EqnEdit64.release.json"
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
    data = yaml.load((ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    for job in ("signed-standalone", "build-wheels", "publish"):
        steps = data["jobs"][job]["steps"]
        gates = [i for i, step in enumerate(steps) if "tools/check_release_versions.py" in step.get("run", "")]
        boundaries = [i for i, step in enumerate(steps) if step.get("uses", "").startswith(("actions/upload-artifact@", "pypa/gh-action-pypi-publish@"))]
        assert gates and boundaries and max(gates) < min(boundaries), job


def test_additional_packaged_web_labels_are_not_ignored(tmp_path):
    path = tmp_path / "release.whl"
    wheel(path)
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("eqnedit64/web/version.html", "<span>3.1.7 candidate</span>")
    with pytest.raises(ValueError, match="Development version marker"):
        gate.check(path, "3.1.7")


@pytest.mark.parametrize("label", ["candidate版", "未公開", "候補版", "開発版", "unreleased", "dev1"])
def test_labels_after_regex_and_in_template_strings_fail(label):
    text = 'var BUILD = "3.1.7"; var pattern = /\\"/g; const label = `' + label + '`;'
    with pytest.raises(ValueError):
        gate.web(text.encode("utf-8"), "equation-editor.js", "3.1.7")


def test_escaped_labels_in_js_and_decoded_json_fail(tmp_path):
    for escaped in (r"\u0063andidate", r"\u{63}andidate", r"\x63andidate"):
        text = 'var BUILD = "3.1.7"; var pattern = /\\"/g; var label = "' + escaped + '";'
        with pytest.raises(ValueError):
            gate.web(text.encode("utf-8"), "equation-editor.js", "3.1.7")
    path = tmp_path / "EqnEdit64.release.json"
    path.write_text(r'{"version":"3.1.7","tag":"v3.1.7","nested":[{"channel":"\u0063andidate"}]}', encoding="utf-8")
    with pytest.raises(ValueError):
        gate.check(path, "3.1.7")


def test_pe_fixed_numeric_version_flags_and_extra_labels_fail(tmp_path):
    exe = tmp_path / "EqnEdit64.exe"
    original = executable()
    signature = original.index(struct.pack("<I", 0xFEEF04BD))
    for offset, replacement in [(0, 0), (8, 0x00030009), (16, 0x00030009), (28, 2)]:
        bad = bytearray(original)
        struct.pack_into("<I", bad, signature+offset, replacement)
        exe.write_bytes(bad)
        with pytest.raises(ValueError): gate.check(exe, "3.1.7")
    # Same UTF-16 length replacement in a non-version string field name/value.
    bad = original.replace("FileVersion".encode("utf-16le"), "SpecialBldX".encode("utf-16le"))
    bad = bad.replace("3.1.7".encode("utf-16le"), "dev.7".encode("utf-16le"), 1)
    exe.write_bytes(bad)
    with pytest.raises(ValueError): gate.check(exe, "3.1.7")


def test_contextual_prerelease_names_and_legitimate_preview_math():
    for text in ("3.1.7rc1", "3.1.7 (beta)", "preview 3.1.7", "3.1.7 dev_build", "3.1.7 候補"):
        with pytest.raises(ValueError): gate.clean(text, "version label")
    gate.clean(r"\beta preview devicePixelRatio candidateList ImmGetCandidateListW", "ordinary UI/code")


def test_dependency_order_and_nonmutating_build_paths():
    import yaml
    flow = yaml.load((ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    runs = [step.get("run", "") for step in flow["jobs"]["build-wheels"]["steps"]]
    install = next(i for i, text in enumerate(runs) if "pip install -r ci-requirements.txt" in text)
    check = next(i for i, text in enumerate(runs) if "tools/release_version.py --check" in text)
    assert install < check, "Python 3.10 needs tomli before importing the generator"
    assert "release_version.py --check" in (ROOT / "build/build_eqnedit64.bat").read_text(encoding="utf-8")
    for name in ("CMakeLists.txt", "python/CMakeLists.txt"):
        assert 'tools/release_version.py" --check' in (ROOT / name).read_text(encoding="utf-8")


def test_html_entity_version_label_is_rejected():
    with pytest.raises(ValueError):
        gate.web(b"<span>3.1.7 &#99;andidate</span>", "equation-editor.fragment.html", "3.1.7")
