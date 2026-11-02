# Architecture

DICOMForge adds collection validation and reproducible processing workflows while
keeping the core dependency-free. Optional integrations remain ordinary extras.

## Shared contracts

`DicomDataset` retains the simple tag-to-value interface. A parallel VR map and
unchanged numeric-string lexical records preserve input semantics. `DataElement`
provides a value-hidden representation; indexed paths identify nested items.
`DatasetView` validates existing pydicom objects without copying their pixels.
The bundled standard dictionary loads lazily through gzip/json.

`io` makes backend selection deterministic. `part10` owns the native preparation
contract, bounds checks and endian conversion; adapters normalize sequences and
encapsulation. Both file backends use `storage` for atomic publication.
`EncapsulatedPixelData` retains the backward-compatible bytes interface, but
conversion to pydicom's wire framing is explicit. Plain payload and framed bytes
are never intentionally interchanged. A future major version may replace the
bytes subclass with a standalone value object.

`pixels` validates metadata and byte counts. `adapt` implements native NumPy,
RLE, and optional pydicom frame paths, then explicit modality/display processing.
`Codec.decode_frame` provides executable extensions; `probe` expresses
instance-specific limitations. Heavy backends are imported only on use.

## Collection workflows

`collection` provides an inventory/resource plan, conventional CT/MR metadata
validation, project-keyed ReleasePolicy, and checkpointed release_collection.
It does not introduce distributed execution, a database service, or an implicit
cloud dependency. Reports use input ordinals and stable codes. Manifests retain
controlled output-integrity evidence without source filenames or identity values.
`cli` exposes the same APIs through inventory/validate/plan/release commands.

Release atomicity is per instance. Checkpoints support restart and detect changed
keys, source content, or outputs. Metadata-only preflight is followed by full file
read, transformation, atomic write, independent reopen and structural checks.
The implementation does not assess recognizable anatomy, acquisition completeness,
or all modality-specific identity channels. These boundaries travel in reports.

## Transport

`dicomweb` owns query/JSON/business outcomes and injectable request protocols.
`multipart` emits verified binary chunks for bounded-memory sinks. `transport`
provides optional requests pooling, TLS, retries and closeable responses.
Multipart convenience APIs buffer one part; retrieval to files stages each instance.
The historical `network` JSON simulator is experimental; pynetdicom owns actual
DICOM association interoperability.

## Release evidence

Tests exercise backend combinations and independent pydicom decoding, parser
corruption, privacy output, CLI subprocesses, geometry and interrupted jobs.
CI tests installed wheels with and without extras across Python 3.9–3.14. Ruff
and strict core mypy checks run separately on a supported toolchain. Versioned
migration and support boundaries are part of each user-visible change.
