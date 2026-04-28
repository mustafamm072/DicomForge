# Roadmap

## 0.1 Core

- typed tags and dataset wrapper
- transfer syntax classification
- codec registry
- de-identification planning
- optional pydicom read/write adapter
- core documentation and contribution rules

## 0.2 Pixel Safety

Status: implemented in `dicomforge.pixels` with standard-library tests.

- frame metadata model
- pixel capability checks
- VOI LUT, rescale, photometric interpretation helpers
- clear errors for unsupported compressed syntaxes
- golden sample tests

## 0.3 De-identification

Status: implemented in `dicomforge.anonymize` with standard-library tests.

- practical DICOM PS3.15 Basic Application Level Confidentiality Profile subset
  for common non-pixel identifying attributes
- deterministic UID remapping that preserves equality relationships within a
  dataset or batch using the same salt
- audit report generation via `apply_with_report`
- configurable private tag handling with removal by default
- explicit profile metadata tags such as `PatientIdentityRemoved` and
  `LongitudinalTemporalInformationModified`

## 0.4 Networking

- async association lifecycle
- C-ECHO, C-FIND, C-MOVE, C-STORE client
- backpressure-aware C-STORE SCP
- cancellation and socket cleanup tests

## 0.5 DICOMweb

- QIDO-RS query builder
- WADO-RS retrieval
- STOW-RS upload
- streaming multipart parsing

## 1.0 Adoption Bar

- stable public API
- conformance documentation
- benchmark suite
- compatibility matrix
- examples for PACS, AI pipelines, and web viewers
- governance and maintainer guide
