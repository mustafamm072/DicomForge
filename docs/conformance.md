# DICOMForge Conformance Notes

This document describes what the current in-repository implementation is meant
to do safely. It is not a formal DICOM Conformance Statement, and DICOMForge is
not a medical device or diagnostic system.

## Core Dataset

`dicomforge.dataset` provides typed tag normalization and a lightweight mapping
API. It preserves Python values as supplied by callers and by optional backends.

Current scope:

- normalize keyword, integer, tuple, and canonical string tag inputs
- support nested `DicomDataset` values inside sequence-like lists
- remove private tags recursively by default
- `copy()` for shallow dataset copies
- `__repr__` shows tag count and sample tags for debugging

Out of scope for core today:

- full VR-specific value classes
- IOD/module validation
- complete ISO 2022 code-extension state-machine coverage for every edge case
- guaranteed byte-for-byte round trips

## Tag Registry

`dicomforge.tags` provides 100 registered keyword tags covering:

- Character sets (`SpecificCharacterSet`)
- Patient identity (PatientName, PatientID, PatientBirthDate, …)
- Study / Series / Instance identification (StudyDescription, SeriesNumber,
  InstanceNumber, ImageType, ProtocolName, …)
- Equipment (Manufacturer, ManufacturerModelName, DeviceSerialNumber, …)
- Patient clinical context (BodyPartExamined, PatientWeight, PatientComments,
  EthnicGroup, AttendingPhysicianName, …)
- Image geometry (PixelSpacing, SliceLocation, ImagePositionPatient,
  ImageOrientationPatient, …)
- Pixel metadata (all standard pixel tags)
- Referenced SOP sequences (ReferencedSOPClassUID, ReferencedSOPInstanceUID, …)

Private tags (odd group numbers) are supported but not assigned keywords.

## UID Utilities

`dicomforge.uids` provides standard UID constants plus dependency-free helpers.

Current scope:

- Transfer Syntax, SOP Class, query/retrieve model, and DICOMForge
  implementation UID constants, plus DIMSE status codes
- `is_valid_uid` — DICOM UID grammar validation (PS3.5 §9.1): digits and dots
  only, ≤ 64 characters, no empty components, no leading zeros
- `generate_uid` — globally unique UIDs derived from UUID4 under the standard
  `2.25` root (PS3.5 §B.2), or under a caller-supplied organisational root

Out of scope today:

- UID registry lookups or semantic classification of arbitrary UIDs
- collision tracking across processes (UUID-derived uniqueness only)

## Character Sets

`dicomforge.charset` provides dependency-free helpers for DICOM text encoding
boundaries.

Current scope:

- `SpecificCharacterSet` normalization for default ASCII, UTF-8, common ISO
  8859 terms, GB18030, GBK, ISO 2022 IR 87 Japanese, and ISO 2022 IR 149
  Korean terms
- map common Python codec names back to DICOM Specific Character Set terms
- `encode_text` / `decode_text` / `can_encode_text` safety helpers
- `dataset_character_set` for reading a dataset's declared character set
- `PersonName` and `coerce_person_name` for PN component parsing, formatting,
  and display names
- `io.write` propagates `SpecificCharacterSet` before text elements and rejects
  non-ASCII text when no compatible charset is declared
- `adapt.to_pydicom` formats structured `PersonName` values but leaves final
  charset encoding checks to the eventual pydicom write call

Out of scope today:

- full conformance claim for every DICOM ISO 2022 code-extension transition
- vendor fixture validation for every modality and PACS/VNA combination
- locale-aware display-name ordering beyond the structured PN components

## File IO

`dicomforge.io` delegates reading and writing to `pydicom` (≥ 2.4).

Current scope:

- pydicom 2.x and 3.x compatibility (`dcmwrite` preferred when available)
- File Meta Information preservation on read
- Standard VR assignment for 90+ known tags on write
- Specific Character Set propagation before text elements on write
- write-time validation for text encodability against declared character set
- Required SOP Class UID and SOP Instance UID for file meta generation
- Default Transfer Syntax UID (Explicit VR Little Endian) when absent

Out of scope today:

- VR inference for tags not in the known VR table (falls back to `UN`)
- Guaranteed pixel-for-pixel round-trip fidelity on compressed syntaxes

## Adoption Layer

`dicomforge.adapt` bridges DicomDataset with external libraries.

Current scope:

- `from_pydicom` / `to_pydicom` — bidirectional pydicom Dataset conversion,
  including nested sequences, Person Name, UID, DS, and IS value coercion
- `pixel_array(frame, apply_rescale)` — numpy array from native uncompressed
  PixelData with dtype derived from BitsAllocated and PixelRepresentation;
  compressed PixelData is delegated to pydicom when pydicom and the relevant
  pydicom pixel plugin are installed
- `iter_pixel_frames(apply_rescale)` — frame-by-frame numpy array iterator for
  native multiframe data, with compressed stacks delegated once to pydicom
- `to_pil_image(frame, apply_window)` — PIL Image from a DICOM frame with
  automatic VOI windowing; MONOCHROME1 displayed correctly (inverted), and
  RGB/YBR colour display conversion for supported arrays
- `to_jpeg_preview(frame, quality, apply_window)` — 8-bit JPEG preview bytes
  for thumbnails, web viewers, and API responses; uses the same pixel safety
  and optional backend path as `to_pil_image`
- `from_jpeg_preview(data, mode)` — load JPEG preview bytes back into a PIL
  Image for validation and lightweight viewer pipelines
- `to_json` / `from_json` — DICOM JSON Model round-trip via `dicomforge.dicomweb`
- `from_pynetdicom_event` — extract DicomDataset from a pynetdicom event payload

Out of scope today:

- bundled compressed pixel codecs; DICOMForge does not vendor JPEG, JPEG-LS,
  JPEG 2000, or RLE decoders
- diagnostic-quality lossy image derivation from JPEG previews
- pynetdicom association management (use `pynetdicom` directly; `adapt` only
  bridges the dataset representation)

## High-Level API

`dicomforge.api` provides one-call convenience wrappers.

Current scope:

- `DicomFile` — lazy-loading DICOM file wrapper with named property access for
  24 common tags, `.anonymize()`, `.save()`, `.validate()`, and `.tags()`
- `quick_anonymize(input, output)` — read → de-identify → write in one call
- `validate_dataset` — structural validation: required tags, pixel metadata
  consistency, burned-in annotation warning
- `validate_for_sop_class` — DICOM Type 1 / Type 2 mandatory attribute
  validation for CT, MR, Ultrasound, CR, and Secondary Capture image storage
  SOP Classes; unrecognised SOP Classes return an informational issue instead
  of raising
- `batch_anonymize` — anonymize a list of files; partial failures isolated

Out of scope today:

- IOD module validation beyond the five image SOP Classes above; Type 3 and
  conditional attributes are not checked
- full burned-in annotation detection (flag only; no pixel analysis)
- multi-threaded or async batch processing

## Pixel Safety

`dicomforge.pixels` is a metadata and safety layer, not a full pixel pipeline.

Current scope:

- validate native pixel shape metadata
- check registered codec capability before pixel access
- verify native uncompressed PixelData byte length
- apply simple modality rescale (Hounsfield Units) and VOI window helpers
- photometric interpretation helpers (is_monochrome, needs_inversion)
- automatically detect available pydicom compressed pixel handlers in the
  default codec registry
- generate 8-bit JPEG preview bytes through the optional Pillow adoption layer
- all pixel helper functions exported from `dicomforge` top level

Out of scope today:

- bundled compressed pixel codecs
- overlays and presentation state behavior
- clinical interpretation from display previews

## De-Identification

`dicomforge.anonymize` provides a deterministic starter de-identification plan.
Use `AnonymizationPlan.starter_profile()` for new code. `basic_profile()` is
kept as a compatibility alias and does not imply full PS3.15 coverage.

Current scope (48 rules in `starter_profile`):

- replace common direct identifiers (PatientName → "Anonymous", PatientID → "ANON")
- empty dates, times, institution, personnel, and procedure fields
- delete address, telephone, patient weight/size/comments, ethnic group,
  smoking/pregnancy status, allergies, device serial number, and more
- recursively apply rules to nested sequence items
- recursively remove private tags (configurable)
- deterministically remap Study, Series, SOP, Frame of Reference, and
  MediaStorageSOPInstanceUID (same UID in ↔ same UID out across the batch)
- `AnonymizationAction.SHIFT_DATE` — shift DA/DT values by a configurable
  integer day offset while preserving time components and timezone suffixes;
  shifts are recorded in the audit report
- thread-safe UidRemapper (threading.Lock on internal cache)
- return an applied-event audit report for downstream logging

Out of scope today:

- full DICOM PS3.15 Basic Application Confidentiality Profile option table
- burned-in pixel annotation detection
- UID remapping across an external longitudinal registry

## Networking

`dicomforge.network` is a dependency-free async command transport for API
development and lifecycle testing. It is deliberately not DICOM Upper Layer wire
compatible.

Current scope:

- async association lifecycle
- AE title checks
- requested/supported SOP Class negotiation
- C-ECHO, C-FIND, C-MOVE, and C-STORE style client methods
- bounded C-STORE queue backpressure
- read/write timeout (default 30 s) and 64 MiB message size guard
- cancellation and socket cleanup tests

Out of scope today:

- DICOM Upper Layer PDUs
- presentation context transfer syntax negotiation
- direct interoperability with PACS, modalities, Orthanc, or dcm4chee

Full wire-compatible DIMSE support belongs in the planned `dicomforge-network`
package (0.7 / 1.0 milestone).

## DICOMweb

`dicomforge.dicomweb` provides dependency-free helpers for DICOMweb API
mechanics.

Current scope:

- QIDO-RS query parameter building
- QIDO-RS study, series, and instance search client methods
- WADO-RS study, series, instance, and study metadata retrieval methods
- STOW-RS multipart upload body construction
- DICOM JSON Model conversion for common values, person names, sequences, and
  inline binary
- multipart/related parsing for buffered response bodies
- injectable transport protocol plus a standard-library `urllib` transport
- optional `dicomforge.transport` helpers for requests-backed connection
  pooling, bearer-token auth, retry/backoff, TLS client certificates, and
  streaming multipart retrieve/store workflows

Out of scope today:

- real PACS/VNA integration-test compatibility guarantees
- complete DICOM JSON Model coverage for every VR edge case
