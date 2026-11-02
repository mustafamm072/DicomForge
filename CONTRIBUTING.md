# Contributing

Thank you for helping make DICOMForge safer and more useful.

## Development Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
PYTHONPATH=src python -m unittest
```

## Project Rules

- Keep the core package dependency-light.
- Prefer explicit DICOM boundaries over claiming unsupported conformance.
- Add tests for every user-visible behavior change.
- Do not commit real patient data or DICOM files containing PHI.
- Prefer small, focused modules over broad abstractions.

## DICOM Changes

When adding DICOM behavior, include one of:

- a reference to the DICOM part/table used
- a test that captures the expected behavior
- documentation in `docs/conformance.md` explaining the current boundary

Full clinical conformance work should also update the compatibility matrix and
conformance notes.

## Documentation Checklist

Every pull request that adds or changes user-visible behavior must also update:

- `CHANGELOG.md` — an entry under the upcoming release
- `docs/conformance.md` — the current scope / out of scope boundary for the
  affected module
- `docs/compatibility.md` — the capability status table, if a row exists or a
  capability moves from planned to implemented

Stale documentation is treated as a bug; features that ship without these
updates will be asked to add them before merge.

## Required release checks (0.12+)

- Run `python -m unittest`, including subprocess CLI tests.
- Run `python -m ruff check src tests tools` and `python -m mypy src/dicomforge`.
- Build a wheel/source archive and test the installed wheel, not just PYTHONPATH.
- Verify core-only import, dictionary/type-marker packaging, and optional extras
  on Python 3.9–3.14. `tools/check_matrix.py --help` documents the local runner.
- Verify pydicom 2.4 separately from current pydicom, and both read/write backend
  directions whenever file or compressed-pixel representation changes.
- Record skipped tests and remaining deployment limits. Passing synthetic tests
  is not vendor/PACS certification. Do not describe unchecked scopes as passed.
- Changes to release policies, dictionary snapshots, or UID mapping strategies
  need version/migration notes and reproducibility evidence.
