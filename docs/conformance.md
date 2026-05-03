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

Out of scope for core today:

- full VR-specific value classes
- IOD/module validation
- character set transcoding
- guaranteed byte-for-byte round trips

## File IO

`dicomforge.io` delegates reading and writing to `pydicom`.

Current write behavior:

- assigns standard VRs for known tags
- keeps File Meta Information in group `0002`
- requires SOP Class UID and SOP Instance UID when creating file meta
- defaults Transfer Syntax UID to Explicit VR Little Endian when absent

Production systems should still use pydicom validation and real sample fixtures
for final file compatibility checks.

## Pixel Safety

`dicomforge.pixels` is a metadata and safety layer, not a full pixel pipeline.

Current scope:

- validate native pixel shape metadata
- check registered codec capability before pixel access
- verify native uncompressed PixelData byte length
- apply simple modality rescale and VOI window helpers

Out of scope today:

- compressed pixel decoding
- NumPy array conversion
- color space conversion
- overlays and presentation state behavior

## De-Identification

`dicomforge.anonymize` provides a deterministic starter de-identification plan.
Use `AnonymizationPlan.starter_profile()` for new code. `basic_profile()` is
kept as a compatibility alias and does not imply full PS3.15 coverage.

Current scope:

- replace or empty common direct identifiers
- delete patient address
- recursively apply rules to nested sequence items
- recursively remove private tags
- deterministically remap Study, Series, and SOP Instance UIDs
- return an applied-event audit report

Out of scope today:

- full DICOM PS3.15 Basic Application Confidentiality Profile coverage
- option-specific action tables
- burned-in pixel detection
- UID remapping across an external longitudinal registry

## Networking

`dicomforge.network` is a dependency-free async command transport for API
development and lifecycle testing. It is deliberately not DICOM Upper Layer wire
compatibility.

Current scope:

- async association lifecycle
- AE title checks
- requested/supported SOP Class negotiation checks
- C-ECHO, C-FIND, C-MOVE, and C-STORE style client methods
- bounded C-STORE queue backpressure
- cancellation and socket cleanup tests

Out of scope today:

- DICOM Upper Layer PDUs
- presentation context transfer syntax negotiation
- direct interoperability with PACS, modalities, Orthanc, or dcm4chee

Full wire-compatible DIMSE support belongs in the planned `dicomforge-network`
package, likely by integrating with `pynetdicom`.
