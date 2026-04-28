# Architecture

## Product stance

DICOMForge should compete by being easier to trust and easier to adopt, not by
shipping every feature in the first release. The core package stays lightweight;
heavy capabilities are optional plugins.

## Core packages

- `dicomforge.tags`: typed tags and keyword lookup for core image and
  de-identification attributes
- `dicomforge.dataset`: predictable dataset wrapper
- `dicomforge.transfer_syntax`: transfer syntax classification
- `dicomforge.codecs`: codec capability registry
- `dicomforge.pixels`: frame metadata, pixel safety checks, and lightweight
  pixel helpers
- `dicomforge.anonymize`: de-identification profiles, UID remapping, private
  tag policy, and audit reports
- `dicomforge.io`: optional backend-based file IO

## De-identification stance

The 0.3 de-identification API is intentionally conservative and auditable. It
models each change as a rule, applies deterministic UID remapping through a
salted mapper, and returns an `AuditReport` for downstream logging or review.
The basic profile targets common non-pixel identifying attributes from the
DICOM PS3.15 Basic Application Level Confidentiality Profile. It does not claim
that pixel data, burned-in annotations, structured report text, or every
modality-specific attribute has been made non-identifying.

Private attributes are removed by default. Callers can opt into
`PrivateTagAction.KEEP` when private attributes have been separately reviewed.
The older `remove_private_tags` argument on `apply` and `apply_with_report`
remains available as a per-call override for compatibility.

Commercial deployments should treat this module as one component in a governed
de-identification workflow: choose a stable project-specific UID salt, decide
whether private attributes can be retained, run pixel and metadata review, and
document the profile options used for each data release.

## Optional packages planned

- `dicomforge-pixels`: NumPy/Pillow pixel transforms and bulk array operations
- `dicomforge-codecs-openjpeg`: JPEG 2000 codec bridge
- `dicomforge-network`: async DIMSE services
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

Sources reviewed:

- fo-dicom repository and public issue listing
- fo-dicom supported transfer syntax documentation
- pydicom project description
- highdicom project description and paper abstract
