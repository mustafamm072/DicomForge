# DICOMForge

[![DOI](https://zenodo.org/badge/1222011062.svg)](https://doi.org/10.5281/zenodo.20192747)

DICOMForge is a Python DICOM processing library for medical imaging
applications. The goal is a lightweight core with typed, predictable APIs,
explicit safety boundaries, and optional integrations for heavier work such as
pixel codecs, wire-compatible networking, and DICOMweb.

This repository is intentionally starting with a small, solid core:

- typed tags and value access
- transfer syntax classification
- pluggable codec registry
- de-identification profiles, deterministic UID remapping, and audit reports
- pixel metadata and safety checks
- VOI window, rescale, and photometric interpretation helpers
- optional pydicom-backed compressed pixel decode and frame iteration
- async networking primitives for association lifecycle and DIMSE-style commands
- DICOMweb query, retrieval, upload, and multipart helpers
- optional `pydicom` IO backend
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
- de-identification planning with deterministic UID remapping and audit reports
- pydicom-backed file IO behind a smaller application API
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
dicomforge.pixels          pixel metadata safety checks and small value helpers
dicomforge.anonymize       starter de-identification plans and audit reports
dicomforge.io              optional pydicom read/write adapter
dicomforge.network         async command lifecycle primitives, not DICOM UL PDUs
dicomforge.dicomweb        QIDO/WADO/STOW helpers with injectable HTTP transport
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

Optional pydicom-backed reading:

```python
from dicomforge.io import read

dataset = read("image.dcm", stop_before_pixels=True)
print(dataset.get("PatientName"))
```

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

### Fixed in 0.7.0

- **`Tag.SliceThickness` wrong group/element** — The tag was registered as
  `(0050,0018)` (DeviceDiameter) instead of the correct `(0018,0050)`.
  Any dataset lookup using `Tag.SliceThickness` would silently return `None`
  on real DICOM files. Fixed in v0.7.0.

- **`io._KNOWN_VR` incomplete** — Approximately 30 tags including
  `AccessionNumber`, all date/time tags (`StudyDate`, `SeriesDate`, …),
  `InstitutionName`, `ReferringPhysicianName`, `FrameOfReferenceUID`,
  `PatientIdentityRemoved`, and `DeidentificationMethod` were missing from
  the internal VR map. Writing these tags via `io.write()` produced VR `"UN"`
  instead of the correct DICOM VR. Fixed in v0.7.0.

### Current limitations

- **`dicomforge.network` is not wire-compatible DIMSE** — The async networking
  module uses a lightweight JSON framing protocol, not the DICOM Upper Layer
  PDU wire format defined in PS3.8. It is not interoperable with real PACS
  systems over the wire. Wire-compatible DIMSE via a `pynetdicom` bridge is
  planned for a `dicomforge-network` package in a future release.

- **Compressed pixel access is delegated to pydicom** — `adapt.pixel_array`
  can decode compressed transfer syntaxes when pydicom and the relevant pydicom
  pixel plugin are installed. DICOMForge does not bundle JPEG, JPEG-LS,
  JPEG 2000, or RLE codec implementations.

## License

DICOMForge is distributed under the MIT License for personal and commercial
use. See [LICENSE](LICENSE).
