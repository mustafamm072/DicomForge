# Roadmap

## 0.1 Core ✅

- typed tags and dataset wrapper
- transfer syntax classification
- codec registry
- de-identification planning
- optional pydicom read/write adapter
- core documentation and contribution rules

## 0.2 Pixel Safety ✅

Status: implemented in `dicomforge.pixels` with standard-library tests.

- frame metadata model
- pixel capability checks
- VOI LUT, rescale, photometric interpretation helpers
- clear errors for unsupported compressed syntaxes
- golden sample tests

## 0.3 De-identification ✅

Status: implemented in `dicomforge.anonymize` as a practical PS3.15-inspired
non-pixel attribute subset with standard-library tests. Full regulatory
de-identification remains a site-specific policy and validation responsibility.

- practical DICOM PS3.15 Basic Application Level Confidentiality Profile subset
  for common non-pixel identifying attributes
- deterministic UID remapping that preserves equality relationships within a
  dataset or batch using the same salt
- audit report generation via `apply_with_report`
- configurable private tag handling with removal by default
- explicit profile metadata tags such as `PatientIdentityRemoved` and
  `LongitudinalTemporalInformationModified`

## 0.4 Networking ✅

Status: implemented in `dicomforge.network` as dependency-free command primitives
with standard-library async tests; full DICOM Upper Layer wire compatibility
remains planned for `dicomforge-network`.

- async association lifecycle
- C-ECHO, C-FIND, C-MOVE, C-STORE client
- backpressure-aware C-STORE SCP
- cancellation and socket cleanup tests
- read/write timeout and maximum message size guard

## 0.5 DICOMweb ✅

Status: implemented in `dicomforge.dicomweb` as dependency-free client,
query, DICOM JSON, STOW multipart, and multipart parsing primitives with
standard-library tests. Production auth/retry policies and PACS integration
fixtures remain planned for optional transports.

- QIDO-RS query builder
- WADO-RS retrieval
- STOW-RS upload
- streaming multipart parsing

## 0.6 Adoption Layer ✅

Status: implemented in `dicomforge.adapt` and `dicomforge.api` with
standard-library tests. All items below were shipped in v0.6.0.

**Integration adapters (`dicomforge.adapt`):**
- `from_pydicom` / `to_pydicom` — bidirectional conversion with nested
  sequence support; allows incremental adoption alongside existing pydicom code
- `pixel_array` — extract a numpy array from uncompressed PixelData with
  correct dtype, shape, and optional Hounsfield Unit rescale
- `to_pil_image` — convert a DICOM frame to a PIL Image with automatic VOI
  windowing and MONOCHROME1 inversion
- `to_json` / `from_json` — round-trip through the DICOM JSON Model (PS3.18 §F)
- `from_pynetdicom_event` — extract a `DicomDataset` from a pynetdicom event

**High-level convenience API (`dicomforge.api`):**
- `DicomFile` — lazy-loading file wrapper with named property access
  (`patient_name`, `modality`, `series_number`, `transfer_syntax`, …)
- `quick_anonymize(input, output)` — one-call read → de-identify → write
- `validate_dataset` — returns a list of human-readable issues (missing required
  tags, pixel metadata inconsistency, burned-in annotation warning)
- `batch_anonymize` — anonymize a file list; partial failures do not abort

**Extended registries:**
- 75+ DICOM tags (added clinical context: SeriesNumber, BodyPartExamined,
  PixelSpacing, ImagePositionPatient, Manufacturer, and more)
- 35+ SOP Class UIDs (PET, NM, US, RT, SR, WSI added)
- 15 Transfer Syntax UIDs (JPEG 2000 lossy, JPEG-LS near-lossless, HT-JPEG 2000)
- 48 PS3.15 de-identification rules (added patient weight/size/comments,
  ethnic group, attending/requesting physician, device serial number, and more)

**Quality fixes:**
- Thread-safe `UidRemapper` (threading.Lock on internal cache)
- `default_registry()` is now cached (module-level singleton)
- pydicom ≥ 3.0 compatibility (`pydicom.dcmwrite` preferred over deprecated `save_as`)
- `DicomDataset.__repr__` and `.copy()` added
- `Tag.__repr__` shows keyword name when known (e.g. `Tag.PatientName`)
- All public pixel helper functions exported from `dicomforge` top-level

---

## 0.7 Production DICOMweb Transport

Target: pluggable, production-hardened HTTP transport for DICOMweb clients.

- `requests`-backed transport with connection pooling
- automatic retry with exponential back-off and jitter
- OAuth 2.0 / Bearer token auth helper
- chunked WADO-RS streaming (iterator API, no full-body buffering)
- STOW-RS streaming upload (no full multipart body in memory)
- integration-test fixtures against Orthanc or a mocked DICOMweb server
- TLS client certificate support

## 0.8 Compressed Pixel Access

Target: numpy arrays from compressed PixelData without leaving the library.

- pydicom-backed compressed pixel decode (JPEG, JPEG-LS, JPEG 2000, RLE) via
  `adapt.pixel_array` when pydicom and its codec extras are installed
- `CodecRegistry` integration: codec registered automatically when detected
- Pillow encode/decode bridge for 8-bit JPEG preview generation
- Multiframe pixel iterator to avoid loading all frames into memory at once
- Signed 32-bit pixel support in numpy adapter

## 0.9 Character Sets and Internationalisation

Target: correct handling of non-ASCII patient and physician names.

- DICOM Specific Character Set (0008,0005) detection and propagation
- UTF-8 encoding output on write when supported
- Japanese (ISO 2022 JIS), Korean, Chinese extended character set tests
- VR-aware string coercion for PN (person names) with component parsing
- Round-trip test suite against real multi-byte encoded DICOM files

## 1.0 Stable Commercial Release

Target: a release that commercial teams can adopt without expecting breaking
changes and that regulated-software teams can cite in their design histories.

**Stability:**
- Published CHANGELOG with semantic versioning commitment
- Deprecation policy: deprecated symbols announced one minor release before removal
- Public API documented with parameter types, return types, and exceptions raised

**Conformance:**
- Formal DICOM Conformance Statement template (PS3.2-inspired)
- IOD/Module validation: verify a dataset satisfies the mandatory attribute
  requirements for its declared SOP Class
- Full DICOM PS3.15 Basic Application Confidentiality Profile option table coverage
- Validated character set handling across Japanese, Korean, and Chinese encodings

**Operations:**
- Benchmark suite: de-identification throughput, DICOMweb query latency,
  pixel array extraction speed
- Memory-usage profile for large multiframe objects

**Integration:**
- Wire-compatible DIMSE via `dicomforge-network` (pynetdicom bridge)
- Curated PACS integration examples: Orthanc, dcm4chee, Google Cloud Healthcare API
- AI pipeline example: integration with monai / torchvision preprocessing
- Web viewer example: pixel → base64 PNG endpoint

**Governance:**
- Maintainer guide and contribution ladder
- Security disclosure policy
- Compatible license list for optional dependencies
