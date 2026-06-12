# Compatibility Matrix

## Python Versions

DICOMForge uses `from __future__ import annotations` throughout and targets
Python 3.9+.  All six supported versions are exercised in CI.

| Python | Status |
|--------|--------|
| 3.9    | ✅ Supported — minimum required version (past upstream end-of-life; kept as the floor for long-lived deployments) |
| 3.10   | ✅ Supported |
| 3.11   | ✅ Supported |
| 3.12   | ✅ Supported |
| 3.13   | ✅ Supported |
| 3.14   | ✅ Supported |

No deprecated stdlib modules are used.  `asyncio` calls use `get_running_loop()`
(not the deprecated `get_event_loop()`).  Tests pass cleanly with
`-W error::DeprecationWarning` on Python 3.9 and 3.14.

## Optional Backends

| Backend | Install | Status |
|---------|---------|--------|
| pydicom ≥ 2.4 | `pip install dicomforge[pydicom]` | File IO, conversion, compressed pixel bridge |
| pydicom ≥ 3.0 | same | Supported — uses `pydicom.dcmwrite()` when available |
| numpy ≥ 1.23 | `pip install dicomforge[pixels]` | Pixel arrays and frame iteration |
| Pillow ≥ 10 | `pip install dicomforge[pixels]` | `adapt.to_pil_image`, JPEG preview helpers |
| pynetdicom ≥ 2.0 | `pip install dicomforge[network]` | `adapt.from_pynetdicom_event` bridge |

Install everything at once:

```bash
pip install dicomforge[all]
```

## DICOM Capability Status

| Capability | Current Status |
|------------|-------------|
| Typed tag normalization (100 keywords) | ✅ Implemented |
| Transfer syntax classification (14 syntaxes) | ✅ Implemented |
| Codec capability registry | ✅ Implemented |
| Specific Character Set helpers | ✅ ASCII, UTF-8, ISO 8859, ISO 2022 IR 87/149, GB18030/GBK |
| Person Name component parsing | ✅ `dicomforge.charset.PersonName` |
| Native pixel metadata validation | ✅ Implemented |
| Pixel array extraction — uncompressed | ✅ via `dicomforge.adapt` (requires numpy) |
| Pixel array extraction — compressed | ✅ via pydicom bridge plus codec plugins |
| Multiframe pixel iteration | ✅ `adapt.iter_pixel_frames` |
| Color-space conversion | ✅ RGB/YBR display conversion in `to_pil_image` |
| JPEG preview generation | ✅ `adapt.to_jpeg_preview` / `adapt.from_jpeg_preview` |
| pydicom-backed read/write | ✅ Implemented (pydicom 2.x + 3.x) |
| Starter de-identification plan (48 rules) | ✅ Implemented |
| Full DICOM PS3.15 profile | 🔲 Planned (1.0) |
| Date-shift de-identification action | ✅ `AnonymizationAction.SHIFT_DATE` |
| UID validation and generation | ✅ `is_valid_uid` / `generate_uid` (PS3.5 grammar, UUID-derived `2.25` root) |
| Async command lifecycle (JSON transport) | ✅ Implemented |
| DICOM Upper Layer wire compatibility | 🔲 Planned (dicomforge-network, 1.0) |
| DICOMweb query/client/multipart helpers | ✅ Implemented |
| DICOMweb production transport (auth/retry) | ✅ Implemented |
| pydicom ↔ DicomDataset conversion | ✅ via `dicomforge.adapt` |
| Pillow image display helper | ✅ via `dicomforge.adapt` (requires Pillow) |
| High-level `DicomFile` API | ✅ via `dicomforge.api` |
| `quick_anonymize` one-liner | ✅ via `dicomforge.api` |
| Dataset structural validation | ✅ via `dicomforge.api` |
| Multi-byte character sets (Japanese, Korean, …) | ✅ Explicit helpers plus pydicom write propagation |
| IOD/module validation | ◐ `validate_for_sop_class` covers five common image SOP Classes; full module tables planned (1.0) |

## Commercial Adoption Readiness

The table below summarises which workflow patterns are ready for use in
production software today and which require additional validation or a
planned milestone before they are suitable.

| Workflow | Ready today? | Notes |
|----------|:------------:|-------|
| Research de-identification (non-pixel) | ✅ | Pair with pixel review and governance policy |
| DICOM metadata extraction and inspection | ✅ | `DicomFile`, `DicomDataset`, pydicom adapter |
| DICOMweb QIDO/WADO/STOW integration | ✅ | Inject auth/retry in your `DicomwebTransport` |
| DICOM JSON round-trip | ✅ | `adapt.to_json` / `adapt.from_json` |
| Uncompressed pixel array extraction | ✅ | `adapt.pixel_array` (requires numpy) |
| Display-ready image from DICOM | ✅ | `adapt.to_pil_image` (numpy + Pillow) |
| JPEG thumbnails/API previews | ✅ | `adapt.to_jpeg_preview`; lossy 8-bit previews only |
| Compressed pixel decode | ⚠️ | Requires pydicom plus a codec plugin |
| Wire-compatible DIMSE | ❌ | Planned `dicomforge-network`; use `pynetdicom` now |
| Regulated clinical workflows | ⚠️ | Not a medical device; site validation required |
| Multi-byte patient names (Japanese, …) | ✅ | Explicit helpers; validate real site fixtures before regulated use |
