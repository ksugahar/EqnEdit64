# Eqnedit64

Source version: **3.1.6** is the first independent-repository candidate; not released yet.
Eqnedit64 is a portable Windows TeX equation editor with native, Python and Web interfaces.

## Build and use

Use Visual Studio Build Tools 2022/MSVC14.44 and CMake from this root:

```sh
cmake -S . -B build_cmake -A x64
cmake --build build_cmake --config Release --parallel 2
ctest --test-dir build_cmake -C Release --output-on-failure
```

Set `EQNEDIT64_RELEASE_EXE` to the verified executable and run
`python -m build --wheel python` for wheels. Signing is a separate controlled step.
`Eqnedit64.exe input.tex output.pptxmath` exports editable Office OOXML math.
The Python helper is `eqnedit64.export_powerpoint_math(tex, output)`.
Unsupported conversion raises an error.

See [CLI](docs/COMMAND_LINE.md), [GUI](docs/GUI_SPEC.md) and
[Office math](docs/POWERPOINT_MATH.md). Canonical browser code is in `web/`.
Regression checks live in `tests/`. Independent native/Office release validation
requires a separately scheduled exact-artifact run. Content lint is not Office acceptance.
