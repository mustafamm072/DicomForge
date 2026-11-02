# 0.12 verification — November 1, 2026

The implementation was tested locally on macOS arm64 before committing. The
same wheel was installed in fresh isolated environments; source PYTHONPATH was
removed for installed-wheel tests. Local loopback networking was enabled so the
networking tests executed rather than skipping due to sandbox restrictions.

| Python | Core wheel | Optional integrations | Tests per run |
| --- | --- | --- | --- |
| 3.9.25 | Pass; 29 optional skips | Pass; no skips | 391 |
| 3.10.20 | Pass; 29 optional skips | Pass; no skips | 391 |
| 3.11.14 | Pass; 29 optional skips | Pass; no skips | 391 |
| 3.12.13 | Pass; 29 optional skips | Pass; no skips | 391 |
| 3.13.12 | Pass; 29 optional skips | Pass; no skips | 391 |
| 3.14.3 | Pass; 29 optional skips | Pass; no skips | 391 |

A separate Python 3.10.20 environment with **pydicom 2.4.4** also passed all
391 tests without skips. Core mode installs no optional packages. Extras mode
installs resolver-compatible pydicom, NumPy, Pillow, requests and pynetdicom.

The suite includes real CLI subprocesses for inventory, validation, dry-run
planning, release, resume, safe error output and failure exit codes. Each matrix
run also checks the installed console script and module entry point, the bundled
dictionary, py.typed, package version and absence of heavy imports on core import.
The standalone synthetic research-release example also passes.

Ruff, strict core mypy 1.15, compileall, wheel/source builds and git diff whitespace
checks pass. The development pytest run passes too; optional socket tests are
skipped only when that run uses the sandbox, and are covered by the unrestricted
installed-wheel matrix. Existing upstream deprecation warnings are not failures.

[Machine-readable evidence](verification-0.12.json) records all thirteen runs and
artifact identity. The tested wheel is 154,340 bytes and has SHA-256:

```
2f274237339d597b97e87f48da7b13e65912d55099acafd23195514babf5a670
```

Reproduce the matrix with `tools/check_matrix.py --help`. CI now builds/installs
wheels for the same six Python versions, both core and extras, and separately
checks legacy pydicom and code quality. The GitHub-hosted run will occur only
after push; local verification cannot guarantee an external runner's result.

## Repaired review findings

- Nested pydicom values and encapsulated pixels share normalized representations.
- Default audits/repr are value-free; explicit sensitive diagnostics are separate.
- Native endian changes preserve pixel values, including nested binary VRs.
- Signed stored-bit values and modality-before-VOI display are corrected.
- Atomic/no-clobber writes, batch collision checks and source protection prevent
  the reproduced overwrite/data-loss paths.
- UID grammar and root capacity are checked; keyed mapping is versioned.
- Explicit VRs and unchanged numeric lexical forms survive adapters and writes.
- Truncated containers/multipart and allocation-budget violations fail explicitly.
- Empty Type 1 values and missing Type 2 attributes produce errors.
- JSON VR/PN/null/bulk references, retry replay safety, stream closure and STOW
  per-instance outcomes have regressions.
- Research releases verify policy/key identity, unchanged source membership,
  output integrity, longitudinal linkage and interrupted-job resume.

## Boundaries retained deliberately

This release adds complete local workflows within a narrow declared scope. It
does not claim complete IOD/module/PS3.15 coverage, enhanced/multiframe geometry,
OCR/recognizable-anatomy processing, or certified PACS compatibility. No live
Orthanc/dcm4chee deployment or external clinical corpus was used. Those require
separate integration evidence and are tracked in the roadmap. The historical
JSON networking simulator remains experimental; production DIMSE uses pynetdicom.
