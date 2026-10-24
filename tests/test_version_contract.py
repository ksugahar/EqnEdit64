"""The PE numeric version must not lag the visible/package version."""
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "python"


def test_version_contract():
    version = tomllib.loads((PACKAGE / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    major, minor, patch = map(int, version.split("."))
    header = (ROOT / "src/eqnedit64_version.h").read_text("utf-8")
    for key, value in (("MAJOR", major), ("MINOR", minor), ("PATCH", patch)):
        assert re.search(rf"#define EQNEDIT64_VERSION_{key}\s+{value}\b", header)
    assert f'#define EQNEDIT64_VERSION_TUPLE {major},{minor},{patch},0' in header
    assert f'#define EQNEDIT64_VERSION_TEXT "{version}"' in header
    assert f'#define EQNEDIT64_VERSION_TEXT_W L"{version}"' in header
    assert f'__version__ = "{version}"' in (PACKAGE / "src/eqnedit64/__init__.py").read_text("utf-8")
    assert 'project(Eqnedit64 VERSION ${EQNEDIT64_VERSION} ' in (ROOT / "CMakeLists.txt").read_text("utf-8")
    assert f'var BUILD = "{version}";' in (ROOT / "web/equation-editor.js").read_text("utf-8")
    for changelog in [ROOT / "docs/CHANGELOG.md"]:
        assert re.search(rf"^## {re.escape(version)}(?: |$)", changelog.read_text("utf-8"), re.M)
    for readme in [ROOT / "README.md", PACKAGE / "README.md"]:
        assert f"Source version: **{version}**" in readme.read_text("utf-8")
    assert f"- 対象: Eqnedit64 {version}" in (ROOT / "docs/GUI_SPEC.md").read_text("utf-8")



def test_native_corpus_contract_is_complete():
    import json
    corpus = json.loads((ROOT / "tests/office_bit_corpus.json").read_text("utf-8"))
    regressions = json.loads((ROOT / "tests/office_315_contract.json").read_text("utf-8"))["fixtures"]
    combined = corpus + [dict(item, id="315-" + item["id"]) for item in regressions]
    assert len({item["id"] for item in combined}) == len(combined) == 79
    rejected = {item["id"] for item in combined if item.get("coverage") == "excluded"}
    assert rejected == {"boxed", "cancel", "binom"}
    assert len(combined) - len(rejected) == 76


def test_release_context_rejects_cross_repository_and_source_mismatch(tmp_path):
    import json
    import os
    import subprocess
    import sys
    import yaml
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-eqnedit64-pypi.yml").read_text("utf-8"))
    step = next(s for s in workflow["jobs"]["qualify"]["steps"] if s.get("id") == "context")
    source = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    context_dir = tmp_path / "eqnedit64-ci-release-context"
    context_dir.mkdir()
    good = {"schema": "eqnedit64.ci-release-context.v1", "repository": "example/editor", "sha": "a" * 40,
            "run_id": "42", "ref": "refs/tags/v3.1.6", "ref_type": "tag"}
    environment = dict(os.environ, SHA=good["sha"], RUN_ID="42", GITHUB_REPOSITORY=good["repository"])
    for index, (patch, expected_code, eligible) in enumerate([
        ({}, 0, True), ({"repository": "example/another"}, 1, None),
        ({"sha": "b" * 40}, 1, None), ({"run_id": "43"}, 1, None),
        ({"schema": "invalid"}, 1, None), ({"ref": "refs/heads/main", "ref_type": "branch"}, 0, False),
        ({"ref": "refs/tags/not-a-version"}, 0, False),
    ]):
        (context_dir / "context.json").write_text(json.dumps(dict(good, **patch)), encoding="utf-8")
        output = tmp_path / f"output-{index}"
        result = subprocess.run([sys.executable, "-c", source], cwd=tmp_path,
                                env=dict(environment, GITHUB_OUTPUT=str(output)), capture_output=True, text=True)
        assert result.returncode == expected_code, result.stdout + result.stderr
        if eligible is not None:
            assert f"eligible={str(eligible).lower()}" in output.read_text("utf-8")


def _draft_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("draft_assets", ROOT / "tools/download_release_asset.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_draft_selection_fails_closed():
    import pytest
    mod = _draft_module()
    item = {"id": 1, "tag_name": "v3.1.6", "draft": True, "target_commitish": "a" * 40}
    assert mod.select_draft([item], "v3.1.6", "a" * 40) == item
    for releases in [[], [dict(item, draft=False)], [item, item], [dict(item, target_commitish="main")]]:
        with pytest.raises(ValueError): mod.select_draft(releases, "v3.1.6", "a" * 40)
    with pytest.raises(ValueError): mod.select_draft([item], "v3.1.6", "b" * 40)

def test_draft_download_uses_authenticated_api_and_exact_size(tmp_path, monkeypatch):
    import io
    import pytest
    mod = _draft_module()
    asset = {"id": 7, "name": "Eqnedit64.exe", "size": 4, "state": "uploaded",
             "browser_download_url": "https://example.invalid/public-copy"}
    monkeypatch.setattr(mod, "fetch_release", lambda *a: {"assets": [asset]})
    calls = []
    def fake_request(url, binary=False):
        calls.append((url, binary))
        return io.BytesIO(b"data")
    monkeypatch.setattr(mod, "request", fake_request)
    result = mod.download("example/editor", "v3.1.6", "a" * 40, "Eqnedit64.exe", tmp_path, 1)
    assert result.read_bytes() == b"data"
    assert calls == [("https://api.github.com/repos/example/editor/releases/assets/7", True)]
    asset["size"] = 5
    with pytest.raises(ValueError): mod.download("example/editor", "v3.1.6", "a" * 40, "Eqnedit64.exe", tmp_path, 1)
    with pytest.raises(ValueError): mod.download("example/editor", "v3.1.6", "a" * 40, "../unexpected", tmp_path, 1)

def test_asset_redirect_drops_credentials(monkeypatch):
    import pytest
    import urllib.request
    mod = _draft_module()
    req = urllib.request.Request("https://api.github.com/repos/example/editor/releases/assets/7", headers={"Authorization": "Bearer synthetic"})
    redirected = mod.SafeRedirect().redirect_request(req, None, 302, "Found", {}, "https://example.invalid/asset")
    assert redirected.get_header("Authorization") is None
    with pytest.raises(ValueError): mod.SafeRedirect().redirect_request(req, None, 302, "Found", {}, "http://example.invalid/asset")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ValueError): mod.request("https://api.github.com/repos/example/editor/releases")
