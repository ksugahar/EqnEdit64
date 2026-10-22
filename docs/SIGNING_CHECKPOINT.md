# Signed release qualification

Run from a clean committed checkout in the approved test session. The unsigned
phase always rebuilds and runs the complete background and address-sanitizer
suites, 500,000 endurance operations, font lifecycle checks and paint gates.
It stops at a durable checkpoint before any signature is required.

```powershell
pwsh -File build/accept_release.ps1 -Phase Unsigned -CheckpointPath <checkpoint.json> -ReportPath <unsigned-report.json>
```

The maintainer then signs that exact executable and copies the identical signed
bytes to both build/Eqnedit64.exe and dist/Eqnedit64.exe. Keep the unsigned report
and checkpoint unchanged. Complete qualification without rebuilding:

```powershell
pwsh -File build/accept_release.ps1 -Phase Signed -CheckpointPath <checkpoint.json> -UnsignedReportPath <unsigned-report.json> -ReportPath <signed-report.json>
```

The signed phase requires a valid code-signing signature, identical build/dist
bytes, the same source commit, and the completed unsigned report. It compares
all executable bytes except the PE checksum, security directory and appended
certificate table, allowing only zero alignment padding. A modified code or data
byte fails. This comparison supplements Authenticode trust verification; it does
not replace it. Missing records or changed report hashes fail. Neither phase
publishes, stages a deployment copy or creates a tag.

Acceptance of actual Office clipboard paste and published package artifacts
remains a separate release requirement. Never overlap Office testing with a
user's active Office session or manipulate the user's mouse or keyboard.
