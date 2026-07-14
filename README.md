# DICOMForge

[![DOI](https://zenodo.org/badge/1222011062.svg)](https://doi.org/10.5281/zenodo.20192747)
[![CI](https://github.com/mustafamm072/DicomForge/actions/workflows/ci.yml/badge.svg)](https://github.com/mustafamm072/DicomForge/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
![Status](https://img.shields.io/badge/status-beta-yellow)
![License](https://img.shields.io/badge/license-MIT-green)
![Core](https://img.shields.io/badge/core-dependency--free-brightgreen)
![DICOMweb](https://img.shields.io/badge/DICOMweb-QIDO%20%7C%20WADO%20%7C%20STOW-blueviolet)
![i18n](https://img.shields.io/badge/i18n-UTF--8%20%7C%20ISO--2022%20%7C%20GB18030-informational)

`dicom` · `medical-imaging` · `radiology` · `pacs` · `dicomweb` ·
`de-identification` · `pixel-data` · `healthcare-ai` · `python`

DICOMForge is a Python DICOM processing library for medical imaging
applications. The goal is a lightweight core with typed, predictable APIs,
explicit safety boundaries, and optional integrations for heavier work such as
pixel codecs, wire-compatible networking, and DICOMweb.

This repository is intentionally starting with a small, solid core:

- typed tags and value access
- transfer syntax classification
- pluggable codec registry
- de-identification profiles, deterministic UID remapping, date shifting, and
  audit reports
- DICOM UID grammar validation and UUID-derived UID generation
- structural and SOP Class (Type 1 / Type 2 attribute) dataset validation
- pixel metadata and safety checks
- VOI window, rescale, and photometric interpretation helpers
- optional pydicom-backed compressed pixel decode and frame iteration
- optional Pillow-backed 8-bit JPEG preview generation
- Specific Character Set helpers and structured person-name parsing
- async networking primitives for association lifecycle and DIMSE-style commands
- DICOMweb query, retrieval, upload, and multipart helpers
- dependency-free **native DICOM Part 10 file IO** (read/write), with an
  optional `pydicom` backend for the broadest real-world coverage
- dependency-free **RLE Lossless compression and decompression** with one-call
  dataset transcoding (`compress_pixel_data` / `decompress_pixel_data`)
- standard-library tests

## Why another DICOM library?

The adoption target is not just feature count. The library should feel safe for
production teams and approachable for new medical-imaging developers.

Design priorities:

- **Small import surface:** core imports should not pull in NumPy, Pillow, codec
  wheels, or networking stacks.
- **Typed access:** avoid stringly-typed dataset code where common attributes can
  be accessed predictably.
- **Explicit codec model:** make unsupported transfer syntaxes visible before a
  transcoding job fails halfway through.
- **Lazy IO:** support large studies and multi-frame objects without forcing
  full pixel loading.
- **Character-set correctness:** treat text encoding as a first-class concern.
- **Concurrency-safe services:** design networking and DICOMweb APIs around
  explicit lifecycle and backpressure.
- **Good errors:** explain the DICOM concept, the offending tag, and the next
  action where possible.

See [docs/architecture.md](docs/architecture.md) and
[docs/roadmap.md](docs/roadmap.md). Current implementation boundaries are
tracked in [docs/conformance.md](docs/conformance.md). For repository naming
and discoverability notes, see [docs/branding.md](docs/branding.md).

## Commercial Readiness

DICOMForge is MIT licensed and designed for commercial use as a developer
library. It is not a medical device, diagnostic application, complete PS3.15
de-identification engine, or wire-compatible DIMSE implementation. See
[docs/safety.md](docs/safety.md), [docs/conformance.md](docs/conformance.md),
and [docs/compatibility.md](docs/compatibility.md) before using it in regulated
clinical workflows.

## When To Use It

Use DICOMForge when you need:

- typed, dependency-light DICOM metadata handling
- pixel metadata validation before decoding or processing
- pydicom-backed pixel extraction for compressed syntaxes when optional codec
  plugins are installed
- display-ready PIL images and JPEG preview bytes for lightweight viewer/API
  workflows
- explicit character-set validation before writing non-ASCII DICOM text
- de-identification planning with deterministic UID remapping, date shifting,
  and audit reports
- mandatory-attribute validation against common image storage SOP Classes
- native, dependency-free DICOM file IO — or a pydicom-backed backend — behind
  a smaller application API
- lossless pixel-data compression (RLE) without installing any codec packages
- DICOMweb URL/query, DICOM JSON, STOW multipart, and response parsing helpers
- async lifecycle and backpressure primitives for DICOM-like service design

Do not use DICOMForge as the only component for:

- diagnostic interpretation or medical-device behavior
- legal de-identification approval without site policy and human review
- direct DIMSE/PACS interoperability over the DICOM Upper Layer
- full-fidelity DICOM editing that requires every VR, character set, and IOD rule
- replacing pydicom, pynetdicom, or integration-tested PACS/VNA validation

## Architecture At A Glance

```text
dicomforge.tags            typed tag parsing and common keyword constants
dicomforge.dataset         lightweight mutable dataset wrapper
dicomforge.transfer_syntax transfer syntax classification
dicomforge.codecs          codec capability registry
dicomforge.charset         Specific Character Set and person-name helpers
dicomforge.pixels          pixel metadata safety checks and small value helpers
dicomforge.anonymize       starter de-identification plans and audit reports
dicomforge.dictionary      tag → VR data dictionary and VR category metadata
dicomforge.part10          native, dependency-free DICOM Part 10 read/write
dicomforge.encapsulation   fragment-preserving compressed PixelData value model
dicomforge.rle             native, dependency-free RLE Lossless frame codec
dicomforge.transcode       one-call compress/decompress between transfer syntaxes
dicomforge.adapt           pydicom, numpy, Pillow, JSON, and pynetdicom adapters
dicomforge.api             lazy file wrapper and one-call application helpers
dicomforge.io              native + optional pydicom read/write backends
dicomforge.network         async command lifecycle primitives, not DICOM UL PDUs
dicomforge.dicomweb        QIDO/WADO/STOW helpers with injectable HTTP transport
dicomforge.transport       optional requests/retry/auth DICOMweb transports
```

## API Stability

DICOMForge is pre-1.0. Public APIs are intended to be small and stable, but
breaking changes may happen while the library moves toward a 1.0 adoption bar.
Breaking changes should be documented in release notes and paired with migration
guidance.

## Quick Start

```python
from dicomforge import DicomDataset, Tag, TransferSyntax

ds = DicomDataset()
ds.set(Tag.PatientName, "Anonymous")
ds.set(Tag.Modality, "CT")

syntax = TransferSyntax.from_uid("1.2.840.10008.1.2.1")
assert syntax.is_little_endian
assert syntax.is_explicit_vr
```

Read and write DICOM files — no dependencies required:

```python
from dicomforge import dcmread, dcmwrite, DicomDataset, SopClassUID, Tag

# Read any uncompressed DICOM file with the built-in native codec.
dataset = dcmread("image.dcm", stop_before_pixels=True)
print(dataset.get("PatientName"))

# Write one back out as a conformant DICOM Part 10 file.
ds = DicomDataset(
    {
        Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
        Tag.SOPInstanceUID: "1.2.3.4.5",
        Tag.PatientName: "Doe^Jane",
        Tag.Modality: "OT",
    }
)
dcmwrite("out.dcm", ds)
```

`dcmread` / `dcmwrite` (aliases of `dicomforge.read` / `write`) select a backend
automatically: the dependency-free native codec when pydicom is not installed,
and pydicom when it is. Force a backend explicitly with `backend="native"` or
`backend="pydicom"`. The native codec handles Implicit/Explicit VR Little
Endian, Explicit VR Big Endian, Deflated Explicit VR Little Endian, and — for
compressed pixel data — RLE Lossless end to end, plus faithful fragment
round-trips for the other encapsulated syntaxes. JPEG-family *encoding and
decoding* still requires `dicomforge[pydicom]` with the relevant codec plugin.

```python
from dicomforge import part10

# Serialise directly to/from bytes, choosing the transfer syntax.
blob = part10.dumps(ds, transfer_syntax="1.2.840.10008.1.2")  # Implicit VR LE
restored = part10.loads(blob)
```

Lossless pixel-data compression — still no dependencies required:

```python
from dicomforge import compress_pixel_data, dcmread, dcmwrite, decompress_pixel_data

dataset = dcmread("uncompressed_ct.dcm")
compress_pixel_data(dataset)          # → RLE Lossless, in place
dcmwrite("ct_rle.dcm", dataset)       # smaller file, decodable by any toolkit

dataset = dcmread("ct_rle.dcm")
decompress_pixel_data(dataset)        # → Explicit VR Little Endian raw pixels
```

The built-in codec covers RLE Lossless (`1.2.840.10008.1.2.5`), the DICOM
standard's own run-length scheme — a practical lossless choice for archives
and exports. It round-trips bit-exactly with pydicom in both directions.

Basic de-identification:

```python
from dicomforge import AnonymizationPlan, DicomDataset, PrivateTagAction

dataset = DicomDataset(
    {
        "PatientName": "Ada Lovelace",
        "PatientID": "MRN-123",
        "StudyInstanceUID": "1.2.826.0.1.3680043.8.498.1",
        (0x0011, 0x1001): "private vendor value",
    }
)

plan = AnonymizationPlan.starter_profile(
    uid_salt="project-specific-secret",
    private_tag_action=PrivateTagAction.REMOVE,
)
report = plan.apply_with_report(dataset)

assert dataset.get("PatientName") == "Anonymous"
assert dataset.get("PatientIdentityRemoved") == "YES"
assert report.private_tags_removed == 1
```

Date-shift de-identification (preserves intervals between studies while hiding
real dates):

```python
from dicomforge import AnonymizationAction, AnonymizationPlan, DicomDataset, Rule, Tag

dataset = DicomDataset({Tag.StudyDate: "20260101", Tag.SeriesDate: "20260102"})

plan = AnonymizationPlan(
    [
        Rule(Tag.StudyDate, AnonymizationAction.SHIFT_DATE, -30),
        Rule(Tag.SeriesDate, AnonymizationAction.SHIFT_DATE, -30),
    ]
)
plan.apply(dataset)

assert dataset.get(Tag.StudyDate) == "20251202"
assert dataset.get(Tag.SeriesDate) == "20251203"
```

SOP Class mandatory-attribute validation:

```python
from dicomforge import (
    DicomDataset,
    SopClassUID,
    Tag,
    validate_for_sop_class,
    validate_for_sop_class_detailed,
)

ct = DicomDataset({Tag.SOPClassUID: SopClassUID.CTImageStorage})
for issue in validate_for_sop_class(ct):
    print(issue)
# [error] CT Image Storage requires SOPInstanceUID (0008,0018) (Type 1 — must be present and non-empty).
# ...

# Structured issues are available for services, CI checks, and dashboards.
for issue in validate_for_sop_class_detailed(ct):
    assert issue.severity in {"error", "warning"}
    print(issue.code, issue.tag, issue.message)
```

UID generation and validation:

```python
from dicomforge import generate_uid, is_valid_uid

uid = generate_uid()  # UUID-derived under the standard "2.25" root (PS3.5 §B.2)
assert is_valid_uid(uid)
assert not is_valid_uid("1.2.03.4")  # leading zero in a component
```

Async networking:

```python
from dicomforge.network import DimseServer, open_association

async with DimseServer(ae_title="LOCAL-SCP") as server:
    async with await open_association(
        "127.0.0.1",
        server.bound_port,
        called_ae_title="LOCAL-SCP",
    ) as association:
        status = await association.c_echo()
        assert status.is_success
```

DICOMweb query building:

```python
from dicomforge.dicomweb import DicomwebClient, QidoQuery, UrllibDicomwebTransport

client = DicomwebClient(
    "https://pacs.example/dicomweb",
    UrllibDicomwebTransport(timeout=10),
)
studies = client.search_studies(QidoQuery().patient_id("MRN-123").modality("CT"))
```

JPEG preview generation:

```python
from dicomforge.adapt import to_jpeg_preview

preview = to_jpeg_preview(dataset, frame=0, quality=85)
```

Character-set aware person names:

```python
from dicomforge import DicomDataset, PersonName, Tag

dataset = DicomDataset(
    {
        Tag.SpecificCharacterSet: "ISO_IR 192",
        Tag.PatientName: PersonName("Yamada", "Taro", ideographic="山田^太郎"),
    }
)
```

## De-identification Scope

DICOMForge implements a practical, conservative subset of the DICOM PS3.15
Basic Application Level Confidentiality Profile for non-pixel attributes:
common patient, accession, date/time, institution, operator, and UID fields are
removed, emptied, replaced, or deterministically remapped. Private tag handling
is explicit and defaults to removal. `remove_private_tags` on `apply` and
`apply_with_report` remains available as a per-call override for older callers.

This is a software library, not a compliance certificate. Production use should
pair it with site-specific policy, legal review, image pixel review, and a risk
assessment for the data release context.

## Development

Run the standard-library test suite:

```bash
PYTHONPATH=src python3 -m unittest
```

Optional checks used by maintainers when development dependencies are installed:

```bash
python -m ruff check src tests
python -m mypy src/dicomforge
python -m compileall -q src tests
```

Examples live in [examples](examples).

For a fuller commercial workflow, see
[examples/end_to_end_workflow.py](examples/end_to_end_workflow.py).

## Known Issues and Limitations

Historical bugs and their fixed versions are tracked in
[CHANGELOG.md](CHANGELOG.md). The list below is limited to current boundaries
that still affect adopters.

- **`dicomforge.network` is not wire-compatible DIMSE** — The async networking
  module uses a lightweight JSON framing protocol, not the DICOM Upper Layer
  PDU wire format defined in PS3.8. It is not interoperable with real PACS
  systems over the wire. Wire-compatible DIMSE via a `pynetdicom` bridge is
  planned for a `dicomforge-network` package in a future release.

- **Validation is useful, not exhaustive conformance** — `validate_dataset`
  checks common structural problems, UID grammar, pixel metadata consistency,
  and burned-in annotation flags. `validate_for_sop_class` checks Type 1 /
  Type 2 mandatory attributes for CT, MR, Ultrasound, CR, and Secondary Capture
  image storage SOP Classes. Full IOD module tables, conditional attributes,
  Type 3 semantics, and site-specific conformance policies remain outside the
  built-in validator.

- **De-identification is a starter profile, not legal approval** —
  `AnonymizationPlan.starter_profile()` covers common non-pixel identifying
  attributes, deterministic UID remapping, private tag handling, date shifting,
  and audit reports. It is not a complete PS3.15 Basic Application
  Confidentiality Profile implementation, does not inspect burned-in pixel PHI,
  and should be paired with local policy, review, and validation.

- **JPEG-family pixel codecs are delegated to pydicom** — RLE Lossless is
  encoded and decoded by the built-in dependency-free codec, but JPEG,
  JPEG-LS, and JPEG 2000 decode requires pydicom and the relevant pydicom
  pixel plugin; DICOMForge does not bundle those codec implementations.
  `adapt.to_jpeg_preview` produces lossy 8-bit display previews, not
  diagnostic-quality derived images. The pure-Python RLE codec favours
  portability over raw speed; very large archive jobs may prefer a
  C-accelerated codec via pydicom.

- **Character-set support is explicit, not magical** — DICOMForge validates
  common declared character sets and person names, but full ISO 2022 edge cases
  and vendor-specific legacy files should still be verified with site fixtures.

- **Native IO frames compressed data; it only *compresses* RLE** — The native
  Part 10 codec reads and writes Implicit/Explicit VR Little Endian, Explicit
  VR Big Endian, and Deflated Explicit VR Little Endian, and reads/writes
  encapsulated (compressed) pixel data with fragment boundaries and the Basic
  Offset Table preserved (`EncapsulatedPixelData`). Producing *newly
  compressed* pixels natively is supported for RLE Lossless via
  `compress_pixel_data`; JPEG-family encoding requires `backend="pydicom"`
  with a codec plugin. Tags outside the built-in dictionary resolve to VR `UN`
  under Implicit VR and are preserved as raw bytes rather than corrupted.

- **DICOMForge is not a medical device or diagnostic viewer** — The library can
  support regulated software, research tools, and production pipelines, but
  diagnostic interpretation, clinical display calibration, and medical-device
  claims require separate validation, documentation, and controls.

## License

DICOMForge is distributed under the MIT License for personal and commercial
use. See [LICENSE](LICENSE).
