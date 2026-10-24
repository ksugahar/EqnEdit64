"""Generate release text before the packaging backend reads the README."""
import importlib.util
from pathlib import Path
from scikit_build_core import build as backend


def prepare():
    path = Path(__file__).resolve().parents[2] / "tools/release_version.py"
    spec = importlib.util.spec_from_file_location("release_version", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate(check=True)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    prepare()
    return backend.build_wheel(wheel_directory, config_settings, metadata_directory)


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    prepare()
    return backend.prepare_metadata_for_build_wheel(metadata_directory, config_settings)


def get_requires_for_build_wheel(config_settings=None):
    return backend.get_requires_for_build_wheel(config_settings)


def build_sdist(sdist_directory, config_settings=None):
    raise RuntimeError("Build release wheels from the complete reviewed repository")
