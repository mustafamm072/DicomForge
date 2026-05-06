# Compatibility Matrix

## Python Versions

DICOMForge uses `from __future__ import annotations` throughout and targets
Python 3.9+.  All five supported versions are exercised in CI.

| Python | Status |
|--------|--------|
| 3.9    | ✅ Supported — minimum required version |
| 3.10   | ✅ Supported |
| 3.11   | ✅ Supported |
| 3.12   | ✅ Supported |
| 3.13   | ✅ Supported |

No deprecated stdlib modules are used.  `asyncio` calls use `get_running_loop()`
(not the deprecated `get_event_loop()`).  Tests pass cleanly with
`-W error::DeprecationWarning` on Python 3.9.

## Optional Backends

| Backend | Install | Status |
|---------|---------|--------|
| pydicom ≥ 2.4 | `pip install dicomforge[pydicom]` | File read/write, pydicom ↔ DicomDataset conversion |
| pydicom ≥ 3.0 | same | Supported — uses `pydicom.dcmwrite()` when available |
| numpy ≥ 1.23 | `pip install dicomforge[pixels]` | `adapt.pixel_array` uncompressed extraction |
| Pillow ≥ 10 | `pip install dicomforge[pixels]` | `adapt.to_pil_image` display helper |
| pynetdicom ≥ 2.0 | `pip install dicomforge[network]` | `adapt.from_pynetdicom_event` bridge |

Install everything at once:

```bash
pip install dicomforge[all]
```

## DICOM Capability Status

| Capability | v0.6 Status |
|------------|-------------|
| Typed tag normalization (75+ keywords) | ✅ Implemented |
| Transfer syntax classification (15 syntaxes) | ✅ Implemented |
| Codec capability registry | ✅ Implemented |
| Native pixel metadata validation | ✅ Implemented |
| Pixel array extraction — uncompressed | ✅ via `dicomforge.adapt` (requires numpy) |
| Pixel array extraction — compressed | 🔲 Planned (0.8) |
| Color-space conversion | 🔲 Planned (0.8) |
| pydicom-backed read/write | ✅ Implemented (pydicom 2.x + 3.x) |
| Starter de-identification plan (48 rules) | ✅ Implemented |
| Full DICOM PS3.15 profile | 🔲 Planned (1.0) |
| Date-shift de-identification action | 🔲 Planned |
| Async command lifecycle (JSON transport) | ✅ Implemented |
| DICOM Upper Layer wire compatibility | 🔲 Planned (dicomforge-network, 1.0) |
| DICOMweb query/client/multipart helpers | ✅ Implemented |
| DICOMweb production transport (auth/retry) | 🔲 Planned (0.7) |
| pydicom ↔ DicomDataset conversion | ✅ via `dicomforge.adapt` |
| Pillow image display helper | ✅ via `dicomforge.adapt` (requires Pillow) |
| High-level `DicomFile` API | ✅ via `dicomforge.api` |
| `quick_anonymize` one-liner | ✅ via `dicomforge.api` |
| Dataset structural validation | ✅ via `dicomforge.api` |
| Multi-byte character sets (Japanese, Korean, …) | 🔲 Planned (0.9) |
| IOD/module validation | 🔲 Planned (1.0) |

## Commercial Adoption Readiness

The table below summarises which workflow patterns are ready for use in
production software today and which require additional validation or a
planned milestone before they are suitable.

| Workflow | Ready today? | Notes |
|----------|:------------:|-------|
| Research data de-identification (non-pixel) | ✅ | Use `quick_anonymize`; pair with pixel review and governance policy |
| DICOM metadata extraction and inspection | ✅ | `DicomFile`, `DicomDataset`, pydicom adapter |
| DICOMweb QIDO/WADO/STOW integration | ✅ | Inject auth/retry in your `DicomwebTransport` |
| DICOM JSON round-trip | ✅ | `adapt.to_json` / `adapt.from_json` |
| Uncompressed pixel array extraction | ✅ | `adapt.pixel_array` (requires numpy) |
| Display-ready image from DICOM (non-compressed) | ✅ | `adapt.to_pil_image` (requires numpy + Pillow) |
| Compressed pixel decode (JPEG, JPEG 2000, …) | ❌ | Planned 0.8; use pydicom + codec backend directly |
| Wire-compatible DIMSE (talk to real PACS) | ❌ | Planned `dicomforge-network`; use `pynetdicom` directly now |
| Regulated clinical workflows (FDA, CE) | ⚠️ | Library is not a medical device; additional site validation required |
| Multi-byte patient names (Japanese, …) | ⚠️ | Delegated to pydicom; explicit support planned 0.9 |
