"""Generic source and package-content inspection, without private identity fixtures."""
import importlib.util
from pathlib import Path
import zipfile

spec = importlib.util.spec_from_file_location("public_content", Path(__file__).with_name("check_public_names.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_generic_text_and_encoded_binary():
    example = "Q" + ":/sample/location"
    for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
        assert module.binary_hits(example.encode(encoding)), encoding
    assert not module.binary_hits(b"Eqnedit64 Office math 3.1.6")

def test_wheel_member_names_metadata_and_native_bytes(tmp_path):
    for name, payload in [("package/native.pyd", ("Q" + ":/sample/location").encode("utf-16-le")),
                          ("package.dist-info/METADATA", b"Certificate: " + b"a" * 40),
                          ("Q" + ":/sample/module", b"public")]:
        archive = tmp_path / "candidate.whl"
        with zipfile.ZipFile(archive, "w") as wheel:
            wheel.writestr(name, payload)
        assert module.artifact_hits(archive), name
