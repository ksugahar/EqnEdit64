# Eqnedit64 Python package

Source version: **3.1.7**. Windows wheels contain the native extension,
the verified signed standalone executable and canonical Web files.

```python
from eqnedit64 import export_powerpoint_math
export_powerpoint_math(r"x^2", "equation.pptxmath")
```

Build from the repository root with `EQNEDIT64_RELEASE_EXE` set to the exact verified
executable: `python -m build --wheel python`. Unsupported inputs raise.
See the repository README and docs/COMMAND_LINE.md for the public contract.
