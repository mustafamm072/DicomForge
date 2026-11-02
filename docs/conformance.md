# Supported behavior and boundaries (0.12)

This is an implementation contract, not a formal product conformance statement.
The [migration guide](migration-0.12.md) lists behavior changes from 0.11.

## Elements and file I/O

- The value-mapping API remains small. `DataElement` exposes preserved VR/value
  semantics, `elements()` iterates records, and `iter_paths()` includes sequence
  item indices. Explicit VRs survive both adapters, copies, and native writes.
- A lazy gzip/JSON dictionary snapshot contains 5,091 standard entries from
  pydicom 3.0.2, with source/version/license recorded in `src/dicomforge/data/`.
  This snapshot is not a claim to cover every subsequent standard addition.
  Private explicit VRs are preserved; ambiguous unknown VRs require context or
  explicit assignment. Unknown public implicit VR values remain opaque.
- Native Part 10 supports Implicit/Explicit VR Little Endian, Explicit VR Big
  Endian, Deflated Explicit VR Little Endian, nested sequences, charset-aware
  text, and encapsulated fragment framing. Unchanged native DS/IS lexical forms
  are retained. Byte-for-byte original-file reproduction is not guaranteed.
- Native metadata scans use mmap and stop at PixelData. No fully remote/deferred
  bulk reader is claimed. Deflated input expands under a configurable 512 MiB
  default limit via `part10.loads(max_decompressed_bytes=...)`.
- Container/value bounds, numeric VR widths, delimiter presence, and a 64-level
  sequence nesting limit are enforced. Corrupt character encoding fails rather
  than replacing characters silently. This is not a guarantee against every
  malformed input; continue expanding fuzz/differential fixtures.
- `auto` consistently means native; explicit pydicom 2.4/3.x adapters normalize
  nested values and compressed fragments. The pydicom writer uses the native
  preparation contract, then the selected writer. Templates are copied.
- Native endian changes recursively swap known binary word VRs. Unknown binary
  VRs from a read dataset cannot be safely endian-converted and are rejected.
  Compression changes require the transcoder. Conflicting file-meta/dataset
  identities are rejected. Partial reads cannot be saved accidentally.
- File writes use same-directory staging, fsync, and atomic replacement/link.
  `overwrite=False` is an atomic no-clobber contract. Atomicity is per file and
  assumes a filesystem supporting ordinary local rename/hard-link semantics.

## Pixels

- Native NumPy output supports integer 1/8/16/32/64-bit allocation, stored-bit
  normalization/sign extension, native bit-packed frames, planar colour, and
  native 8-bit YBR_FULL_422 with even columns. Float PixelData is not handled.
- RLE uses the dependency-free byte codec, preserving fragment boundaries and
  offset tables. Dataset encoding permits declared standard 8/16-bit monochrome,
  RGB/YBR_FULL/palette combinations, not 32-bit standard DICOM images. Binary
  segmentation RLE encoding is not implemented.
- Native/RLE frame iteration avoids whole decoded-stack allocation. pydicom 3
  JPEG-family access uses frame APIs with raw colour output; the legacy pydicom
  2 fallback may materialize a stack. Codec plugins remain optional.
- Per-frame budget checks precede native decode. A custom Codec.decode_frame
  callback can execute actual decoding, and Codec.probe can reject a dataset.
  A registered descriptive codec without a callback is not an arbitrary codec
  implementation.
- Monochrome preview applies rescale before the selected first VOI window;
  width=1 is handled without division by zero. MONOCHROME1 and supported YBR
  output are converted for display. Complete modality/VOI LUT sequences,
  real-world value mapping, palette LUT rendering, presentation states and
  diagnostic derivation are not claimed by the preview API.

## Validation

Structural, element VR/VM/UID, selected image mandatory-attribute, and collection
checks are separate APIs. Empty lists/bytes do not satisfy Type 1. Missing Type 2
attributes are errors. Unsupported SOP profiles are explicitly unassessed.
Neither the five small image profiles nor the collection checker implements all
IOD modules, conditional attributes, or all SOP classes.

`validate_elements_detailed` returns indexed paths and dictionary provenance.
Read-only pydicom views preserve the caller's pixel buffers. Collection geometry
is scoped to conventional CT/MR, single-frame objects: identity duplicates,
series metadata, orientation/position/spacing, repeated planes, irregular slice
spacing, resource limits, and optional closed reference sets. Accepted refers to
this metadata scope. Acquisition completeness and pixel identity remain unchecked.

## Privacy and research releases

- The starter profile is a non-pixel metadata subset. It recursively removes
  private tags and remaps selected instance/reference UIDs. A public default
  salt remains for low-level convenience; it is not a confidential project key.
- UidRemapper uses versioned HMAC-SHA-256 mapping without an unbounded cache.
  Root length is restricted to retain a full 128-bit decimal suffix. The public
  UID grammar requires ASCII digits without leading zeros.
- Routine audit events omit original/replacement values. Sensitive capture and
  sensitive serialization are separate explicit choices. File repr does not
  read the file or print names/paths.
- ReleasePolicy requires a project namespace and at least 32 key bytes.
  Subject identity uses PatientID plus issuer; longitudinal shifts are stable
  per subject and reject partial/malformed dates. Conventional CT/MR releases
  require external pixel review. Unknown structured/overlay/document scopes
  are sent for review rather than assumed safe.
- Outputs use remapped instance UIDs; policy/tool/key identity and keyed source
  tokens support resumable, verified exports. The manifest omits source paths
  and patient values. It remains controlled, potentially linkable data.
- This is not complete PS3.15 coverage, OCR, recognizable-anatomy assessment,
  legal de-identification approval, or a claim of clinical suitability.

## DICOMweb and networking

DICOMweb provides QIDO/WADO/STOW, preserved JSON VR/PN/null/bulk-reference
semantics, strict multipart framing, optional requests pooling/TLS, safe-method
retry budgets, explicit stream closure, and typed STOW business outcomes.
`retrieve_study_to` and `iter_multipart_chunks` provide bounded-buffer sinks;
part-object convenience APIs buffer one complete instance. Limits are explicit.
Bulk references are never resolved automatically. No live PACS compatibility
certification or cloud-provider SLA is implied by unit tests.

The historical JSON networking simulator remains available as an experimental
API. It is not a DIMSE/DICOM Upper Layer implementation. Use pynetdicom for
production associations and `adapt.from_pynetdicom_event` for dataset conversion.

## Compatibility evidence

CI builds/installs wheels on Python 3.9–3.14 in core-only and extras environments,
plus pydicom 2.4. CLI subprocess, parser corruption, signed pixels, cross-backend
RLE, nested privacy, atomic writes, geometry, and interrupted-release regressions
are included. See compatibility.md and the release verification report for actual
local results. Synthetic tests do not establish full vendor/PACS interoperability.
