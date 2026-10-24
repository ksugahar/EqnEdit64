# Release version contract

`python/pyproject.toml` is the release version source. Only final `major.minor.patch`
values are accepted. Run `python tools/release_version.py` after changing it.
The generator updates the native header used by the window title and VERSIONINFO,
the JS BUILD label, both README source-version lines, the GUI document target and the Python package version.
Generated copies are checked in so a website can import the exact reviewed tag
without retaining a separately edited copy. `--check` rejects stale generated fields.

Native batch and CMake builds recompute and check generated text before resource compilation,
without repairing a stale tracked source tree in place. The wheel backend performs
the same check before metadata preparation and wheel construction,
so METADATA reads the generated README; the Python CMake path also invokes it.
Python 3.10 uses the pinned TOML parser build dependency.

`tools/check_release_versions.py --artifact <path>` accepts repeated artifacts.
The release workflow checks the staged EXE VERSIONINFO, release manifest and Web
files before handing the EXE to wheel jobs, every built wheel before upload, and
all downloaded artifacts again before publication. It rejects development labels
in metadata text, Unicode-decoded full JS text, HTML and decoded manifest keys/values.
It checks all PE VERSIONINFO text, the fixed block signature, numeric file/product
versions and final file flags without executing the executable. A local JS variable
is named neutrally so the complete text scan needs no identifier exemption.
Alpha/beta/rc/preview are rejected when attached to a version number; ordinary
mathematical beta and UI preview identifiers are unaffected.
Internal identifiers and API names are not version labels; the standard Trove
Development Status classifier is not a version label either. Expected final
versions must match the canonical release version exactly. Missing wheel metadata,
required Web/EXE members and PE version resources fail closed.

The gate does not replace signature/pin validation, source and artifact audits,
exact-byte signing checkpoint, native/Office acceptance, four-wheel inspection,
or the protected publication-environment approval. A new version requires a new
exact-source qualification and signed draft; older qualification is not reused.
