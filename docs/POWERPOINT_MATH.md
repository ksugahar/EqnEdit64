# Native PowerPoint math export

Version 3.1.6 is the first independent-repository candidate; not released yet.

```text
Eqnedit64.exe equation.tex equation.pptxmath
```

The output is an XML `m:oMathPara` in the 2006 Office math namespace, with
DrawingML `a:rPr` formatting and canonical Office math `m:t` text runs. It is intended for PowerPoint's `a14:m`
extension, not Word import and not HTML. The serializer shares equation
structure with the normal-copy RichEdit HTML route. Both routes emit matched
visible delimiter pairs as stretchable structures.
ISO `baseJc` is vertical and uses `center` here. Horizontal paragraph
justification remains `left`.

The strict export rejects unsupported commands/environments, invalid colours,
unclosed groups/environments and excessive depth. The known non-covered
boxed, binom and cancel constructs are rejected rather than flattened.
Other unsupported inputs must not be assumed valid simply because the editor
can show them. Function argument collection retains the shared one-atom or
balanced-visible-fence contract; arbitrary TeX parity is not established.

The CLI writes atomically, emits a non-zero exit and a diagnostic including
the input TeX on rejection, and preserves an existing output file. The
`eqnedit64.export_powerpoint_math(tex, output)` helper is a checked subprocess
client with no renderer, clipboard or image fallback. This path does not load
the private rendering font. Office math names Cambria Math, with 18 pt native
runs; no font is embedded into a PPTX.

## Office delimiter layout

Native math paragraph justification is left-aligned.
Matched visible pairs in one row, including plain parentheses, explicit
`\left...\right`, use a stretchable Office delimiter structure. The `\big`, `\Big`, `\bigg`, `\Bigg` commands (plain and `l/r/m` variants)
are fixed-size tokens in both clipboard and strict OOXML output. At the 18 pt
Office base, the four classes use upright symbol runs of 21.6, 32.4, 43.2 and
54.0 pt. They never grow with the operand or become a stretchable `m:d`.
Each fixed symbol is scoped inside its own `m:box` with an 18 pt control
property, so its enlarged font does not change an adjacent fraction's layout.
Native TeX round trips preserve the exact command. MathJax's font-specific
big-family heights are mapped to these shared Office classes; internal
binomial layout is not classified as an explicit size command.
Strict export rejects missing/non-delimiter arguments. Interactive native
parsing ignores an unfinished size command and retains an ordinary token,
so a half-typed command does not make the whole equation invalid.
General `\middle` separators and one-sided fences currently retain visible
characters without stretching; they are outside the stretchable-fence gate.

## Validation and limits

The declared corpus has 79 fixtures: 76 clipboard comparisons and 3 exclusions;
strict OOXML requires 76 checked native fragments and 3 rejections.
The big-family fixture independently checks all 16 commands and
all four fixed run sizes in both clipboard HTML and DrawingML.
Run grouping, control formatting and dialect-specific vertical layout are
normalized; byte identity is not claimed. Independent golden annotations
check functions, upright/bold styles and enclosing nary fences.

Native CI checks atomic CLI errors, shipped math fragments and strict DrawingML
run profiles without rewriting emitted text. SDK limitations are reported separately.
Outer PPTX packaging is the consumer's responsibility. These checks do not certify
actual PowerPoint import. Actual open/edit/save/reopen and clipboard tests are separate
release validation on the exact candidate.

Primary format reference: [Microsoft DrawingML math extension](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/853b19c7-68a9-4f9a-a2ae-5e6cb0d02e62).

Clipboard HTML explicitly declares English for mathematical/control runs and
Japanese for runs containing Japanese kana, CJK ideographs or full-width text.
This prevents inherited unrelated proofing languages without changing Office settings.

Native array column specifications (`\begin{array}{...}`) are unsupported;
use the supported `cases` or `matrix` environments. A single stretchable
delimiter encloses only one balanced group; adjacent groups remain separate.
