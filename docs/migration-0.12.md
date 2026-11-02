# Migrating to 0.12

0.12 is a pre-1.0 correctness release. Test a representative corpus before
upgrading an existing workflow. The following behavior changes are deliberate.

- **Backend:** auto now always chooses native. Select pydicom explicitly for an
  existing backend-specific deployment. Both backends normalize sequences and
  encapsulation. The bundled dictionary removes the old 100-tag inference limit.
- **UID mappings:** HMAC-SHA-256 v1 replaces the old prefix-salted hash. Old and
  new releases produce different mappings. Keep an existing mapping/version or
  reprocess a whole collection; never mix mappings in one reference graph.
  Roots must leave 39 suffix digits (at most 24 characters). Research release
  workflows require an explicit namespace and at least 32 secret key bytes.
- **Audit:** reports are value-free by default. To collect sensitive diagnostics,
  use `apply_with_report(..., capture_values=True)`, then
  `report.to_dict(include_values=True)`. Both choices are explicit. Protect the
  resulting data. `DicomFile.__repr__` no longer loads a file or prints identity.
- **I/O:** atomic writes preserve existing destinations on serialization failure.
  Set overwrite=False for no-clobber behavior. quick_anonymize defaults to no
  overwrite and rejects input/output equality; batch collisions are errors.
  Batch legacy names are retained for compatibility; releases use remapped UIDs.
- **Partial reads:** saving stop_before_pixels output raises. Re-read fully or
  use DicomFile.load_pixels(), which retains edited metadata values.
- **Pixels:** Big Endian output has different raw bytes but identical values.
  Signed sub-word values are normalized. Thumbnails apply modality rescale
  before VOI. Width=1 is a threshold; widths below one raise. RLE 32-bit image
  encoding now raises; the standalone byte codec's capacity is a separate API.
- **Validation:** missing Type 2 elements are errors. Empty bytes/lists no longer
  satisfy Type 1. Unsupported SOP profiles have assessed=False. Structural,
  VR/VM, image-profile, and collection checks remain distinct declared scopes.
- **Transport:** retries default to GET/HEAD/OPTIONS and replayable bodies.
  Enable another method only when its semantics and body replay are safe.
  Multipart truncation now raises. Close streaming responses or use a context.
- **JSON:** declared VR, all PN groups, null entries, and BulkDataURI semantics
  are preserved. BulkDataURI reads return BulkDataReference, not a plain string.
- **Networking:** the JSON protocol remains experimental. It does not communicate
  with standard PACS. Production DIMSE is delegated to pynetdicom.

Python 3.9–3.14 remain supported. No core third-party dependency was introduced.
Future pre-1.0 breaking changes must appear in release notes and migration
instructions. After 1.0, public removals require at least two minor releases and
six months of deprecation, except when retaining behavior would expose data or
silently corrupt it. Security-driven exceptions must be explained explicitly.
