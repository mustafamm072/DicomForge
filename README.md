# DICOMForge

DICOMForge is an early Python DICOM processing library for medical imaging
applications. The goal is a lightweight core with typed, predictable APIs and
planned optional integrations for heavier work such as pixel codecs,
networking, and DICOMweb.

This repository is intentionally starting with a small, solid core:

- typed tags and value access
- transfer syntax classification
- pluggable codec registry
- de-identification profiles, deterministic UID remapping, and audit reports
- pixel metadata and safety checks
- VOI window, rescale, and photometric interpretation helpers
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
[docs/roadmap.md](docs/roadmap.md). For repository naming and discoverability
notes, see [docs/branding.md](docs/branding.md).

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

plan = AnonymizationPlan.basic_profile(
    uid_salt="project-specific-secret",
    private_tag_action=PrivateTagAction.REMOVE,
)
report = plan.apply_with_report(dataset)

assert dataset.get("PatientName") == "Anonymous"
assert dataset.get("PatientIdentityRemoved") == "YES"
assert report.private_tags_removed == 1
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

## License

DICOMForge is distributed under the MIT License for personal and commercial
use. See [LICENSE](LICENSE).
