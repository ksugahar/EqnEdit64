import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("privacy", Path(__file__).resolve().parents[1] / "tools/privacy_lint.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def test_public_source_and_private_locations():
    assert not mod.findings("src/editor.cpp", b"TeX and Office OOXML")
    assert "absolute-drive" in mod.findings("x", b"W" + b":/private/file")
    assert "absolute-drive" in mod.findings("x", ("C" + ":\\Users\\person").encode("utf-16-le"))
