# Changelog

All notable changes to DicomForge are documented here.
Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Python 3.14 support: CI matrix and package classifiers now cover 3.9–3.14.
- README examples for date-shift de-identification, `validate_for_sop_class`,
  and the `generate_uid` / `is_valid_uid` helpers.
- Contribution documentation checklist requiring CHANGELOG, conformance, and
  compatibility updates for user-visible changes.

### Fixed
- Documentation corrections: date-shift anonymization, SOP Class validation,
  and UID utilities (shipped in 0.8.0) are now reflected in the conformance
  notes and compatibility matrix; registry counts refreshed (100 keyword tags,
  14 transfer syntaxes, 90+ write VRs, 24 `DicomFile` properties).

## [0.9.0] — 2026-06-10

### Added
- `dicomforge.charset` with dependency-free Specific Character Set helpers:
  `normalize_specific_character_set`, `python_codecs_for_character_set`,
  `preferred_specific_character_set`, `dataset_character_set`, `encode_text`,
  `decode_text`, `can_encode_text`, and `ensure_text_encodable`.
- `PersonName` dataclass plus `coerce_person_name` for VR-aware PN parsing,
  DICOM string formatting, and compact display names.
- `Tag.SpecificCharacterSet` registered as `(0008,0005)` with standard `CS`
  write VR support.
- UTF-8, ISO 2022 IR 87 Japanese, ISO 2022 IR 149 Korean, and GB18030
  Chinese text round-trip tests through Python codecs.
- Write-time charset validation: non-ASCII text without a declared compatible
  `SpecificCharacterSet` raises `CharacterSetError` instead of being passed to
  the backend ambiguously.

### Changed
- `io.write` now writes `SpecificCharacterSet` before other non-file-meta
  elements so pydicom-backed writes can encode following text values using the
  declared character set.
- `io.write` and `adapt.to_pydicom` now format `PersonName` values as DICOM PN
  strings.

## [0.8.1] — 2026-06-10

### Added
- `adapt.to_jpeg_preview` renders one DICOM frame to 8-bit JPEG preview bytes
  using the existing safe pixel path and optional Pillow backend.
- `adapt.from_jpeg_preview` decodes preview bytes back to a loaded PIL Image for
  preview validation, tests, and lightweight viewer pipelines.
- JPEG preview tests covering byte generation, mode conversion, and quality
  validation.

### Changed
- 0.8 compressed pixel access is now documented as complete: compressed array
  decode remains delegated to pydicom codec plugins, while display/export
  previews are handled through the optional Pillow bridge.

## [0.8.0] — 2026-06-02

### Added
- `adapt.pixel_array` now delegates compressed PixelData decode to pydicom when
  pydicom and the relevant pydicom pixel plugin are installed.
- `adapt.iter_pixel_frames` yields frame arrays one at a time for native
  multiframe datasets and reuses a single pydicom decode for compressed stacks.
- The default `CodecRegistry` automatically registers a `pydicom-pixels` bridge
  only for compressed transfer syntaxes with an available pydicom pixel handler.
- Signed 32-bit native pixel arrays are covered by the numpy adapter tests.

The following items also shipped in 0.8.0 but were omitted from this entry
when it was first published; they were documented retroactively on 2026-06-11:

- `AnonymizationAction.SHIFT_DATE`: date-shift de-identification action with a
  configurable integer day offset that preserves DA/DT formatting, time
  components, and timezone suffixes, recorded in the audit report.
- `is_valid_uid` and `generate_uid` in `dicomforge.uids`: DICOM UID grammar
  validation (PS3.5 §9.1) and UUID-derived UID generation under the standard
  `2.25` root or a custom organisational root.
- `validate_for_sop_class` in `dicomforge.api`: Type 1 / Type 2 mandatory
  attribute validation for CT, MR, Ultrasound, CR, and Secondary Capture
  image storage SOP Classes.
- `Tag.KVP`, `Tag.ScanningSequence`, and `Tag.SequenceVariant` keyword tags.

### Changed
- Native pixel dtype mapping now respects Explicit VR Big Endian byte order.

## [0.7.0] — 2026-05-16

### Added
- `dicomforge.transport` — production-hardened HTTP transport implementations:
  - `RequestsDicomwebTransport` — `requests`-backed transport with connection
    pooling, configurable timeouts, and TLS client-certificate support
  - `RetryTransport` — decorator that wraps any transport with automatic retry,
    exponential back-off (configurable base, max, jitter), and per-attempt noise
    to avoid thundering-herd effects on PACS systems
  - `BearerTokenTransport` — decorator that injects `Authorization: Bearer <token>`
    into every request; compose with `RetryTransport` and `RequestsDicomwebTransport`
    to get a full production stack in three lines
  - `StreamingDicomwebResponse` — response type returned by `RequestsDicomwebTransport.stream()`
    with a lazy `body_iter` and a `drain()` helper for header-only reads
- `parse_multipart_related_streaming(content_type, chunks)` — streaming multipart
  parser that holds at most one part in memory, suitable for large WADO-RS study
  responses delivered in byte chunks
- `build_multipart_related_streaming(parts, ...)` — builds a multipart/related
  upload body as a lazy byte generator so STOW-RS uploads do not require buffering
  all instances simultaneously
- `DicomwebClient.iter_retrieve_study_parts()` — streams study instances part-by-part;
  falls back to `retrieve_study_parts()` for non-streaming transports
- `DicomwebClient.iter_retrieve_series_parts()` — streaming series retrieval
- `DicomwebClient.iter_retrieve_instance_parts()` — streaming instance retrieval
- `DicomwebClient.stream_store_instances()` — STOW-RS upload driven by an iterable
  of instance bytes without full-body buffering
- `transport` optional dependency group in `pyproject.toml`:
  `pip install dicomforge[transport]` installs `requests>=2.28`
- `requests` added to the `dev` and `all` extras
- `InvalidTagError` exported from the `dicomforge` top-level package
- New `build_multipart_related_streaming` and `parse_multipart_related_streaming`
  exported from the `dicomforge` top-level package

### Fixed
- `Tag.SliceThickness` was registered as `(0050,0018)` (DeviceDiameter) instead of
  the correct `(0018,0050)`.  Any dataset access using `Tag.SliceThickness` would
  silently return `None` on real DICOM files.
- `io._KNOWN_VR` was missing ~30 entries including `AccessionNumber`, all date/time
  tags, `InstitutionName`, `ReferringPhysicianName`, `FrameOfReferenceUID`,
  `LongitudinalTemporalInformationModified`, `PatientIdentityRemoved`,
  `DeidentificationMethod`, `ImagerPixelSpacing`, and the Referenced SOP sequence
  tags.  Writing these tags via `io.write()` would produce VR `"UN"` instead of the
  correct DICOM VR.

---

## [0.6.0] — 2026-05-05

### Added
- `dicomforge.adapt` — adoption-layer integration adapters:
  - `from_pydicom` / `to_pydicom` — bidirectional pydicom Dataset conversion
  - `pixel_array` — numpy array from uncompressed PixelData with correct dtype
  - `to_pil_image` — PIL Image with automatic VOI windowing and MONOCHROME1 inversion
  - `to_json` / `from_json` — DICOM JSON Model round-trip
  - `from_pynetdicom_event` — extract DicomDataset from a pynetdicom event
- `dicomforge.api` — high-level convenience API:
  - `DicomFile` — lazy-loading file wrapper with named property access for 30+ tags
  - `quick_anonymize` — read → de-identify → write in one call
  - `validate_dataset` — structural validation with human-readable issue list
  - `batch_anonymize` — anonymize a file list; partial failures are isolated
- 55 additional `Tag` keywords (SeriesNumber, BodyPartExamined, PixelSpacing,
  ImagePositionPatient, Manufacturer, AttendingPhysicianName, and more)
- 20+ additional `SopClassUID` constants (PET, NM, US, RT, SR, WSI, enhanced CT/MR)
- 6 additional `TransferSyntaxUID` constants (JPEG 2000 lossy, JPEG-LS near-lossless,
  HT-JPEG 2000 lossless and lossy)
- 6 additional registered `TransferSyntax` entries
- `network` and `all` optional dependency extras in `pyproject.toml`
- `DicomDataset.copy()` and `DicomDataset.__repr__`
- `Tag.__repr__` returns keyword name when available (e.g. `Tag.PatientName`)

### Changed
- `AnonymizationPlan.starter_profile` expanded from 27 to 48 de-identification rules,
  adding patient weight/size/comments, ethnic group, smoking/pregnancy status,
  attending/requesting physician, device serial number, and department name
- `UidRemapper` is now thread-safe (internal cache protected by `threading.Lock`)
- `UidRemapper` now also remaps `MediaStorageSOPInstanceUID` and `ReferencedSOPInstanceUID`
- `default_registry()` now returns a cached singleton instead of a new instance per call
- `io.write` prefers `pydicom.dcmwrite()` on pydicom ≥ 3.0 (avoids deprecation warning)
- Network `_read_message` and `_write_message` now enforce a 30-second timeout and a
  64 MiB maximum message size
- All public pixel helper functions (`rescale_values`, `is_monochrome`, `voi_window_bounds`,
  `apply_voi_window_from_dataset`, etc.) are now exported from `dicomforge` top level
- `pyproject.toml` version bumped to 0.6.0; development status promoted to Beta

### Fixed
- `assert_pixel_data_length` incorrectly validated the last byte of even-length
  pixel data as a padding byte, causing `PixelMetadataError` for any dataset
  whose last pixel value was non-zero

---

## [0.5.0] — 2025-01-01

### Added
- `dicomforge.dicomweb` — dependency-free DICOMweb client:
  - QIDO-RS query builder (`QidoQuery`)
  - WADO-RS study/series/instance retrieval
  - STOW-RS multipart upload
  - DICOM JSON Model conversion (`dataset_from_dicom_json`, `dataset_to_dicom_json`)
  - `parse_multipart_related` / `build_multipart_related`
  - Injectable `DicomwebTransport` protocol with stdlib `UrllibDicomwebTransport`
- `dicomforge.network` — async DIMSE-style services:
  - `Association` client with C-ECHO, C-FIND, C-MOVE, C-STORE
  - `DimseServer` SCP with backpressure-aware C-STORE queue
  - `open_association` / `start_dimse_server` convenience helpers
  - `AssociationRejectedError`, `AssociationClosedError`
- DICOMweb integration: `dataset_to_message` / `dataset_from_message` with
  base64-encoded binary and nested dataset support

---

## [0.4.0] — 2024-10-01

### Added
- `dicomforge.network` initial implementation (async association lifecycle,
  C-ECHO, JSON framing)
- `DimseStatus` with class-level constants (SUCCESS, PENDING, CANCEL, UNABLE_TO_PROCESS)
- `AssociationRequest` frozen dataclass

---

## [0.3.0] — 2024-07-01

### Added
- `dicomforge.anonymize` — de-identification engine:
  - `AnonymizationPlan` with `starter_profile()` and `basic_profile()` factory methods
  - `UidRemapper` with SHA-256 deterministic remapping
  - `AnonymizationReport` / `AnonymizationEvent` audit trail
  - `PrivateTagAction` (REMOVE / KEEP)
  - Recursive sequence processing

---

## [0.2.0] — 2024-04-01

### Added
- `dicomforge.pixels` — pixel metadata and safety layer:
  - `FrameMetadata` with `from_dataset` and eager validation
  - `check_pixel_capability` — metadata + codec pre-flight check
  - `PixelCapability`, `VoiLut`
  - `rescale_value`, `apply_voi_window`, photometric interpretation helpers
- `dicomforge.io` — optional pydicom read/write backend

---

## [0.1.0] — 2024-01-01

### Added
- `dicomforge.tags` — `Tag` frozen dataclass with keyword registry and multi-format parser
- `dicomforge.dataset` — `DicomDataset` (MutableMapping with tag normalization)
- `dicomforge.transfer_syntax` — `TransferSyntax` registry with safe unknown defaults
- `dicomforge.codecs` — `CodecRegistry` and `Codec` capability model
- `dicomforge.errors` — `DicomForgeError` hierarchy
- `dicomforge.uids` — `SopClassUID`, `TransferSyntaxUID`, `ImplementationUID`, `DimseStatusCode`
- CI matrix: Python 3.9–3.13 on GitHub Actions
- MIT license, CONTRIBUTING.md, SECURITY.md, architecture and conformance docs
