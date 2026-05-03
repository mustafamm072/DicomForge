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
