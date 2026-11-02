# DICOMForge: critical engineering and adoption review

> Historical assessment of 0.11.0. The 0.12 implementation addresses the
> reproduced defects and adds scoped collection/CLI/release workflows. See
> [migration](migration-0.12.md), [current boundaries](conformance.md), and
> [verification](release-verification-0.12.md) for current behavior. Product
> proposals in this review are not automatically implementation claims.

Review date: October 25, 2026. Code reviewed: `33c0139`, version 0.11.0.

This is an assessment and proposed roadmap, not a declaration that the proposed
features are implemented. Production source was not modified during this review.
All reproduction data was synthetic.

## Recommendation

DICOMForge should become a **validation and reproducibility layer for DICOM
workflows**, with first-class support for existing pydicom applications.

Suggested product promise:

> Turn a collection of DICOM objects into a validated, policy-controlled,
> reproducible data release, with an explanation for every accepted,
> transformed, or quarantined instance.

Today, I would not select 0.11.0 as the primary de-identification or pixel
processing engine for production data. The most serious problems are observable
correctness failures in advertised workflows, not merely missing advanced
features. Resolve those before widening the feature surface or declaring 1.0.

The project has useful foundations: explicit errors, separation of optional
dependencies, structured validation issues, fragment-aware native pixel data,
clear conformance boundaries, MIT licensing, and small modules. The weakness is
that individual module capabilities do not compose reliably across backends.

## What was checked

- Read the production modules, tests, examples, packaging, CI, and scope documents.
- Ran the existing unittest suite under Python 3.12, both without pydicom and
  with pydicom 3.0.2. Results and remaining environment limitations are recorded
  below.
- Used synthetic end-to-end probes for backend conversion, nested identifiers,
  pixel values, file integrity, JSON, multipart transport, and batch outputs.
- Compared the intended positioning with official pydicom, highdicom,
  dicomweb-client, and DICOM standard documentation.

The findings below distinguish reproduced defects from source-inspection
findings and proposed capabilities. No real PACS, external clinical corpus,
performance benchmark, or regulatory assessment was part of this review.

## Release-blocking findings

Priority P0 means a privacy/data-integrity issue that should block promotion for
production use. P1 means an advertised workflow or essential reliability
contract needs repair. These are engineering priorities, not CVSS ratings.

### 1. P0: the default read path bypasses recursive de-identification

**Code:** `src/dicomforge/io.py:80`, `:198`; `anonymize.py:369`;
`dataset.py:97`.

When pydicom is installed, `io.read()` copies element values directly. Sequence
values retain pydicom `Sequence` and `Dataset` objects. Both anonymization and
private-tag removal recurse only through DicomForge datasets and ordinary
lists. The recursive converter in `adapt.from_pydicom()` is not used by this
read path.

**Reproduced:** a nested synthetic PatientName and private identifier survived
`read()` followed by `starter_profile().apply()`. The top-level output still
received `PatientIdentityRemoved = YES`.

**Required change:** establish one normalized recursive representation at the
I/O boundary, with explicit contracts for sequences, values, VRs, and compressed
pixels. Reuse it across `read()`, adapters, and writers. Prevent the processing
result from implying an assessment that was not performed.

**Acceptance:** nested identifiers and private elements are removed through the
public read/de-identify/write workflow with native and pydicom backends, multiple
sequence items, multiple levels, and both defined/undefined sequence lengths.
The saved file must be reopened independently and inspected.

### 2. P0: privacy-sensitive values are copied into routine audit output

**Code:** `anonymize.py:40`, `:52`, `:309`; `api.py:335`.

`AnonymizationEvent.to_dict()` includes `previous_value`, `new_value`, and
replacement values. A report intended for an audit/logging pipeline therefore
retains the identifiers removed from the dataset. `DicomFile.__repr__` also
loads the file and includes the patient's name and original filename.

**Reproduced:** the report for replacing PatientName serialized the original
synthetic name in `previous_value`.

**Required change:** make routine reports value-free by default: indexed tag
path, action, policy version, outcome, and reason. Offer a separate, explicit
sensitive diagnostic mode. Do not use ordinary hashes of names or patient IDs
as safe log values; low-entropy identifiers remain guessable. Keep any identity
mapping in a controlled store. Make `repr` free of patient values and I/O.

**Acceptance:** distinctive synthetic names, IDs, dates, filenames, and secrets
do not appear in default reports, exceptions intended for routine logging, or
representations. Diagnostic disclosure is explicit and tested.

### 3. P0: changing transfer syntax can silently change numerical pixel values

**Code:** `part10.py:195`, `:219`, `:542`.

The native writer changes element byte order but copies OW PixelData bytes
unchanged. There is no guard against a requested transfer syntax that requires
pixel-byte conversion.

**Reproduced:** writing little-endian 16-bit values `[258, 1024]` as Explicit VR
Big Endian and reading them produced `[513, 4]`.

**Required change:** distinguish serialization from transcoding. A syntax
change must use a verified conversion path or fail before opening the output.
Handle all affected binary VRs, not only PixelData. Detect inconsistent file
meta/dataset SOP identities too. Preserve the source encoding context.

**Acceptance:** compare numerical values using an independent reader across
every supported source/target pair. Same-library byte round trips cannot detect
this bug when both sides agree on the wrong representation.

### 4. P0: signed sub-word pixel values decode incorrectly

**Code:** `adapt.py:264`, `:662`, `:764`.

The NumPy path selects a signed dtype from BitsAllocated and PixelRepresentation
without normalizing BitsStored. The sign bit for signed 12-bit data lives at
bit 11, not bit 15.

**Reproduced:** for BitsAllocated=16, BitsStored=12, HighBit=11, signed samples
`0x0FFF` and `0x0800`, DICOMForge returned `[4095, 2048]`; pydicom returned
`[-1, -2048]`.

**Required change:** mask unused bits and sign-extend from the stored sign bit
consistently for native and RLE outputs. Review unsigned unused-bit handling.

**Acceptance:** differential tests against an independent decoder cover
minimum, maximum, negative, zero, and nonzero unused-bit patterns for each
supported bit-depth combination.

### 5. P0: batch outputs can be silently overwritten

**Code:** `api.py:760`, `:788`; `part10.py:124`.

`batch_anonymize()` writes each source to `output_dir / src.name`. Different
directories routinely contain identical DICOM filenames. Original filenames can
also contain identifiers. Writes are not staged atomically, and an output path
can coincide with an input.

**Reproduced:** two different input paths named `image.dcm` reported two
successes but produced one output file.

**Required change:** preflight destination uniqueness, use remapped instance
identifiers or a deliberate naming policy, default to no overwrite, protect
sources, and stage writes on the destination filesystem before atomic commit.
Record per-instance durable outcomes. Report collisions before processing.

**Acceptance:** duplicate basenames, duplicate SOP identities with different
content, existing outputs, interrupted writes, and input/output overlap cannot
silently destroy data.

### 6. P0: long UID roots destroy uniqueness guarantees

**Code:** `anonymize.py:88`, `:111`; `uids.py:56`.

Both UID generators truncate a decimal suffix to fit the supplied root. The
remapper accepts a 60-character root, leaving only three decimal suffix digits.
The cache maps inputs to outputs but does not detect different inputs mapping
to the same output. The public UID validator also accepts Unicode digits via
`str.isdigit()`.

**Reproduced:** 1,000 source UIDs with an accepted 60-character root produced
only 420 distinct outputs. `is_valid_uid("1.2.\u0663")` returned true even though
the final component is not an ASCII digit.

**Required change:** specify a collision/entropy budget, reject roots that
cannot satisfy it, validate ASCII UID grammar and leading zeros uniformly, and
provide a versioned mapping strategy. For reproducible de-identification, use
an explicit project key and namespace, preferably a standard keyed PRF such as
HMAC-SHA-256 with a carefully specified UID encoding. A public default salt
does not create confidential pseudonyms. Require callers to choose a namespace
and managed key for release workflows.

**Acceptance:** invalid roots and insufficient suffix capacity fail at
construction; collision behavior is explicit; mappings reproduce across
processes and preserve references; key/version changes are deliberate.

## Other high-priority correctness findings

### 7. P1: the advertised native RLE workflow fails with pydicom installed

**Code:** `io.py:45`, `:208`; `encapsulation.py:1`; `transcode.py:153`.

The native value's bytes are concatenated compressed fragment payloads.
pydicom's PixelData bytes include encapsulation item framing. They are not
interchangeable, despite sharing the Python `bytes` type.

**Reproduced:** `compress_pixel_data(ds); io.write(path, ds)` selected pydicom
and raised an encapsulation error. Reading a valid native RLE file with default
`io.read()` and calling `decompress_pixel_data()` interpreted the encapsulation
item header as an RLE frame header and failed.

**Fix:** explicit conversion between a fragment model and a serialized
encapsulation value. Make backend selection deterministic and observable;
adding an optional dependency must not silently break working application
code. Do not make a `bytes` subclass carry two incompatible wire meanings.

**Acceptance:** exercise the README workflow with and without pydicom, all
read/write backend combinations, single/multiframe data, and empty/populated
offset tables.

### 8. P1: the value-only dataset cannot support faithful general editing

**Code:** `dataset.py:14`; `dictionary.py:112`; `part10.py:219`;
`adapt.py:620`.

`DicomDataset` stores tag to Any without the source VR. Readers discard the
explicit VR, and writers infer it from a small dictionary. This is more than
an incomplete keyword registry: missing dictionary entries lose encoding
semantics even when the source explicitly provided them.

**Reproduced:** ConvolutionKernel was read from an SH element, then written as
UN. pydicom may recover its known VR on read, which can hide the defect in a
naive interoperability test. ContentSequence `(0040,A730)` was parsed as a list
of datasets but could not be written because the writer assigned UN and
expected bytes. `to_pydicom()` on a registered nested sequence independently
raised `TypeError: Sequence contents must be 'Dataset' instances` because the
child converter returns a Sequence instead of a Dataset.

**Fix:** preserve an element record containing VR, value, source encoding, and
raw/deferred representation where appropriate. Expose the existing value API
as a convenience view. Generate a versioned standard dictionary with documented
provenance and licensing, including ambiguous VR resolution. Unknown private
elements with explicit VR must retain that VR. Separate file meta from the
main dataset. Preserve original DS/IS lexical values when required rather than
unconditionally converting through floating point.

### 9. P1: previews window stored values before applying modality transforms

**Code:** `adapt.py:363`, `:750`, `:831`.

`to_pil_image()` does not request modality rescale before applying dataset
window values. It also directly converts multivalued WindowCenter/WindowWidth
to float. The compressed pydicom path may already return RGB, after which the
preview path can convert it again according to the original YBR metadata.

**Reproduced:** stored values `[0, 1024]`, slope 1, intercept -1024, center 0,
width 400 produced preview values `[127, 255]`; the modality values are
`[-1024, 0]`, so the expected linear-window output is approximately `[0, 127]`.

**Fix:** define stored, modality, real-world, and display pixel stages. Track
the decoded color space explicitly. Apply modality LUT/rescale before VOI,
support indexed VOI choices, validate width including width=1, and account for
padding values. Use explicit support errors for unimplemented photometric
formats. Current metadata byte counts do not handle native YBR_FULL_422 or
bit-packed data correctly; accepting their metadata is not decoding support.

### 10. P1: truncated input is accepted as successfully parsed

**Code:** `part10.py:248`, `:351`, `:384`; `dicomweb.py:814`, `:890`.

**Reproduced:** deleting the last two bytes of a four-byte PixelData value
still returned a dataset with two pixel bytes and no parsing error. A multipart
response missing its closing delimiter yielded its truncated payload as a
normal part.

**Fix:** check container/value lengths before slicing; enforce item boundaries,
numeric VR widths, delimiters, valid VR headers, and nesting limits. Normalize
low-level exceptions to structured parsing errors with offsets. Put explicit
limits on decompressed deflate output and element/frame allocations. Make any
lenient recovery an opt-in mode with visible recovery events. Reject truncated
multipart responses rather than publishing partial objects.

### 11. P1: structural validation can provide false reassurance

**Code:** `api.py:407`, `:625`, `:705`, `:726`.

**Reproduced:** a dataset with `PixelData=b""` received no PixelData Type 1
issue because `str(b"")` is nonempty. The same problem applies to empty lists.
Structural validation only creates FrameMetadata; it does not check actual
pixel byte length. Missing Type 2 attributes are warnings, although their
absence is a DICOM protocol violation. Secondary Capture's profile is far too
small to stand in for its image IOD.

**Fix:** use VR-aware emptiness, VM, and value checks; distinguish a structural
lint from IOD conformance; represent unsupported and unchecked scopes
explicitly. A conformant gate must not treat unperformed checks as a pass.
Make policy severities distinct from normative requirement status. Include tag
paths with sequence item indices and the standard edition/table in each rule.

Reference: [DICOM Type 2 requirements](https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_7.4.3.html).

### 12. P1: DICOM JSON conversion loses semantics

**Code:** `dicomweb.py:515`, `:550`, `:744`, `:761`.

**Reproduced:** an OW BulkDataURI came back as OB with a string in `Value`;
a PN's Ideographic component disappeared. Incoming VRs are not retained.

**Fix:** preserve typed bulk references, all PN representations, empty/null
value semantics, and incoming VR. Share the element dictionary/model with
file I/O. Bulk resolution needs an explicit policy for allowed locations and
credentials; receiving metadata should not automatically fetch remote URLs.

### 13. P1: transport retry and streaming contracts are incomplete

**Code:** `transport.py:64`, `:194`, `:318`; `dicomweb.py:438`.

**Reproduced:** retrying a POST with a generator body sent the payload on the
first attempt and an empty body on the next. RetryTransport retries statuses
without considering request method or whether a body can be replayed.

**Fix:** default retries to safe operations; require a body factory or explicit
replay guarantee for uploads. Handle Retry-After and transport exceptions with
an attempt/time budget. Give streaming responses deterministic close/context
management for early cancellation. Decode STOW per-instance successes,
warnings, and failures into a typed result rather than interpreting any 2xx as
the complete business outcome. Retain the raw response for advanced callers.

The multipart parser buffers an entire instance and has a hard-coded 256 MiB
search cap. That is unsuitable as a general large-instance streaming promise.
Provide chunk-to-sink/spool APIs with configurable limits and bounded memory.

### 14. P1: codec capability checks overpromise

**Code:** `codecs.py:34`, `:114`; `pixels.py:263`; `transcode.py:32`.

The registry is a capability description rather than an executable codec
interface. Registering a custom codec does not make `pixel_array()` invoke it.
`can_decode=True` does not capture bit depth, color representation, frame
organization, installed plugin behavior, or available memory.

**Reproduced:** compression accepted 32-bit MONOCHROME2 data and labeled it
with the DICOM RLE transfer syntax. A byte-level PackBits/RLE implementation
supporting 32 bits does not imply that this is a permitted standard DICOM image
encoding. The current standard's RLE pixel-attribute table does not list
32-bit allocated samples for these standard photometric interpretations.

**Fix:** use a codec Protocol with probe/decode/encode/frame operations and
dataset-specific capability results. Validate the target syntax's legal image
attribute combinations separately from the codec's algorithmic capacity.

Reference: [DICOM RLE attribute constraints](https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_8.2.2.html).

## Performance and scope problems visible in the implementation

1. **Metadata-only native reads still read the full file.**
   `part10.read_file()` calls `Path.read_bytes()` before checking
   `stop_before_pixels`. `loads()` also slices the dataset body, and deflated
   input is expanded wholesale. A lazy wrapper around this function defers
   *when* work happens; it does not provide deferred element or pixel I/O.
   Implement seekable readers, selected tags, deferred bulk references, and
   incremental deflate where practical. Benchmark bytes read and peak RSS.

2. **Compressed frame iteration generally decodes the full stack.**
   `adapt.iter_pixel_frames()` delegates non-RLE compression to the whole
   `raw.pixel_array`. Use pydicom's path/file-object frame APIs when available.
   Publish limits for random access, absent offset tables, and unsupported
   codecs. Do not imply that a generator guarantees bounded-memory decoding.

3. **The custom framed-JSON network protocol consumes maintenance capacity.**
   Its limitations are documented, but names such as DimseServer, C-STORE, and
   association negotiation invite expectations of interoperability. Move the
   simulator into an explicitly experimental namespace or test support, with a
   deprecation path. Use pynetdicom for production DIMSE. A second homemade
   wire protocol is a weak adoption argument.

4. **De-identification is currently instance-oriented and research-hostile in
   some defaults.** Every patient becomes PatientID=ANON; dates and several
   useful covariates disappear. References outside a small UID tag list are
   unhandled. Date shifting quietly leaves malformed/partial values unchanged.
   Build collection-aware pseudonymization, project/issuer-aware subject
   identity, consistent subject-level shifts, and explicit quarantine rules.
   Preserve research covariates only under deliberate, documented policy.
   Do not offer universal safe-private-tag retention; use versioned vendor,
   creator, modality, and version-specific policies with an unknown outcome.

5. **Thread-safe cache access is not a concurrency strategy.** The UID mapping
   cache grows per source UID, is process-local, and locks work already made
   deterministic by hashing. Define process-safe persistence, bounded caches,
   batch resume, and key/version handling before advertising large-scale jobs.

## Competitive assessment

The following are useful implementation qualities, but weak headline
differentiators against the existing ecosystem:

| Current angle | Existing ecosystem capability | Better DICOMForge promise |
| --- | --- | --- |
| No mandatory core dependencies | pydicom already has a pure-Python core with no other requirements | A clearly scoped install footprint, backed by comparable measurements |
| Native RLE | pydicom provides its own RLE encoder | Verified end-to-end preservation and clear per-dataset encoding decisions |
| Lazy/frame iteration | pydicom supports deferred/selected reads and frame APIs | Bounded-memory collection workflows with documented resource budgets |
| DICOMweb + auth | dicomweb-client supports common servers, auth, TLS, and remote/local access | Resumable validated transfers, typed per-instance outcomes, release manifests |
| Easier image/volume handling | highdicom provides volume/geometry and derived-object support | Explain why a series is usable and retain provenance through existing tools |
| Typed dataset | Normalized tags with Any values do not establish typed value safety | Typed workflow results, validation rules, policies, and adapters users can trust |

Primary sources: [pydicom project](https://github.com/pydicom/pydicom),
[RLE encoding](https://pydicom.github.io/pydicom/stable/guides/encoding/rle_lossless.html),
[deferred and selected reads](https://pydicom.github.io/pydicom/stable/reference/generated/pydicom.filereader.dcmread.html),
[frame iteration](https://pydicom.github.io/pydicom/stable/reference/generated/pydicom.pixels.iter_pixels.html),
[dicomweb-client](https://dicomweb-client.readthedocs.io/en/latest/usage.html),
[highdicom volumes](https://highdicom.readthedocs.io/en/stable/volume.html).

This is not an exhaustive competitor survey. The differentiation below is a
product hypothesis to validate with adopters, not a claim that no other tool
offers any of these features.

## The three capabilities worth building around

### A. Explainable collection validation and a release gate

Validate an entire study/cohort, including references and geometry, and produce
`accepted`, `quarantined`, or `needs_review` outcomes with stable issue codes.
Distinguish incomplete, unsupported, not-assessed, and invalid inputs.

Start with conventional CT/MR series: duplicate instances, conflicting instance
content, study/series/FrameOfReference mismatches, geometry consistency,
orientation, spacing, modality transforms, and missing referenced instances.
Use spatial position/orientation for ordering; InstanceNumber alone is not a
geometry contract. Internal consistency does not establish that acquisition is
complete: report expected counts or retrieval manifests separately.

**Commercial value:** fewer ingestion incidents and integration-specific
patches; explicit acceptance rules before inference or archival export.

**Research value:** fewer invalid volumes, mixed acquisitions, cohort selection
errors, and unrecorded exclusions.

**Proof to publish:** an independently checked challenge corpus with exact
expected findings, documented false negatives, and exported JSON/HTML reports.

### B. Reproducible, collection-aware data release

A versioned policy applies project-keyed pseudonyms, consistent date handling,
private-attribute decisions, and reference remapping across a collection. A dry
run estimates what changes and what cannot be assessed. A release operation
writes staged outputs, reopens and validates them, then commits a manifest.

The manifest should record tool/policy/ruleset/backend versions, decisions,
transformation provenance, and controlled integrity evidence. Keep sensitive
source mappings and original identifiers separate from broadly shared
manifests. Even source hashes and pseudonyms can be linkable; their disclosure
needs a deliberate contract.

**Commercial value:** reproducible exports, auditable transformations,
recoverable failures, and evidence useful to a customer's validation process.

**Research value:** longitudinal linkage, reproducible dataset versions,
preserved approved covariates, and fewer broken SEG/SR/source references.

**Proof to publish:** repeated runs reproduce intended semantic outputs and
mapping relationships; resume does not duplicate/overwrite; default logs are
value-free; unsupported SOP classes/PHI-bearing content are explicitly flagged.

The [DICOM confidentiality profiles](https://dicom.nema.org/Medical/Dicom/current/output/chtml/part15/chapter_E.html)
explicitly distinguish attribute processing from the wider de-identification
process. Treat pixel content, overlays, encapsulated documents, SR text, and
recognizable anatomy as separate assessed or unassessed scopes. Adding OCR does
not justify a universal de-identification guarantee.

### C. Resource-bounded ingestion with operational evidence

Plan a job before execution: objects, bytes, codec availability, estimated
decoded size, limits, concurrency, expected reference closure, and destination
conflicts. Process with backpressure and checkpoints. Retrieve to sinks rather
than forcing every instance into one in-memory bytes value.

**Commercial value:** predictable cloud costs and memory, restartability, and
per-instance delivery outcomes.

**Research value:** reproducible large-cohort scans and usable processing on a
workstation without loading all pixels.

**Proof to publish:** peak RSS, bytes read, throughput distributions, failed
instance counts, and retry behavior against pinned reproducible workloads.
Benchmark end-to-end useful work against the equivalent pydicom ecosystem
workflow, not a metadata-only shortcut against a full decode.

## Architecture to make these promises credible

- **One element contract:** loss-preserving elements and indexed tag paths,
  separate file meta, raw/deferred bulk sources, explicit source encoding.
- **One backend contract:** read/write/decode/probe operations with declared
  capabilities and deterministic backend choice. Record the chosen backend and
  version in reproducibility evidence. Honor overrides or reject them clearly.
- **Direct pydicom adoption:** allow validation and planning against a pydicom
  Dataset through a narrow read-only adapter. Do not force a lossy conversion
  just to run a validator. Apply mutations through an explicit plan/transaction.
- **Versioned rulesets:** standard edition, rule identifier, scope, condition,
  source table, requirement, and evidence. Keep normative correctness separate
  from local policy severity.
- **Collection model:** subject/study/series/instance inventory, reference graph,
  duplicate/conflict semantics, and serializable job checkpoints. Begin with a
  small local manifest/SQLite implementation before distributed orchestration.
- **Explicit pixel stages:** stored samples, modality values, real-world values,
  display output; geometry and per-frame metadata travel with the data.
- **Optional integrations:** pydicom and pynetdicom for established low-level
  behavior; highdicom for SEG/SR/derived objects; MONAI/PyTorch/NumPy adapters
  after geometry contracts exist. Native I/O remains an explicitly scoped
  backend until it meets preservation and differential-test gates.

Avoid splitting the current code into five separately maintained packages
before there is a real need for independent releases. Extras and internal
protocol boundaries are sufficient initially.

## Adoption work with measurable outcomes

| Audience | First complete example | Adoption criterion |
| --- | --- | --- |
| Existing pydicom team | Validate an existing Dataset/series without rewriting its pipeline | First useful finding in under 15 minutes; no forced file rewrite |
| Research lab | Build a CT/MR cohort manifest, validate geometry, apply longitudinal policy, export to NumPy/MONAI | Reproducible membership, exclusions, transforms, and subject linkage |
| Imaging AI vendor | Ingest from Orthanc, validate, quarantine failures, run a mock model, write derived results via highdicom | Resumable job with explicit per-instance outcomes and reference integrity |
| Commercial integration team | Supported workflow matrix, migration guide, reproducible fixtures and validation evidence | Can reproduce declared behavior on a pinned deployment |

Ship an executable CLI around the same API, for example inventory, validate,
plan, and release commands. CLI names and API examples should be marked as
proposals until implemented. Include JSON output, stable exit codes, safe
logging, progress, and interruption/resume behavior. A convenient CLI can reduce
time to first useful result more than another convenience property.

Create a versioned documentation site with searchable API reference, supported
workflow matrix, migration recipes from pydicom, and limitations beside each
example. Keep examples executable in CI. The current historical milestone
checkmarks should not substitute for the status of complete user workflows.

For research: retain CITATION.cff/DOI, publish synthetic fixtures and benchmark
methods, and seek a methods/software paper after reproducible workflows exist.
For commercial use: add predictable security contacts, dependency/SBOM and
license provenance, supported-version policy, deprecation window, release
validation evidence, and a clear support model. These support a customer's
assessment; they do not certify the resulting medical product.

An optional paid layer could provide deployment support, vendor policy packs,
validated integration profiles, or managed orchestration. Keep the core data
formats and fundamental correctness open so users can reproduce and exit.
Treat willingness to pay as something to test, not an established market fact.

## Sequenced roadmap

The time ranges below are planning targets for a small team, contingent on
scope and staffing. Gate completion on evidence, not the date.

| Stage | Focus | Exit criteria |
| --- | --- | --- |
| First 2–4 weeks | Correctness/stabilization release | Resolve P0 findings; default README I/O/RLE paths work across backends; no silent truncation/overwrite; regression tests reproduce each defect |
| Following 4–8 weeks | Element/backend contracts and explainable CT/MR validation | Preserve declared element semantics; explicit unsupported scopes; indexed paths; direct pydicom adapter; independent fixture comparisons |
| Following 6–10 weeks | One complete research-release workflow | Collection inventory, keyed subject mapping, policy versioning, dry run, safe reports, reference integrity, atomic outputs, resume |
| Next milestone | Commercial ingestion pilot | Pinned Orthanc and dcm4chee integration jobs, bounded-memory transfers, typed STOW outcomes, operational metrics, adopter feedback |
| 1.0 gate | Stability of a deliberately declared scope | Published support matrix, migration/deprecation policy, independently verified workflows, artifact packaging checks, complete docs for guaranteed behavior |

Do not make 1.0 depend on implementing every IOD, a new DIMSE stack, every
codec, an OCR engine, or all PS3.15 options. That scope encourages shallow
coverage. A small validated contract can be stable while advanced workflows
remain experimental and visibly unsupported.

## Testing and release engineering changes

Current CI installs `[dev]` on every Python version, so the normal CI matrix
does not prove the zero-optional-dependency claim. It runs unittest and
compileall, but neither Ruff nor mypy.

Add a deliberately selected matrix:

1. A genuinely dependency-free wheel installation and native workflow job.
2. A supported pydicom 2.4 job and a current pydicom 3.x job, on compatible
   Python versions; use those to justify the advertised version range.
3. Pixel/transport extras and actual installed decoder-plugin tests.
4. Every meaningful backend boundary: native-to-pydicom and back; normalized
   nested values; compressed wire representations; backend overrides.
5. Golden fixtures produced by an independent tool, plus differential tests
   against pydicom/DCMTK/GDCM where appropriate. Shared implementation agreement
   is not a sufficient oracle.
6. Malformed inputs, property-based tests, and parser fuzzing. Include corrupt
   lengths, unknown VRs, nested sequences, absent delimiters, large offsets,
   deflate limits, and character-set transitions.
7. Pinned Orthanc/dcm4chee integration tests for declared workflows. Test partial
   STOW failures, interruption, pagination, and early response closure.
8. Build and install the wheel in a clean environment; run examples, verify
   package metadata, include `py.typed`, and type-check a consumer fixture.
9. Run Ruff and a deliberately supported mypy version in CI. The dev dependency
   is currently unbounded; mypy 2.4.0 rejects the configured Python 3.9 target.
   Broad Any values and a missing `py.typed` marker weaken the typed-library
   claim even independently of the reported type errors.

Use licensed synthetic/public fixtures with explicit provenance. A public
imaging archive is not automatically safe to redistribute as a test fixture.
Track coverage by modality, SOP class, transfer syntax, character set, backend,
and workflow instead of relying only on line coverage or total test counts.

## Validation results from this review

- Python 3.12.14 without pydicom: **353 tests run, 19 skipped, no failures**.
  NumPy/Pillow were present; this was not a completely dependency-free install.
- With pydicom 3.0.2 and requests 2.34.2 in the sandbox: **353 tests run,
  9 skipped, no failures**. All nine skips were loopback-socket restrictions.
- With local loopback sockets enabled and the package installed in the temporary
  environment: **353 tests passed, no skips**. The editable package build also
  succeeded. A clean production wheel installation was not separately tested.
- Focused Ruff checks (`E4,E7,E9,F`): **9 findings**, including two undefined
  `Any` names in test annotations. These are secondary to the correctness work.
- mypy 2.4.0: rejects the configured Python 3.9 target and reports **24 errors
  across 8 files** in this environment, including optional-dependency stub and
  unused-ignore issues. This is not a claim that all 24 are runtime defects.
- Synthetic diagnostics reproduce the failures described above. They are
  observations against 0.11.0, not new passing regression tests or implemented
  fixes. The [companion diagnostic script](review_probes_2026_10_25.py) documents
  how to rerun all 19 probes. Their [recorded JSON results](review_results_2026_10_25.jsonl)
  provide the observations from this review.

The first success metric should be: **an existing pydicom user can validate and
release a realistic study, reproduce every decision, and encounter no silent
data change, identifier disclosure, or overwritten output.** Feature count is
a poor substitute for that result.
