# Architecture

## Product stance

DICOMForge should compete by being easier to trust and easier to adopt, not by
shipping every feature in the first release. The core package stays lightweight;
heavy capabilities are optional plugins.

## Core packages

- `dicomforge.tags`: typed tags and keyword lookup
- `dicomforge.dataset`: predictable dataset wrapper
- `dicomforge.transfer_syntax`: transfer syntax classification
- `dicomforge.codecs`: codec capability registry
- `dicomforge.pixels`: frame metadata, pixel safety checks, and lightweight pixel helpers
- `dicomforge.anonymize`: de-identification profiles and plans
- `dicomforge.io`: optional backend-based file IO
- `dicomforge.network`: dependency-free association and DIMSE-style command primitives
- `dicomforge.uids`: selected standard UID and DIMSE status constants

## Optional packages planned

- `dicomforge-pixels`: NumPy/Pillow pixel transforms and bulk array operations
- `dicomforge-codecs-openjpeg`: JPEG 2000 codec bridge
- `dicomforge-network`: full DICOM Upper Layer and DIMSE services
- `dicomforge-dicomweb`: QIDO-RS, WADO-RS, STOW-RS client/server helpers
- `dicomforge-iods`: validated high-level IOD builders

## Lessons from existing libraries

fo-dicom is mature and valuable, but public issue and documentation signals show
areas a new design should handle deliberately:

- codec packages must be explicit and capability-queryable
- transfer syntax metadata can be misleading and needs validation hooks
- parallel association handling needs a clear concurrency model
- datasets need typed set/get helpers
- character sets must be tested, especially Japanese encodings
- network sockets must close reliably on exceptions
- low-level flexibility should not force every user to know the whole standard

Python already has strong libraries, especially `pydicom`, `pynetdicom`, and
`highdicom`. DICOMForge should integrate where helpful rather than pretending
those ecosystems do not exist.

The in-core networking module is deliberately not a DICOM Upper Layer PDU
implementation. It uses a small framed JSON transport to exercise association
lifecycle, command handlers, backpressure, and cancellation behavior without
adding a networking dependency to core. Full wire-compatible DIMSE belongs in
the planned `dicomforge-network` package.

See [conformance.md](conformance.md) for the current implementation boundary by
module.

Sources reviewed:

- fo-dicom repository and public issue listing
- fo-dicom supported transfer syntax documentation
- pydicom project description
- highdicom project description and paper abstract
