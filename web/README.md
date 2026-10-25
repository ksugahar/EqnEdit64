# Web equation editor

`equation-editor.js` and `equation-editor.fragment.html` are the canonical browser implementation.
Use the product Git repository only to export the exact reviewed release tag with `git cat-file blob`.
Do not publish working-tree files: checkout filters may alter their bytes.

For the homepage builder, set the job-local `EQNEDIT64_REPOSITORY` to the exported directory,
then run `python site_builder/tools/build_site.py --equation-editor-only` in the website workspace.
For release verification, use `python site_builder/tools/ci_equation_editor.py`
with `--eqnedit64-repository <export> --canonical-repository <git-repository>`
and `--expected-tag v<version> --profile static`; the checker owns these arguments, not the builder.
After the release is public, also pass `--verify-download --expected-exe-sha256 <signed-exe-sha256>`.
The website must check exact source blob bytes and update the matching executable download and source links.

The shared interaction contract is [product parity](../docs/PRODUCT_PARITY.md).
Native/Web clipboard byte regression and real-browser tests are distinct from actual Office acceptance.
Verify SHA-256 and exact bytes against the canonical tag assets.
Do not retain or edit an independent homepage source copy.
