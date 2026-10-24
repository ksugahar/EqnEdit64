# Release version contract

`python/pyproject.toml` is the release version source. Only final `major.minor.patch`
values are accepted. Run `python tools/release_version.py` after changing it.
The generator updates the native header used by the window title and VERSIONINFO,
the JS BUILD label, both README source-version lines and the Python package version.
Generated copies are checked in so a website can import the exact reviewed tag
without retaining a separately edited copy. `--check` rejects stale generated fields.

Native batch and CMake builds invoke the generator before resource compilation.
The wheel backend invokes it before metadata preparation and wheel construction,
so METADATA reads the generated README; the Python CMake path also invokes it.
Python 3.10 uses the pinned TOML parser build dependency.

`tools/check_release_versions.py --artifact <path>` accepts repeated artifacts.
The release workflow checks the staged EXE VERSIONINFO, release manifest and Web
files before handing the EXE to wheel jobs, every built wheel before upload, and
all downloaded artifacts again before publication. It rejects development labels
in metadata text, JS string labels, HTML and manifest text, and checks the PE
FileVersion and ProductVersion resources without executing the executable.
Internal identifiers and API names are not version labels; the standard Trove
Development Status classifier is not a version label either. Expected final
versions must match the canonical release version exactly. Missing wheel metadata,
required Web/EXE members and PE version resources fail closed.

The gate does not replace signature/pin validation, source and artifact audits,
exact-byte signing checkpoint, native/Office acceptance, four-wheel inspection,
or the protected publication-environment approval. A new version requires a new
exact-source qualification and signed draft; older qualification is not reused.
