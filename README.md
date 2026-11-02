# DICOMForge

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20192747.svg)](https://doi.org/10.5281/zenodo.20192747)
[![CI](https://github.com/mustafamm072/DicomForge/actions/workflows/ci.yml/badge.svg)](https://github.com/mustafamm072/DicomForge/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%20%E2%80%93%203.14-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Core](https://img.shields.io/badge/core-dependency--free-brightgreen)

**Lightweight DICOM processing, explainable collection validation, and reproducible
research data releases.** DICOMForge has no mandatory third-party dependencies.
Use the Python API or the same workflows from a small JSON command-line tool.

Version 0.12 fixes the end-to-end correctness problems identified in the
[critical review](docs/critical-review-2026-10-25.md). See the
[migration guide](docs/migration-0.12.md) before upgrading: backend selection,
UID mappings, reports, and some validation outcomes deliberately change.

## Install

```bash
python -m pip install dicomforge
# Choose only the integrations you need:
python -m pip install 'dicomforge[pixels]'     # NumPy/Pillow arrays and previews
python -m pip install 'dicomforge[pydicom]'   # explicit pydicom file adapter
python -m pip install 'dicomforge[transport]' # requests pooling/TLS/streaming
python -m pip install 'dicomforge[network]'   # pynetdicom integration
```

Python 3.9–3.14 are supported. Optional dependency versions are selected by pip
for the interpreter. CI tests installed wheels both without extras and with
extras on every supported Python version, plus a pinned pydicom 2.4 job.

## Read, edit, and write

```python
from dicomforge import dcmread, dcmwrite

metadata = dcmread('image.dcm', stop_before_pixels=True)
print(metadata.get('Modality'))

dataset = dcmread('image.dcm')
dataset['SeriesDescription'] = 'Reviewed acquisition'
dcmwrite('reviewed.dcm', dataset, overwrite=False)
```

`backend='auto'` always selects the native backend. Installing an extra does not
change the default. Select `backend='pydicom'` explicitly when needed. Both
backends preserve explicit VRs, normalize nested sequences, and convert
compressed fragments through one shared representation.

Writes are staged beside the destination and published atomically. Use
`overwrite=False` to protect existing files. Metadata-only datasets cannot be
saved accidentally: re-read the full file or call `DicomFile.load_pixels()`.
Changing native byte order preserves numerical pixel values; compression changes
require explicit transcoding.

The native reader uses a memory-mapped source so an ordinary metadata-only scan
does not read or copy the pixel payload. Deflated files still require bounded
whole-body inflation; the default decompressed limit is 512 MiB. This is not a
general remote/deferred-bulk-data reader.

## Validate collections and plan resource use

```python
from dicomforge import inspect_collection

report = inspect_collection(
    ['slice1.dcm', 'slice2.dcm'],
    require_reference_closure=True,
    max_input_bytes=512 * 1024**2,
    max_frame_bytes=64 * 1024**2,
)
print(report.status)      # accepted, needs_review, or quarantined
print(report.to_dict())   # stable codes, input ordinals, explicit unchecked scopes
```

Conventional CT/MR checks cover repeated instance identities, inconsistent
series metadata, orientation/spacing, repeated planes, irregular slice spacing,
and missing references when a closed collection is requested. An accepted
metadata report does not establish that an acquisition is complete or that
pixels are anonymous. Enhanced/multiframe geometry remains explicitly unassessed.

Validate existing pydicom datasets without copying their pixel buffers:

```python
from dicomforge import validate_collection, validate_elements_detailed

# raw is an existing pydicom Dataset:
# report = validate_collection([raw])
# issues = validate_elements_detailed(raw)
```

Use `validate_dataset_detailed` for structural checks,
`validate_elements_detailed` for VR/VM and UID checks with indexed paths, and
`validate_for_sop_class_detailed` for the declared subset of mandatory image
attributes. These are distinct scopes, not a full IOD conformance certificate.

## Reproducible research releases

```python
from pathlib import Path
from dicomforge import ReleasePolicy, release_collection

policy = ReleasePolicy(
    namespace='trial-a',
    key=Path('/secure/project.key').read_bytes(),  # at least 32 secret bytes
    longitudinal_dates=True,
    pixels_reviewed=True,  # explicit external review, not automated detection
)
manifest = release_collection(
    ['slice1.dcm', 'slice2.dcm'], 'release', policy, dry_run=True,
)
# Execute the reviewed plan:
# manifest = release_collection(paths, 'release', policy)
# Resume an interrupted job with the identical source collection, policy, and key:
# manifest = release_collection(paths, 'release', policy, resume=True)
```

The release scope is conventional CT/MR metadata. Project-keyed subject
pseudonyms include PatientID and issuer; date shifts are consistent per subject;
UID mappings preserve reference equality. Outputs use remapped instance UIDs,
not source filenames. Each output is reopened and structurally checked before
checkpointing. Resume verifies source tokens, output digests, policy identity,
and tool version. Source files are protected; output publication is per instance,
not one filesystem transaction for the whole cohort.

Manifests omit original identifiers, source filenames, and secrets. Even keyed
source tokens, output hashes, and pseudonyms are controlled, potentially linkable
data. Store manifests accordingly. The starter profile and release policy do
not implement every PS3.15 option or inspect pixels, recognizable anatomy,
overlays, documents, or structured report content. Unsupported content requires
review. See [safety](docs/safety.md) and [conformance](docs/conformance.md).

## CLI

```bash
dicomforge --version
dicomforge inventory study/
dicomforge validate study/ --max-frame-bytes 67108864
dicomforge plan study/ --output release/ --namespace trial-a \
  --key-file /secure/project.key --pixels-reviewed
dicomforge release study/ --output release/ --namespace trial-a \
  --key-file /secure/project.key --pixels-reviewed --resume
```

Directory discovery includes `*.dcm`; pass individual paths for extensionless
files. Commands emit JSON. Exit code 0 means the declared checks accepted the
operation, 1 means collection findings need attention, and 2 means usage or
operational failure. Error output omits sensitive paths and backend values.
`python -m dicomforge` uses the same entry point. Keep secret key material in a
file, never in command arguments or a committed example.

## Pixels and lossless compression

```python
from dicomforge import compress_pixel_data, decompress_pixel_data
from dicomforge.adapt import pixel_array, iter_pixel_frames, to_jpeg_preview

# Pure-Python RLE, no codec wheels required:
compress_pixel_data(dataset)
dcmwrite('rle.dcm', dataset, overwrite=False)
decompress_pixel_data(dataset)

# Optional NumPy/Pillow:
frame = pixel_array(dataset, frame=0, apply_rescale=True)
for frame in iter_pixel_frames(dataset):
    pass
thumbnail = to_jpeg_preview(dataset)
```

Native arrays normalize stored-bit signedness and support bit-packed, 8/16/32/64
bit native integers. RLE image encoding is restricted to the supported standard
8/16-bit combinations. Preview generation applies modality rescale before VOI,
handles the first multivalued window, and converts supported YBR data to RGB.
JPEG previews are 8-bit display artifacts, not diagnostic derived images.
JPEG-family codecs remain optional pydicom plugins. The pydicom 3 adapter uses
frame-specific decoding; the legacy pydicom 2 adapter may materialize a stack.

## DICOMweb

QIDO/WADO/STOW helpers accept injectable transports. Optional requests-backed
transport supports pooling, TLS, bearer auth, and deterministic stream closure.
Retries default to safe methods and replayable bodies; upload generators are
never blindly retried. Call `response.store_result()` for STOW per-instance
successes/warnings/failures; HTTP 2xx alone is insufficient.

`client.retrieve_study_to(study_uid, directory)` streams to staged, non-overwriting
files with configurable per-instance limits. `iter_multipart_chunks` supports
custom sinks without holding an entire instance in memory. The convenience
multipart-parts iterator necessarily buffers one complete part. Truncated
responses fail explicitly. BulkDataURI values remain typed, unresolved
references and are never fetched automatically.

The old `dicomforge.network` framed-JSON simulator is retained for compatibility
and tests. It is experimental and is not DICOM Upper Layer/DIMSE. Use pynetdicom
for production PACS networking.

## Development and adoption evidence

```bash
python -m pip install -e '.[dev]'
python -m unittest
python -m ruff check src tests tools
python -m mypy src/dicomforge
python -m build
```

[Compatibility](docs/compatibility.md), [architecture](docs/architecture.md),
[contributing](CONTRIBUTING.md), [release notes](CHANGELOG.md), and
[security](SECURITY.md) define the supported contract and remaining limits.
`tools/check_matrix.py` tests actual wheels under supplied Python interpreters;
`tools/check_package.py` verifies packaging and the lightweight import contract.
The bundled standard dictionary is versioned and has documented
[provenance/licensing](src/dicomforge/data/README.md). Cite the project using
[CITATION.cff](CITATION.cff).
