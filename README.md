# DICOMForge

DICOMForge is a Python DICOM processing library for medical imaging
applications. The goal is a lightweight core with typed, predictable APIs,
explicit safety boundaries, and optional integrations for heavier work such as
pixel codecs, wire-compatible networking, and DICOMweb.

This repository is intentionally starting with a small, solid core:

- typed tags and value access
- transfer syntax classification
- pluggable codec registry
- de-identification planning
- pixel metadata and safety checks
- VOI window, rescale, and photometric interpretation helpers
- async networking primitives for association lifecycle and DIMSE-style commands
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

## Development

Run the standard-library test suite:

```bash
PYTHONPATH=src python3 -m unittest
```

Examples live in [examples](examples).
